import ujson as json  # pyright: ignore[reportMissingImports]
import os
import machine  # pyright: ignore[reportMissingImports]

_led = machine.Pin("LED", machine.Pin.OUT)
_led_timer = machine.Timer()


def _led_slow_blink():
    """Slow blink (500 ms) — waiting / connecting."""
    _led_timer.init(period=500, mode=machine.Timer.PERIODIC, callback=lambda t: _led.toggle())


def _led_fast_blink():
    """Fast blink (150 ms) — active download in progress."""
    _led_timer.init(period=150, mode=machine.Timer.PERIODIC, callback=lambda t: _led.toggle())


def _led_solid():
    """Solid on — success."""
    _led_timer.deinit()
    _led.value(1)


def _led_error():
    """Rapid flash (80 ms) — failure."""
    _led_timer.init(period=80, mode=machine.Timer.PERIODIC, callback=lambda t: _led.toggle())


def _ntfy(msg, title="Bilal Cast"):
    try:
        import urequests  # pyright: ignore[reportMissingImports]
        r = urequests.post(
            "https://ntfy.sh/",
            data=json.dumps({"topic": "bilalpico", "title": title, "message": msg}),
            headers={"Content-Type": "application/json"},
        )
        r.close()
    except Exception:
        pass


def _cfg():
    try:
        with open("config.json") as f:
            c = json.load(f)
        if c.get("ssid") and c.get("password") and c.get("cast_device_name"):
            return c
    except Exception:
        pass
    return None


def _has_app():
    try:
        os.stat("bilalcast/main.py")
        return True
    except Exception:
        return False


_c = _cfg()

if _c is None:
    import asyncio  # pyright: ignore[reportMissingImports]
    from bilalcast.captive_portal import captive_portal
    asyncio.run(captive_portal())

elif _has_app():
    try:
        import bilalcast.main
    except Exception as e:
        import sys
        import utime as time  # pyright: ignore[reportMissingImports]
        _led_error()
        sys.print_exception(e)
        time.sleep(5)
        machine.reset()

else:
    # Config exists but app not yet downloaded — first boot after captive portal
    import network  # pyright: ignore[reportMissingImports]
    import utime as time  # pyright: ignore[reportMissingImports]

    _title = _c.get("cast_device_name", "Bilal Cast")

    print("OTA boot: connecting to WiFi...")
    _led_slow_blink()  # slow blink = WiFi connecting

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    try:
        network.hostname(_c.get("hostname", "bilalcast"))
    except Exception:
        pass
    wlan.connect(_c["ssid"], _c["password"])
    for _ in range(30):
        if wlan.isconnected():
            break
        time.sleep(1)

    if not wlan.isconnected():
        print("OTA boot: WiFi failed, resetting...")
        _led_error()
        _ntfy("OTA boot: WiFi failed — will retry on next boot", _title)
        time.sleep(2)
        machine.reset()

    local_ip = wlan.ifconfig()[0]
    print("OTA boot: WiFi connected (" + local_ip + "), starting download...")
    _ntfy("OTA boot: WiFi connected (" + local_ip + "), downloading app...", _title)
    _led_fast_blink()  # fast blink = downloading

    from bilalcast.ota import download_all
    ok = download_all()

    if ok:
        print("OTA complete, rebooting...")
        _ntfy("OTA complete — rebooting", _title)
        _led_solid()
    else:
        print("OTA failed, will retry on next boot...")
        _ntfy("OTA failed — some files could not be downloaded, will retry on next boot", _title)
        _led_error()

    time.sleep(2)
    machine.reset()
