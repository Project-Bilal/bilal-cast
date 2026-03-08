# Bilal Cast — Claude Project Context

## What this project is
Standalone MicroPython app for ESP32/Pico W that plays the athan (call to prayer) at the correct times by casting MP3s to a Chromecast device. Key files: `bilalcast/main.py`, `bilalcast/cast.py`.

## Standalone scope
`main.py` + `cast.py` are the standalone runtime. They only depend on `cast.py`, the mDNS client (baked into firmware), and phew (for captive portal onboarding). `bilal_server.py`, `scheduler.py`, `store.py`, `device_registry.py` are a separate full web server stack — **do not use these in main.py**.

## Architecture
- `main.py` — entry point, fully synchronous. Boots, connects WiFi, sets RTC, discovers Chromecast, fetches next prayer, sleeps until it, plays, resets.
- `cast.py` — `Chromecast(host, port)` class. `play_url(url)` returns `True`/`False`.
- `captive_portal.py` — async phew server for onboarding (AP mode).
- `device_registry.py` — async mDNS scanner, used by bilal_server only.

---

## main.py — current state

### User-configured constants (top of file)
- `CAST_HOST`, `CAST_PORT` — hardcoded fallback if mDNS discovery fails
- `CAST_DEVICE_NAME` — mDNS friendly name (matches name shown in Google Home app)
- `DEBUG` — `True` = print to console, `False` = send via ntfy

### Runtime vars (set from config.json at boot — PENDING)
`SSID`, `PASSWORD`, `ADDRESS`, `CAST_DEVICE_NAME` are currently still hardcoded. Next session replaces these with reads from `config.json`.

### Key functions
- `log(msg)` — print if DEBUG, else send_ntfy. send_ntfy's own error handler stays as print (avoid recursion).
- `set_rtc()` — uses ntptime (NTP/UDP); guards against silent failure by checking year >= 2024.
- `get_next_prayer()` — calls `nextPrayerByAddress` API; filters timings to ATHANS dict; try/finally on resp.close().
- `pre_athan_time(hhmm)` — computes 10-min-before, midnight-safe.
- `seconds_until(hhmm)` — midnight-safe seconds until HH:MM.
- `resolve_cast_device(local_ip)` — 3-step: (1) load cache + verify reachable, (2) mDNS scan, (3) hardcoded fallback.
- `_mdns_find(local_ip, name)` — wraps TXTServiceDiscovery in asyncio.run(); 10 attempts.
- `cast_url(url, host, port, max_retries=3)` — retries on exception or False return; always disconnects in finally.
- `ensure_wifi()` — checks isconnected() before casting, reconnects if dropped.

### main() boot flow
```
load_config()  →  if None → asyncio.run(captive_portal())   ← PENDING
connect_to_wifi_with_retries(SSID, PASSWORD)
set_rtc()
send_ntfy("online")
resolve_cast_device(local_ip)
get_next_prayer()
pre_athan_time() + seconds_until()
if secs_to_pre < secs_to_prayer → sleep → play PRE_ATHAN
else                             → sleep → play ATHANS[prayer]
send_ntfy(label or "cast failed: ...")
machine.reset()
```

---

## NEXT SESSION — Captive Portal Onboarding

### Goal
Headless onboarding: no config → device creates AP → user connects → fills form → saves config.json → reboots → runs normally.

### Files to change

**1. `main.py`**
- Remove hardcoded `SSID`, `PASSWORD`, `ADDRESS`, `CAST_DEVICE_NAME`
- Add `CONFIG_FILE = "config.json"`
- Add `SSID = PASSWORD = ADDRESS = CAST_DEVICE_NAME = None` as module-level vars
- Add `url_encode()` (for address before API call — do NOT use the one in utils.py, keep main.py standalone)
- Add `load_config()` — reads config.json, returns dict or None
- Update `main()`: set `global SSID, PASSWORD, ADDRESS, CAST_DEVICE_NAME` → load config → if None → `asyncio.run(captive_portal())` → else populate globals

**2. `captive_portal.py`**
- Drop `from utils import WIFI_FILE`; hardcode `CONFIG_FILE = "config.json"` directly
- Save all 4 fields (ssid, password, address, cast_device_name) to config.json
- Replace `loop.run_forever()` with `while True: await asyncio.sleep_ms(1000)` so `asyncio.run(captive_portal())` from main.py works correctly in uasyncio

**3. `www/index.html`**
- Add Address text field
- Add Cast Device Name text field
- **ONE OPEN QUESTION:** confirm placeholder/hint copy before implementing:
  - Address placeholder: `123 Main St, Seattle WA 98101` ?
  - Cast Device Name hint: "Found in Google Home app under device settings" ?

**4. `www/configured.html`**
- Remove bilalcast.lan / bilalcast.local links (not relevant in standalone mode)
- Simplify to save-confirmed + rebooting message

### config.json schema
```json
{
  "ssid": "...",
  "password": "...",
  "address": "123 Main St, Seattle WA",
  "cast_device_name": "Living Room"
}
```
Address stored raw (user types plain text). URL-encoded when building the aladhan API URL inside `get_next_prayer()`.

### Important uasyncio note
`captive_portal.py` uses `loop.run_forever()`. Calling `asyncio.run(captive_portal())` from sync main.py conflicts because the loop is already running. Fix: replace `loop.run_forever()` with `while True: await asyncio.sleep_ms(1000)`.

---

## Coding conventions
- All `print()` calls go through `log()` — never add raw `print()` calls
- Always `try/finally` around `resp.close()` in HTTP calls
- Always `try/finally` around `cc.disconnect()` in Chromecast calls
- `send_ntfy()` is non-fatal — always wrapped in try/except
- No over-engineering; keep solutions minimal
