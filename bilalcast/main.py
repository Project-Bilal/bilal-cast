import machine
import network
import utime as time
import ujson as json
import ntptime
import os

import bilalcast.logger as logger
from bilalcast.logger import log, send_ntfy
from bilalcast.prayer import get_location, get_next_prayer, pre_athan_time, seconds_until, ATHANS, PRE_ATHAN
from bilalcast.discovery import resolve_cast_device, cast_url

# USER CONFIGURED DATA
DEBUG = False  # True = print to console, False = send via ntfy

ACTIVATION_URL = "https://translate.google.com/translate_tts?client=tw-ob&tl=en&q=Salaam+Alaykum,+This+is+Belaal+Cast.+You+will+hear+the+adthaan+on+this+device."

CONFIG_FILE = "config.json"

# Runtime config — populated from CONFIG_FILE at boot
SSID = None
PASSWORD = None
CAST_DEVICE_NAME = None

_led = machine.Pin("LED", machine.Pin.OUT)
_led_timer = None


def led_blink():
    """Fast blink via hardware timer — works in both sync and async contexts."""
    global _led_timer
    _led_timer = machine.Timer(-1)
    _led_timer.init(freq=4, mode=machine.Timer.PERIODIC, callback=lambda t: _led.toggle())


def led_solid():
    """Stop blinking and turn LED solidly on."""
    global _led_timer
    if _led_timer:
        _led_timer.deinit()
        _led_timer = None
    _led.on()


def check_factory_reset():
    """Hold BOOTSEL for 10 seconds at boot to wipe config and open captive portal."""
    import rp2

    if not rp2.bootsel_button():
        return False
    log("BOOTSEL held — keep holding 10s to reset, release to cancel...")
    for _ in range(100):  # 100 × 100ms = 10 seconds
        time.sleep_ms(100)
        if not rp2.bootsel_button():
            log("BOOTSEL released, continuing normal boot.")
            return False
    led_solid()
    time.sleep_ms(500)
    led_blink()
    return True


def load_config():
    try:
        with open(CONFIG_FILE) as f:
            d = json.load(f)
        if d.get("ssid") and d.get("password") and d.get("cast_device_name"):
            return d
    except Exception:
        pass
    return None


_NTP_HOSTS = [
    "pool.ntp.org",
    "time.google.com",
    "time.cloudflare.com",
    "time.apple.com",
]


def connect_to_wifi_with_retries(ssid, password, *, max_retries=100, timeout_seconds=30, retry_delay_s=2):
    statuses = {
        network.STAT_IDLE: "idle",
        network.STAT_CONNECTING: "connecting",
        network.STAT_WRONG_PASSWORD: "wrong password",
        network.STAT_NO_AP_FOUND: "access point not found",
        network.STAT_CONNECT_FAIL: "connection failed",
        network.STAT_GOT_IP: "got ip address",
    }

    wlan = network.WLAN(network.STA_IF)

    for attempt in range(1, max_retries + 1):
        try:
            log("Wi-Fi connect attempt {}/{}...".format(attempt, max_retries))

            wlan.active(False)
            time.sleep(1)
            wlan.active(True)

            wlan.connect(ssid, password)

            start = time.time()
            last_status = None

            while not wlan.isconnected():
                status = wlan.status()

                if status != last_status:
                    log("  status: " + statuses.get(status, str(status)))
                    last_status = status

                if time.time() - start >= timeout_seconds:
                    log("  timed out after {}s".format(timeout_seconds))
                    break

                time.sleep(1)

            if wlan.isconnected() and wlan.status() == network.STAT_GOT_IP:
                ip = wlan.ifconfig()[0]
                log("connected to wifi: " + ip)
                time.sleep(2)
                return ip

        except Exception as e:
            log("Wi-Fi error on attempt {}/{}: {}".format(attempt, max_retries, e))

        time.sleep(retry_delay_s)

    log("Wi-Fi failed after {} attempts; resetting.".format(max_retries))
    time.sleep(1)
    machine.reset()


