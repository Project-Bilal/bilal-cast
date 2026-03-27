import asyncio
import machine
import network
import utime as time
import ujson as json
import ntptime
import os

import bilalcast.logger as logger
from bilalcast.logger import log, warn, error, send_ntfy
from bilalcast.prayer import (
    get_location,
    get_all_prayers,
    get_all_prayers_by_address,
    try_prayers_by_address,
    geocode_address,
    pre_athan_time,
    seconds_until,
    ATHANS,
    ATHANS_ORDER,
    PRE_ATHAN,
)
from bilalcast.discovery import resolve_cast_device, cast_url, start_mdns_responder, list_cast_devices
from bilalcast.status import start_status_server

# USER CONFIGURED DATA
DEBUG = False  # True = print to console, False = send via ntfy

ACTIVATION_URL = "https://translate.google.com/translate_tts?client=tw-ob&tl=en&q=Salaam+Alaykum,+This+is+Belaal+Cast.+You+will+hear+the+adthaan+on+this+device."

CONFIG_FILE = "config.json"
CAST_STATE_FILE = "cast_state.json"

# Runtime config — populated from CONFIG_FILE at boot
SSID = None
PASSWORD = None
CAST_DEVICE_NAME = None
DEVICE_HOSTNAME = "bilalcast"  # not configurable
PRE_ATHAN_MINS = 10
CALC_METHOD = 2
LAT_ADJ_METHOD = 1
MIDNIGHT_MODE = 0
SCHOOL = 0
_cfg_lat = None
_cfg_lon = None
_cfg_address = None
_tz_string = ""

_led = machine.Pin("LED", machine.Pin.OUT)
_led_timer = None

# Shared state between HTTP handler and prayer scheduler
state = {
    "prayer_times": {},
    "next_prayer": None,
    "next_prayer_time": None,
    "cast_host": None,
    "cast_port": None,
    "last_cast_ok": None,
    "last_cast_label": None,
    "lat": None,
    "lon": None,
    "address": None,
    "lat_adj": 1,
    "midnight": 0,
    "school": 0,
    "local_ip": None,
    "boot_epoch": 0,
    "device_name": None,
    "hostname": "bilalcast",
    "cast_devices": [],
}


def led_blink():
    """Fast blink via hardware timer — works in both sync and async contexts."""
    global _led_timer
    _led_timer = machine.Timer(-1)
    _led_timer.init(
        freq=4, mode=machine.Timer.PERIODIC, callback=lambda t: _led.toggle()
    )


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


def connect_to_wifi_with_retries(
    ssid, password, *, hostname=None, max_retries=10, timeout_seconds=30, retry_delay_s=2
):
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
            if hostname:
                try:
                    network.hostname(hostname)
                except Exception:
                    pass
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
            log(
                "NTP sync failed ({}), trying next host: {}".format(
                    ntptime.host, str(e)
                )
            )
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


def adjust_rtc(utc_offset_secs):
    t = time.localtime(time.time() + utc_offset_secs)
    machine.RTC().datetime((t[0], t[1], t[2], t[6], t[3], t[4], t[5], 0))
    log("RTC adjusted to local time (UTC offset {}s)".format(utc_offset_secs))


def ensure_wifi():
    wlan = network.WLAN(network.STA_IF)
    if not wlan.isconnected():
        warn("WiFi dropped, reconnecting...")
        connect_to_wifi_with_retries(SSID, PASSWORD)


def _time_passed(hhmm):
    """Return True if HH:MM has already passed today (local time)."""
    now = time.localtime()
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m) <= now[3] * 60 + now[4]


def _get_prayer_times(lat, lon, method, tz):
    """Fetch prayer times with address fallback chain.

    1. lat/lon available → lat/lon endpoint (retry forever)
    2. address config, no lat/lon → address endpoint (retry forever)
    3. fallback path: never reached if caller ensures lat/lon or address is set
    """
    if lat is not None and lon is not None:
        return get_all_prayers(lat, lon, method, tz, LAT_ADJ_METHOD, MIDNIGHT_MODE, SCHOOL)
    if _cfg_address:
        return get_all_prayers_by_address(_cfg_address, method, tz, LAT_ADJ_METHOD, MIDNIGHT_MODE, SCHOOL)
    return {}


async def _discovery_loop():
    """Background task: retry cast device discovery every 30s until found."""
    while True:
        await asyncio.sleep(30)
        if state["cast_host"] is not None:
            return
        log("Re-attempting cast device discovery...")
        host, port = await resolve_cast_device(state["local_ip"], CAST_DEVICE_NAME)
        if host:
            state["cast_host"] = host
            state["cast_port"] = port
            log("Cast device found: {}:{}".format(host, port))
            return


