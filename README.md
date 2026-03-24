# Bilal Cast

Standalone MicroPython app for the Raspberry Pi Pico W that plays the athan (call to prayer) at the correct times by casting MP3s to a Chromecast device.

## How it works

1. On boot, the device connects to Wi-Fi using saved credentials
2. Syncs the clock via NTP
3. Discovers the Chromecast on the local network via mDNS
4. Detects location automatically via IP geolocation
5. Fetches the next prayer time from the Aladhan API
6. Sleeps until the prayer time, then casts the athan audio to the Chromecast
7. Resets and repeats for the next prayer

## First-time setup

The device uses a captive portal for onboarding — no app required.

1. Power on the Pico W with no config present
2. It will create a Wi-Fi access point named **"Bilal Cast Onboarding"**
3. Connect to that network from your phone or computer
4. Navigate to `http://bilalcast.net` — you'll be redirected automatically
5. Select your Wi-Fi network from the dropdown (scanned automatically) or choose "Other" to type it manually. Enter your password and the name of your Chromecast device (found in the Google Home app under device settings)
6. Tap **Save & Connect** — the device will reboot, connect to your network, and play a short activation message on your Chromecast to confirm it's working

## Factory reset

Hold the **BOOTSEL** button for 10 seconds while the device is booting. The LED will go solid then resume blinking to confirm. The device will clear its config and reopen the captive portal.

## Building the firmware

The UF2 firmware is built via Docker. Requires Docker installed and running.

```bash
docker build -t bilalcast-rp2 -f Dockerfile.micropython.1.24.rp2 .
docker run -v $(pwd):/tmp/bilalcast-build bilalcast-rp2
```

Flash the output UF2 to the Pico W by holding BOOTSEL while plugging it in, then copying the file to the mounted drive.

If you have Claude Code, you can use the `/build` skill as a shortcut — it runs both commands for you.

## Hardware

- Raspberry Pi Pico W
- Any Chromecast device on the same Wi-Fi network

## Firmware

Built for **MicroPython 1.24** (rp2 port). Do not flash 1.25+ — mDNS scanning is broken on later versions.

## Key files

| File | Purpose |
|---|---|
| `bilalcast/main.py` | Entry point — boot, WiFi, prayer scheduling, cast |
| `bilalcast/cast.py` | Chromecast Cast protocol over TCP/SSL |
| `bilalcast/discovery.py` | mDNS device discovery and cast retry logic |
| `bilalcast/prayer.py` | IP geolocation, Aladhan API, prayer time helpers |
| `bilalcast/captive_portal.py` | Onboarding AP + web form |
| `bilalcast/logger.py` | Logging — print (debug) or ntfy push notifications |
| `bilalcast/mdns_client/` | mDNS client for Chromecast discovery |
| `bilalcast/www/` | HTML pages for the captive portal |

## Configuration

Saved to `config.json` on the device after onboarding:

```json
{
  "ssid": "your-wifi-name",
  "password": "your-wifi-password",
  "cast_device_name": "Living Room"
}
```

Location is auto-detected at runtime via IP geolocation — no manual address entry needed.