def set_rtc(max_attempts=20):
    for host_idx in range(max_attempts):
        ntptime.host = _NTP_HOSTS[host_idx % len(_NTP_HOSTS)]
        try:
            ntptime.settime()
        except Exception as e:
            log("NTP sync failed ({}), trying next host: {}".format(ntptime.host, str(e)))
            time.sleep(2)
            continue

        year = time.localtime()[0]
        if year >= 2024:
            log("RTC set via {} (UTC): {}".format(ntptime.host, str(time.localtime())))
            return

        log("RTC year implausible ({}), trying next host...".format(year))
        time.sleep(2)

    log("NTP failed after {} attempts; resetting.".format(max_attempts))
    time.sleep(1)
    machine.reset()


def ensure_wifi():
    wlan = network.WLAN(network.STA_IF)
    if not wlan.isconnected():
        log("WiFi dropped, reconnecting...")
        connect_to_wifi_with_retries(SSID, PASSWORD)


def main():
    global SSID, PASSWORD, CAST_DEVICE_NAME

    logger.configure(True, None)  # always print before WiFi is up
    led_blink()
    log("athan starting")

    if check_factory_reset():
        log("Factory reset confirmed, clearing config...")
        for f in (CONFIG_FILE, "cast_device.json"):
            try:
                os.remove(f)
            except Exception:
                pass
        import asyncio
        from bilalcast.captive_portal import captive_portal as _portal

        asyncio.run(_portal())
        return  # never reached — portal resets the device after save

    config = load_config()
    if not config:
        log("No config found, starting captive portal...")
        import asyncio
        from bilalcast.captive_portal import captive_portal as _portal

        asyncio.run(_portal())
        return  # never reached — portal resets the device after save

    SSID = config["ssid"]
    PASSWORD = config["password"]
    CAST_DEVICE_NAME = config["cast_device_name"]

    try:
        os.stat("cast_device.json")
        first_connection = False
    except OSError:
        first_connection = True

    local_ip = connect_to_wifi_with_retries(SSID, PASSWORD)
    logger.configure(DEBUG, CAST_DEVICE_NAME)  # switch to configured mode now that WiFi is up
    set_rtc()

    cast_host, cast_port = resolve_cast_device(local_ip, CAST_DEVICE_NAME)
    log("cast device: {}:{}".format(cast_host, cast_port))
    led_solid()

    if first_connection:
        log("First connection — playing activation message")
        cast_url(ACTIVATION_URL, cast_host, cast_port)

    t = time.localtime()
    send_ntfy(
        "online: {:04d}-{:02d}-{:02d} {:02d}:{:02d} UTC".format(t[0], t[1], t[2], t[3], t[4]),
        priority=2,
        tags=["white_check_mark"],
    )
    lat, lon = get_location()
    prayer, prayer_time = get_next_prayer(lat, lon)
    pre_time = pre_athan_time(prayer_time)

    secs_to_pre = seconds_until(pre_time)
    secs_to_prayer = seconds_until(prayer_time)

    if secs_to_pre < secs_to_prayer:
        secs, target, audio_file, label = secs_to_pre, pre_time, PRE_ATHAN, f"pre_{prayer}, {pre_time}"
    else:
        secs, target, audio_file, label = secs_to_prayer, prayer_time, ATHANS[prayer], f"{prayer}, {prayer_time}"

    time.sleep(max(0, secs - 30))

    # Poll every second until HH:MM matches; 60s safety timeout covers overshoot
    deadline = time.time() + 60
    while time.time() < deadline:
        now = time.localtime()
        if "{:02d}:{:02d}".format(now[3], now[4]) == target:
            break
        time.sleep(1)

    ensure_wifi()
    ok, cast_error = cast_url(audio_file, cast_host, cast_port)
    if ok:
        send_ntfy(label, priority=3, tags=["bell"])
    else:
        send_ntfy("cast failed: {} — {}".format(label, cast_error), priority=5, tags=["warning"])

    time.sleep(200)
    machine.reset()


try:
    main()
except KeyboardInterrupt:
    log("stopped")
except Exception as e:
    log("fatal error: " + str(e))
    time.sleep(1)
    machine.reset()