def _save_cast_state(ok, label):
    state["last_cast_ok"] = ok
    state["last_cast_label"] = label
    try:
        with open(CAST_STATE_FILE, "w") as f:
            json.dump({"ok": ok, "label": label}, f)
    except Exception as e:
        error("cast state save failed: " + str(e))


async def do_cast(url, label):
    ensure_wifi()
    if state["cast_host"] is None:
        log("Cast host unknown, attempting re-discovery...")
        host, port = await resolve_cast_device(state["local_ip"], CAST_DEVICE_NAME)
        if host:
            state["cast_host"] = host
            state["cast_port"] = port
        else:
            warn("cast device not found: {}".format(CAST_DEVICE_NAME))
            send_ntfy(
                "cast device not found: {}".format(CAST_DEVICE_NAME),
                priority=4,
                tags=["warning"],
            )
            _save_cast_state(False, label)
            return
    ok, cast_error = cast_url(url, state["cast_host"], state["cast_port"])
    _save_cast_state(ok, label)
    if ok:
        send_ntfy(label, priority=3, tags=["bell"])
    else:
        error("cast failed: {} — {}".format(label, cast_error))
        send_ntfy(
            "cast failed: {} — {}".format(label, cast_error),
            priority=5,
            tags=["warning"],
        )


async def run_schedule():
    while True:
        times = state["prayer_times"]
        for prayer in ATHANS_ORDER:
            t = times.get(prayer)
            if not t or _time_passed(t):
                continue

            state["next_prayer"] = prayer
            state["next_prayer_time"] = t

            if PRE_ATHAN_MINS > 0:
                pre_t = pre_athan_time(t, PRE_ATHAN_MINS)
                if not _time_passed(pre_t):
                    secs_to_pre = seconds_until(pre_t)
                    if secs_to_pre > 0:
                        await asyncio.sleep(secs_to_pre)
                    asyncio.create_task(
                        do_cast(PRE_ATHAN, "pre_{}, {}".format(prayer, pre_t))
                    )

            secs_to_prayer = seconds_until(t)
            if secs_to_prayer > 0:
                await asyncio.sleep(secs_to_prayer)

            await do_cast(ATHANS[prayer], "{}, {}".format(prayer, t))
            await asyncio.sleep(200)

        # All today's prayers done — wait for local midnight, re-sync, re-fetch
        state["next_prayer"] = None
        state["next_prayer_time"] = None
        await asyncio.sleep(max(60, seconds_until("00:01")))
        set_rtc()
        global _tz_string
        geo_lat, geo_lon, offset, tz_string = get_location()
        _tz_string = tz_string
        if offset:
            adjust_rtc(offset)
        lat = float(_cfg_lat) if _cfg_lat else (None if _cfg_address else geo_lat)
        lon = float(_cfg_lon) if _cfg_lon else (None if _cfg_address else geo_lon)
        state["lat"] = lat
        state["lon"] = lon
        state["prayer_times"] = _get_prayer_times(lat, lon, CALC_METHOD, _tz_string)
        log("Prayer times refreshed for new day")


