# Bilal Cast — Claude Project Context

## What this project is
Standalone MicroPython **1.24** app for Pico W that plays the athan (call to prayer) at the correct times by casting MP3s to a Chromecast device. Key files: `bilalcast/main.py`, `bilalcast/cast.py`.

**MicroPython version: 1.24 (rp2 port). Do not assume 1.25+ APIs are available.** Notable 1.24 limitations:
- `next(iterator, default)` with a default value is not supported — use an explicit `for` loop with `break` instead

## Standalone scope
`main.py` is the standalone runtime. It depends on: `cast.py`, `discovery.py`, `prayer.py`, `logger.py`, `captive_portal.py` (for onboarding), `status.py` (HTTP status server), and the mDNS client (in `mdns_client/`). `bilal_server.py`, `scheduler.py`, `store.py`, `device_registry.py` are a separate full web server stack — **do not use these in main.py**.

## Architecture
- `main.py` — entry point, **fully async** (`asyncio.run(main())`). Boots, connects WiFi, sets RTC, discovers Chromecast, fetches all prayer times, then runs the async scheduler loop indefinitely (no machine.reset() after each prayer).
- `cast.py` — `Chromecast(host, port)` class. `play_url(url)` returns `True` if LOAD was sent without error, `False` if transport_id timed out.
- `captive_portal.py` — async phew server for onboarding (AP mode).
- `discovery.py` — `resolve_cast_device(local_ip, name)` returns `(host, port)` or `(None, None)` on failure. `cast_url(url, host, port)` returns `(ok, error_str)`.
- `prayer.py` — location, geocoding, and prayer time functions (see below).
- `logger.py` — `log(msg)`, `send_ntfy(msg)`, `configure(debug, device_name)`.
- `status.py` — `start_status_server(state, ...)`. Runs a phew HTTP server as an asyncio task on port 80.
- `device_registry.py` — async mDNS scanner, used by bilal_server only.

---

## main.py — current state

### User-configured constants (top of file)
- `DEBUG` — `True` = print to console, `False` = send via ntfy
- `ACTIVATION_URL` — URL used by the `/test` endpoint (test speakers button)
- `CONFIG_FILE = "config.json"`
- `CAST_STATE_FILE = "cast_state.json"` — persists last cast result across reboots

### Runtime vars (populated from config.json at boot)
- Required: `SSID`, `PASSWORD`, `CAST_DEVICE_NAME`
- Optional: `DEVICE_HOSTNAME` (default `"bilalcast"`), `PRE_ATHAN_MINS` (default `10`), `CALC_METHOD` (default `2`), `LAT_ADJ_METHOD` (default `1`), `MIDNIGHT_MODE` (default `0`), `SCHOOL` (default `0`), `_cfg_lat`/`_cfg_lon` (manual coords), `_cfg_address` (address string)

### Shared state dict
`state` is a mutable dict shared between the HTTP status server and the prayer scheduler:
```python
state = {
    "prayer_times": {},       # {prayer: "HH:MM"} for all 5 prayers today
    "next_prayer": None,
    "next_prayer_time": None,
    "cast_host": None,
    "cast_port": None,
    "last_cast_ok": None,     # persisted to cast_state.json
    "last_cast_label": None,  # persisted to cast_state.json
    "lat": None, "lon": None,
    "address": None,          # configured address string (if no lat/lon)
    "lat_adj": 1,
    "midnight": 0,
    "school": 0,
    "local_ip": None,
    "boot_epoch": 0,
    "device_name": None,
    "hostname": "bilalcast",
}
```

