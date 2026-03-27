import ujson as json  # pyright: ignore[reportMissingImports]
import os


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
        import machine  # pyright: ignore[reportMissingImports]
        import utime as time  # pyright: ignore[reportMissingImports]
        sys.print_exception(e)
        time.sleep(5)
        machine.reset()

else:
    # Config exists but app not yet downloaded — first boot after captive portal
    import network  # pyright: ignore[reportMissingImports]
    import utime as time  # pyright: ignore[reportMissingImports]
    import machine  # pyright: ignore[reportMissingImports]
    from bilalcast import logger
    logger.configure(True, None)
    from bilalcast.logger import log

    log("First boot: connecting for OTA download...")
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
        log("WiFi failed, resetting...")
        time.sleep(2)
        machine.reset()

    from bilalcast.ota import download_all
    ok = download_all()
    log("OTA complete, rebooting..." if ok else "OTA failed, will retry on next boot...")
    time.sleep(2)
    machine.reset()