async def main():
    global SSID, PASSWORD, CAST_DEVICE_NAME, PRE_ATHAN_MINS, CALC_METHOD, LAT_ADJ_METHOD, MIDNIGHT_MODE, SCHOOL, _cfg_lat, _cfg_lon, _cfg_address, _tz_string

    logger.configure(True, None)  # always print before WiFi is up
    led_blink()
    log("athan starting")

    if check_factory_reset():
        log("Factory reset confirmed, clearing config...")
        for f in (CONFIG_FILE, "cast_device.json", CAST_STATE_FILE):
            try:
                os.remove(f)
            except Exception:
                pass
        from bilalcast.captive_portal import captive_portal as _portal

        await _portal()
        return  # never reached — portal resets the device after save

    config = load_config()
    if not config:
        log("No config found, starting captive portal...")
        from bilalcast.captive_portal import captive_portal as _portal

        await _portal()
        return  # never reached — portal resets the device after save

    SSID = config["ssid"]
    PASSWORD = config["password"]
    CAST_DEVICE_NAME = config["cast_device_name"]
    PRE_ATHAN_MINS = int(config.get("pre_athan_mins", 10))
    CALC_METHOD = int(config.get("method", 2))
    LAT_ADJ_METHOD = int(config.get("lat_adj", 1))
    MIDNIGHT_MODE = int(config.get("midnight", 0))
    SCHOOL = int(config.get("school", 0))
    _cfg_lat = config.get("lat")
    _cfg_lon = config.get("lon")
    _cfg_address = config.get("address")

    local_ip = connect_to_wifi_with_retries(SSID, PASSWORD, hostname=DEVICE_HOSTNAME)
    logger.configure(DEBUG, CAST_DEVICE_NAME)

    # Populate state and start HTTP server immediately after WiFi so the
    # status page is reachable as soon as possible. Remaining boot steps
    # (OTA, NTP, location, prayer times) fill in the state afterwards.
    state["local_ip"] = local_ip
    state["device_name"] = CAST_DEVICE_NAME
    state["hostname"] = DEVICE_HOSTNAME
    state["boot_epoch"] = time.time()
    try:
        with open(CAST_STATE_FILE) as f:
            cs = json.load(f)
        state["last_cast_ok"] = cs.get("ok")
        state["last_cast_label"] = cs.get("label")
    except Exception:
        pass

    start_status_server(state, PRE_ATHAN_MINS, CALC_METHOD, CONFIG_FILE, ACTIVATION_URL, do_cast, local_ip)
    start_mdns_responder(local_ip, local_ip)

    try:
        from bilalcast.ota import check_and_update
        if check_and_update():
            log("OTA update applied, rebooting...")
            time.sleep(1)
            machine.reset()
    except Exception as e:
        warn("OTA check failed: " + str(e))

    geo_lat, geo_lon, utc_offset, tz_string = get_location()
    _tz_string = tz_string
    set_rtc()
    if utc_offset:
        adjust_rtc(utc_offset)

    cast_host, cast_port = await resolve_cast_device(local_ip, CAST_DEVICE_NAME)
    if cast_host:
        log("cast device found: {}:{}".format(cast_host, cast_port))
    else:
        warn("cast device not found at boot, background retry active")
        asyncio.create_task(_discovery_loop())

    state["cast_host"] = cast_host
    state["cast_port"] = cast_port

    t = time.localtime()
    send_ntfy(
        "online: {:04d}-{:02d}-{:02d} {:02d}:{:02d}".format(
            t[0], t[1], t[2], t[3], t[4]
        ),
        priority=2,
        tags=["white_check_mark"],
    )

    # Resolve lat/lon: explicit config > Nominatim geocoding > IP geolocation
    if _cfg_lat and _cfg_lon:
        lat = float(_cfg_lat)
        lon = float(_cfg_lon)
        log("using configured location: {}, {}".format(lat, lon))
    elif _cfg_address and not (_cfg_lat and _cfg_lon):
        # Try to geocode the address for precise coordinates
        gc_lat, gc_lon = geocode_address(_cfg_address)
        if gc_lat is not None:
            lat = gc_lat
            lon = gc_lon
            _cfg_lat = str(gc_lat)
            _cfg_lon = str(gc_lon)
            log("geocoded to: {}, {}".format(lat, lon))
        else:
            # Nominatim failed — will use address endpoint for prayer times
            lat = None
            lon = None
            log("geocoding failed, will use address endpoint")
    else:
        lat = geo_lat
        lon = geo_lon

    state["lat"] = lat
    state["lon"] = lon
    state["address"] = _cfg_address or ""
    state["lat_adj"] = LAT_ADJ_METHOD
    state["midnight"] = MIDNIGHT_MODE
    state["school"] = SCHOOL

    # Fetch prayer times: try address endpoint first if no lat/lon, then geo fallback
    if lat is None and lon is None and _cfg_address:
        times = try_prayers_by_address(_cfg_address, CALC_METHOD, _tz_string, LAT_ADJ_METHOD, MIDNIGHT_MODE, SCHOOL)
        if times is None:
            log("address prayer times failed, falling back to IP geolocation")
            lat = geo_lat
            lon = geo_lon
            state["lat"] = lat
            state["lon"] = lon
            state["prayer_times"] = get_all_prayers(lat, lon, CALC_METHOD, _tz_string)
        else:
            state["prayer_times"] = times
    else:
        state["prayer_times"] = _get_prayer_times(lat, lon, CALC_METHOD, _tz_string)

    led_solid()
    log("ready — visit http://bilalcast.local")

    await run_schedule()


try:
    asyncio.run(main())
except KeyboardInterrupt:
    log("stopped")
except Exception as e:
    log("fatal error: " + str(e))
    time.sleep(1)
    machine.reset()
