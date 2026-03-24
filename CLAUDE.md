# Bilal Cast — Claude Project Context

## What this project is
Standalone MicroPython **1.24** app for Pico W that plays the athan (call to prayer) at the correct times by casting MP3s to a Chromecast device. Key files: `bilalcast/main.py`, `bilalcast/cast.py`.

**MicroPython version: 1.24 (rp2 port). Do not assume 1.25+ APIs are available.** Notable 1.24 limitations:
- `next(iterator, default)` with a default value is not supported — use an explicit `for` loop with `break` instead

## Standalone scope
`main.py` is the standalone runtime. It depends on: `cast.py`, `discovery.py`, `prayer.py`, `logger.py`, `captive_portal.py` (for onboarding), and the mDNS client (in `mdns_client/`). `bilal_server.py`, `scheduler.py`, `store.py`, `device_registry.py` are a separate full web server stack — **do not use these in main.py**.

## Architecture
- `main.py` — entry point, fully synchronous. Boots, connects WiFi, sets RTC, discovers Chromecast, fetches location + next prayer, sleeps until it, plays, resets.
- `cast.py` — `Chromecast(host, port)` class. `play_url(url)` returns `True` if LOAD was sent without error, `False` if transport_id timed out.
- `captive_portal.py` — async phew server for onboarding (AP mode).
- `discovery.py` — `resolve_cast_device(local_ip, name)` and `cast_url(url, host, port)`.
- `prayer.py` — `get_location()`, `get_next_prayer(lat, lon)`, `pre_athan_time(hhmm)`, `seconds_until(hhmm)`, `ATHANS`, `PRE_ATHAN`.
- `logger.py` — `log(msg)`, `send_ntfy(msg)`, `configure(debug, device_name)`.
- `device_registry.py` — async mDNS scanner, used by bilal_server only.

---

## main.py — current state

### User-configured constants (top of file)
- `DEBUG` — `True` = print to console, `False` = send via ntfy

### Runtime vars (populated from config.json at boot)
`SSID`, `PASSWORD`, `CAST_DEVICE_NAME` — read from `config.json`. No address field; location is auto-detected via IP geolocation.

### Key functions
- `log(msg)` — print if DEBUG, else send_ntfy. send_ntfy's own error handler stays as print (avoid recursion).
- `set_rtc()` — uses ntptime (NTP/UDP); guards against silent failure by checking year >= 2024.
- `get_location()` — hits `http://ip-api.com/json`; returns `(lat, lon)`.
- `get_next_prayer(lat, lon)` — calls aladhan `nextPrayer/{date}` with lat/lon; filters timings to ATHANS dict; try/finally on resp.close().
- `pre_athan_time(hhmm)` — computes 10-min-before, midnight-safe.
- `seconds_until(hhmm)` — midnight-safe seconds until HH:MM.
- `resolve_cast_device(local_ip, name)` — 3-step: (1) load cache + verify reachable, (2) mDNS scan (10 attempts × 3s), (3) reset.
- `cast_url(url, host, port, max_retries=3)` — retries on exception or False (transport_id timeout); disconnects on failure/retry only. On success, connection is intentionally left open — `machine.reset()` tears it down after the 200s sleep. Closing immediately after LOAD was causing intermittent cast failures.
- `ensure_wifi()` — checks isconnected() before casting, reconnects if dropped.
- `check_factory_reset()` — hold BOOTSEL 10s at boot to wipe config and reopen captive portal.

### main() boot flow
```
logger.configure(DEBUG, None)
check_factory_reset() → if confirmed → clear config files → asyncio.run(captive_portal())
load_config()         → if None      → asyncio.run(captive_portal())
populate SSID / PASSWORD / CAST_DEVICE_NAME
logger.configure(DEBUG, CAST_DEVICE_NAME)
connect_to_wifi_with_retries(SSID, PASSWORD)
set_rtc()
resolve_cast_device(local_ip, CAST_DEVICE_NAME)
send_ntfy("online: YYYY-MM-DD HH:MM UTC")
get_location()  →  get_next_prayer(lat, lon)
pre_athan_time() + seconds_until()
time.sleep(max(0, secs - 30))
poll every 1s until HH:MM == target (60s safety deadline)
ensure_wifi()
cast_url(audio_file, cast_host, cast_port)
send_ntfy(label or "cast failed: ...")
machine.reset()
```

---

## config.json schema
```json
{
  "ssid": "...",
  "password": "...",
  "cast_device_name": "Living Room"
}
```
No address field — location is auto-detected via IP geolocation (`ip-api.com`) at runtime.

---

## Captive portal onboarding
Headless onboarding: no config → device creates AP "Bilal Cast Onboarding" → user connects → fills form (SSID, password, cast device name) → saves config.json → reboots → runs normally.

- `captive_portal.py` saves 3 fields to config.json: `ssid`, `password`, `cast_device_name`
- `www/index.html` — form with SSID dropdown (populated from scan), password (plain text), cast device name
- `www/configured.html` — save-confirmed + rebooting message

### Wi-Fi scan in captive portal
Before starting the AP, `captive_portal.py` activates STA, waits 2 seconds for hardware to settle, calls `wlan.scan()`, sorts results by RSSI, deduplicates, and builds an HTML `<option>` string passed to the index template as `network_options`. The scan is blocking but safe — the AP isn't up yet so no requests can arrive. If the scan fails, `network_options` is empty and the form falls back to manual SSID entry.

The template uses `{{network_options + ""}}` (not `{{network_options}}`) to bypass phew's automatic HTML-escaping, which would otherwise turn `<option>` tags into literal text.

The dropdown has a "Other (type below)" option at the bottom. Selecting it reveals a text input for manual entry. Selecting a scanned network auto-fills a hidden text input that is submitted as `ssid`.

### Important uasyncio note
`captive_portal.py` uses `while True: await asyncio.sleep_ms(1000)` (not `loop.run_forever()`) so that `asyncio.run(captive_portal())` from sync `main.py` works correctly in uasyncio.

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