### Key functions
- `led_blink()` / `led_solid()` — hardware timer-based LED blink (boot indicator); solid = ready.
- `set_rtc(max_attempts=20)` — tries multiple NTP hosts (`_NTP_HOSTS` list) in rotation; guards against silent failure by checking year >= 2024.
- `adjust_rtc(utc_offset_secs)` — adjusts RTC to local time using UTC offset returned by `get_location()`.
- `check_factory_reset()` — hold BOOTSEL 10s at boot to wipe config and reopen captive portal.
- `ensure_wifi()` — checks `isconnected()`, reconnects if dropped.
- `_save_cast_state(ok, label)` — updates `state["last_cast_ok/label"]` and writes to `cast_state.json`.
- `_get_prayer_times(lat, lon, method, tz)` — fetches prayer times using lat/lon endpoint if available, else address endpoint via `_cfg_address`.
- `do_cast(url, label)` — **async**. Ensures WiFi, re-discovers cast device if host unknown, calls `cast_url()`, calls `_save_cast_state()`, sends ntfy.
- `run_schedule()` — **async** loop. Iterates `ATHANS_ORDER` each day: sleeps until pre-athan, fires pre-athan cast, sleeps until prayer, fires prayer cast, sleeps 200s. After all day's prayers: sleeps until 00:01, re-syncs RTC, re-fetches location + prayer times.

### main() boot flow
```
logger.configure(True, None)          # always print before WiFi is up
led_blink()
check_factory_reset() → if confirmed → clear config + cast_state files → await captive_portal()
load_config()         → if None      → await captive_portal()
populate SSID / PASSWORD / CAST_DEVICE_NAME + optional fields from config
connect_to_wifi_with_retries(SSID, PASSWORD, hostname=DEVICE_HOSTNAME)
logger.configure(DEBUG, CAST_DEVICE_NAME)
geo_lat, geo_lon, utc_offset, tz_string = get_location()   # always called for timezone
set_rtc()
if utc_offset: adjust_rtc(utc_offset)
populate state dict (local_ip, device_name, hostname, boot_epoch)
load cast_state.json → restore last_cast_ok / last_cast_label if present
start_status_server(state, ...)        # HTTP server on port 80 as asyncio task
start_mdns_responder(local_ip, local_ip)
cast_host, cast_port = await resolve_cast_device(local_ip, CAST_DEVICE_NAME)
send_ntfy("online: YYYY-MM-DD HH:MM")

# Location resolution (in priority order):
# 1. _cfg_lat + _cfg_lon present → use directly
# 2. _cfg_address present, no lat/lon → try Nominatim geocoding
#    → success: set _cfg_lat/_cfg_lon, use lat/lon endpoint
#    → failure: lat=None, lon=None → try address endpoint once
#      → address endpoint fails: fall back to geo_lat/geo_lon from IP geolocation
# 3. Neither → use geo_lat/geo_lon from IP geolocation

state["prayer_times"] = _get_prayer_times(lat, lon, CALC_METHOD, _tz_string)
led_solid()
await run_schedule()                   # runs indefinitely; no machine.reset()
```

### resolve_cast_device behaviour
Returns `(host, port)` on success or `(None, None)` on failure (no reset). `do_cast()` handles the `None` case by attempting re-discovery at cast time.

### cast_url behaviour
Always disconnects after each attempt (no persistent connection). Returns `(ok, error_str)`.

---

## config.json schema
```json
{
  "ssid": "...",
  "password": "...",
  "cast_device_name": "Living Room",
  "hostname": "bilalcast",
  "pre_athan_mins": "10",
  "method": "2",
  "lat_adj": "1",
  "midnight": "0",
  "school": "0",
  "address": "London, UK",
  "lat": "51.5",
  "lon": "-0.1"
}
```
Required fields: `ssid`, `password`, `cast_device_name`. All others are optional.

Location priority: explicit `lat`+`lon` > `address` (Nominatim geocoded, then Aladhan address endpoint) > IP geolocation.

Aladhan params:
- `method` — calculation authority (1–15, default 2 = ISNA)
- `lat_adj` — latitude adjustment method (0=None, 1=Middle of Night, 2=One-Seventh, 3=Angle-Based; default 1)
- `midnight` — midnight mode (0=Standard, 1=Jafari; default 0)
- `school` — Asr juristic school (0=Shafi standard, 1=Hanafi; default 0)

---

## cast_state.json
Written by `_save_cast_state()` after every cast attempt. Read at boot to restore the last cast result on the status page without waiting for the next prayer.
```json
{"ok": true, "label": "Maghrib, 18:42"}
```
Deleted on factory reset (both BOOTSEL path and `/factory-reset` route).

---

## prayer.py — key functions
- `get_location()` — IP geolocation via ip-api.com. Returns `(lat, lon, utc_offset_secs, timezone_str)`. Used for RTC timezone regardless of address config.
- `geocode_address(address)` — Nominatim forward geocoding. Returns `(lat, lon)` floats or `(None, None)`.
- `_url_encode(s)` — minimal percent-encoder safe for MicroPython; handles UTF-8 non-ASCII chars.
- `get_all_prayers(lat, lon, method, timezone, lat_adj, midnight, school)` — Aladhan lat/lon endpoint, retries forever.
- `get_all_prayers_by_address(address, method, timezone, lat_adj, midnight, school)` — Aladhan `timingsByAddress` endpoint, retries forever.
- `try_prayers_by_address(address, method, timezone, lat_adj, midnight, school)` — single attempt, returns dict or `None` (used for boot fallback probe).
- `pre_athan_time(hhmm, mins=10)`, `seconds_until(hhmm)`, `ATHANS`, `ATHANS_ORDER`, `PRE_ATHAN`.

---

## Captive portal onboarding
Headless onboarding: no config → device creates AP "Bilal Cast Onboarding" → user connects → fills form (SSID, password, cast device name) → saves config.json → reboots → runs normally.

- `captive_portal.py` saves form fields to config.json (whatever the form submits)
- `www/index.html` — form with SSID dropdown (populated from scan), password (plain text), cast device name
- `www/configured.html` — save-confirmed + rebooting message

### Wi-Fi scan in captive portal
Before starting the AP, `captive_portal.py` activates STA, waits 2 seconds for hardware to settle, calls `wlan.scan()`, sorts results by RSSI, deduplicates, and builds an HTML `<option>` string passed to the index template as `network_options`. The scan is blocking but safe — the AP isn't up yet so no requests can arrive. If the scan fails, `network_options` is empty and the form falls back to manual SSID entry.

The template uses `{{network_options + ""}}` (not `{{network_options}}`) to bypass phew's automatic HTML-escaping, which would otherwise turn `<option>` tags into literal text.

The dropdown has a "Other (type below)" option at the bottom. Selecting it reveals a text input for manual entry. Selecting a scanned network auto-fills a hidden text input that is submitted as `ssid`.

### Important uasyncio note
`captive_portal.py` uses `app.run_as_task(loop)` + `while True: await asyncio.sleep_ms(1000)` so that it works correctly when called with `await _portal()` from the async `main()`.

---

## HTTP status server (status.py)
Runs permanently after boot as an asyncio task on port 80. Access at `http://bilalcast.local/`.

- `GET /` — status page: time (HH:MM AM/PM · MM-DD-YYYY), WiFi signal in header, prayer times table, last cast result, IP + hostname URL at bottom.
- `GET /settings` — settings form: address input with Nominatim autocomplete + prayer times preview, lat/lon override (hidden, auto-filled), pre-athan minutes, calc method, lat adjustment method, Asr school, midnight mode, cast device name.
- `POST /settings` — saves settings to config.json, triggers `machine.reset()` after 1s.
- `POST /test` — fires a test cast of `ACTIVATION_URL` as an asyncio task.
- `POST /factory-reset` — wipes config.json, cast_device.json, cast_state.json; triggers reset.

### Settings page — address field behaviour
- Visible `name=address` text input submitted as-is (human-readable).
- Hidden `name=lat` / `name=lon` fields auto-populated by JS when user selects a Nominatim suggestion.
- If lat+lon submitted: saved alongside address (for display). If address only (no geocoding selected): lat/lon cleared from config, address endpoint used at next boot.
- "Preview Prayer Times" button fetches Aladhan API directly from the browser (no device round-trip).

---

## Building the firmware

The UF2 firmware is built via Docker using `Dockerfile.micropython.1.24.rp2`.

```bash
docker build -t bilalcast-rp2 -f Dockerfile.micropython.1.24.rp2 .
docker run -v $(pwd):/tmp/bilalcast-build bilalcast-rp2
```

Use the `/build` skill as a shortcut — it runs both commands in sequence.

---

## Coding conventions
- All `print()` calls go through `log()` — never add raw `print()` calls
- Always `try/finally` around `resp.close()` in HTTP calls
- Always `try/finally` around `cc.disconnect()` in Chromecast calls
- `send_ntfy()` is non-fatal — always wrapped in try/except
- No over-engineering; keep solutions minimal
