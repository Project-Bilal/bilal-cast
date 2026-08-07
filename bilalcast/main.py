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
    try_location,
    get_all_prayers,
    get_all_prayers_by_address,
    try_prayers,
    try_prayers_by_address,
    geocode_address,
    pre_athan_time,
    seconds_until,
    athan_url,
    build_athans,
    DEFAULT_ATHAN,
    DEFAULT_FAJR,
    DEFAULT_PRE_ATHAN,
    ATHANS_ORDER,
)
from bilalcast.discovery import resolve_cast_device, cast_url, start_mdns_responder
from bilalcast.status import start_status_server

# USER CONFIGURED DATA
DEBUG = False  # True = print to console, False = send via ntfy

ACTIVATION_URL = "https://translate.google.com/translate_tts?client=tw-ob&tl=en&q=Salaam+Alaykum,+This+is+Belaal+Cast.+You+will+hear+the+adthaan+on+this+device."

CONFIG_FILE = "config.json"
CAST_STATE_FILE = "cast_state.json"
PRAYER_CACHE_FILE = "prayer_times.json"    # last good prayer times (offline backup)
LOCATION_CACHE_FILE = "location.json"      # last good lat/lon/offset/tz (offline backup)
WIFI_FAIL_FILE = "wifi_fail.txt"           # consecutive failed-boot counter
_WIFI_FAIL_THRESHOLD = 3                    # open onboarding after this many failed boots

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
PRAYER_VOLUMES = {"Fajr": 0.5, "Dhuhr": 0.5, "Asr": 0.5, "Maghrib": 0.5, "Isha": 0.5}
ATHAN_SOUND = DEFAULT_ATHAN
FAJR_SOUND = DEFAULT_FAJR
PRE_ATHAN_SOUND = DEFAULT_PRE_ATHAN
ATHANS = build_athans()                  # {prayer: url}, rebuilt from config in main()
PRE_ATHAN = athan_url(DEFAULT_PRE_ATHAN)  # reminder URL, rebuilt from config in main()
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
    "athan": DEFAULT_ATHAN,
    "fajr_athan": DEFAULT_FAJR,
    "pre_athan": DEFAULT_PRE_ATHAN,
    "cast_devices": [],
    "local_ip": None,
    "boot_epoch": 0,
    "device_name": None,
    "hostname": "bilalcast",
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
        # Only Wi-Fi is required to complete onboarding; the cast device is
        # chosen later on the Settings page. Password may be blank (open network).
        if d.get("ssid"):
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

                # Fail this attempt fast on a terminal status (wrong password,
                # AP not found) instead of waiting out the full timeout — keeps
                # the reboot/onboarding fallback from taking many minutes.
                if status in (
                    network.STAT_WRONG_PASSWORD,
                    network.STAT_NO_AP_FOUND,
                    network.STAT_CONNECT_FAIL,
                ):
                    log("  connect failed: " + statuses.get(status, str(status)))
                    break

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

    # Signal failure to the caller instead of resetting here, so boot can fall
    # back to onboarding after repeated failures rather than reboot-looping.
    log("Wi-Fi failed after {} attempts.".format(max_retries))
    return None


async def set_rtc(max_attempts=20):
    # Async so the retry backoff yields to the event loop (status server,
    # mDNS responder) instead of freezing it when NTP is slow/unreachable.
    try:
        ntptime.timeout = 3  # default is 1s, which is tight over WiFi
    except Exception:
        pass
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
            await asyncio.sleep(2)
            continue

        year = time.localtime()[0]
        if year >= 2024:
            log("RTC set via {} (UTC): {}".format(ntptime.host, str(time.localtime())))
            return

        log("RTC year implausible ({}), trying next host...".format(year))
        await asyncio.sleep(2)

    log("NTP failed after {} attempts; trying HTTP Date fallback...".format(max_attempts))
    if _set_rtc_via_http():
        return
    log("HTTP time fallback failed too; resetting.")
    time.sleep(1)
    machine.reset()


def adjust_rtc(utc_offset_secs):
    t = time.localtime(time.time() + utc_offset_secs)
    machine.RTC().datetime((t[0], t[1], t[2], t[6], t[3], t[4], t[5], 0))
    log("RTC adjusted to local time (UTC offset {}s)".format(utc_offset_secs))


def _wifi_fail_count():
    try:
        with open(WIFI_FAIL_FILE) as f:
            return int(f.read().strip() or "0")
    except Exception:
        return 0


def _set_wifi_fail_count(n):
    try:
        if n <= 0:
            os.remove(WIFI_FAIL_FILE)
        else:
            with open(WIFI_FAIL_FILE, "w") as f:
                f.write(str(n))
                f.flush()
            os.sync()
    except Exception:
        pass


_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def _parse_http_date(line):
    """Parse an HTTP 'Date:' header line into (year, mon, day, hh, mm, ss) UTC."""
    try:
        # "Date: Wed, 21 Oct 2015 07:28:00 GMT" -> "Wed, 21 Oct 2015 07:28:00 GMT"
        v = line.split(":", 1)[1].strip()
        p = v.split(" ")  # ["Wed,","21","Oct","2015","07:28:00","GMT"]
        day = int(p[1])
        mon = _MONTHS[p[2]]
        year = int(p[3])
        hh, mm, ss = [int(x) for x in p[4].split(":")]
        return year, mon, day, hh, mm, ss
    except Exception:
        return None


def _set_rtc_via_http():
    """Fallback clock: set the RTC (UTC) from an HTTP Date header. Works when a
    network blocks NTP (UDP/123) but allows HTTP. Returns True on success."""
    import socket

    for host in ("www.google.com", "cloudflare.com", "example.com"):
        s = None
        buf = b""
        try:
            ai = socket.getaddrinfo(host, 80)[0][-1]
            s = socket.socket()
            s.settimeout(5)
            s.connect(ai)
            s.send(b"HEAD / HTTP/1.0\r\nHost: " + host.encode() + b"\r\nConnection: close\r\n\r\n")
            while len(buf) < 2048:
                chunk = s.recv(512)
                if not chunk:
                    break
                buf += chunk
                if b"\r\n\r\n" in buf:
                    break
        except Exception as e:
            log("HTTP time fetch failed ({}): {}".format(host, e))
        finally:
            if s:
                try:
                    s.close()
                except Exception:
                    pass
        for line in buf.split(b"\r\n"):
            if line[:5].lower() == b"date:":
                parsed = _parse_http_date(line.decode())
                if parsed and parsed[0] >= 2024:
                    y, mo, d, hh, mm, ss = parsed
                    epoch = time.mktime((y, mo, d, hh, mm, ss, 0, 0))
                    tm = time.gmtime(epoch)
                    machine.RTC().datetime((tm[0], tm[1], tm[2], tm[6], tm[3], tm[4], tm[5], 0))
                    log("RTC set via HTTP Date ({}): {}".format(host, str(time.localtime())))
                    return True
    return False


def ensure_wifi():
    wlan = network.WLAN(network.STA_IF)
    if not wlan.isconnected():
        warn("WiFi dropped, reconnecting...")
        if not connect_to_wifi_with_retries(SSID, PASSWORD):
            # Mid-run reconnect failed — reboot so boot-time logic re-runs (and
            # falls back to onboarding if the failure is persistent).
            warn("WiFi reconnect failed; rebooting.")
            time.sleep(1)
            machine.reset()


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


def _load_json_file(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _save_json_file(path, obj):
    try:
        with open(path, "w") as f:
            json.dump(obj, f)
            f.flush()
        os.sync()  # commit to flash so a reboot after a prayer keeps the backup
    except Exception as e:
        warn("save {} failed: {}".format(path, str(e)))


def _today_str():
    t = time.localtime()
    return "{:04d}-{:02d}-{:02d}".format(t[0], t[1], t[2])


def _save_prayer_cache(times):
    _save_json_file(PRAYER_CACHE_FILE, {"date": _today_str(), "times": times})


def _load_prayer_cache():
    """Return (times, date_str) from the last good fetch, or (None, None)."""
    d = _load_json_file(PRAYER_CACHE_FILE)
    if d and d.get("times"):
        return d["times"], d.get("date")
    return None, None


def _resolve_location(attempts=5):
    """IP geolocation with a persisted fallback so a transient ip-api.com outage
    can't hang the boot. Returns (lat, lon, utc_offset, tz)."""
    for _i in range(attempts):
        r = try_location()
        if r:
            _save_json_file(
                LOCATION_CACHE_FILE,
                {"lat": r[0], "lon": r[1], "offset": r[2], "tz": r[3]},
            )
            log("location: {}, {} (UTC offset {}s, tz {})".format(r[0], r[1], r[2], r[3]))
            return r
        time.sleep(2)
    cached = _load_json_file(LOCATION_CACHE_FILE)
    if cached and cached.get("tz") is not None:
        warn("IP geolocation unavailable — using cached location/timezone")
        return cached.get("lat"), cached.get("lon"), cached.get("offset", 0), cached.get("tz", "")
    # First boot during an outage and no cache: last resort, block until it responds.
    warn("IP geolocation unavailable and no cache — retrying until it responds")
    return get_location()


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


def _persist_cast_endpoint(host, port):
    """Promote a working cast endpoint to the durable config pin.

    Called after a successful cast: if the endpoint we just cast to differs from
    what's pinned in config.json (e.g. it was rediscovered after a move, or the
    device was only ever in the mDNS cache), write it so future boots use it
    directly. No-op when it already matches, so it writes at most once per change.
    """
    if not host or not port:
        return
    try:
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        if cfg.get("cast_device_host") == host and str(cfg.get("cast_device_port")) == str(port):
            return
        cfg["cast_device_host"] = host
        cfg["cast_device_port"] = str(port)
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f)
            f.flush()
        os.sync()
        log("pinned working cast endpoint to config: {}:{}".format(host, port))
    except Exception as e:
        warn("cast endpoint persist failed: " + str(e))


async def do_cast(url, label, volume=0.5):
    ensure_wifi()
    if state["cast_host"] is None:
        if not CAST_DEVICE_NAME:
            msg = "no cast device configured — pick one at http://{}.local/settings".format(
                state.get("hostname") or "bilalcast"
            )
            warn(msg)
            send_ntfy(msg, priority=4, tags=["warning"])
            _save_cast_state(False, label)
            return False
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
            return False
    ok, cast_error = cast_url(url, state["cast_host"], state["cast_port"], volume=volume)
    _save_cast_state(ok, label)
    if ok:
        _persist_cast_endpoint(state["cast_host"], state["cast_port"])
        send_ntfy(label, priority=3, tags=["bell"])
    else:
        error("cast failed: {} — {}".format(label, cast_error))
        send_ntfy(
            "cast failed: {} — {}".format(label, cast_error),
            priority=5,
            tags=["warning"],
        )
    return ok


async def run_schedule():
    # Handles the next not-yet-passed prayer, then reboots. Rebooting after
    # every prayer means each prayer is scheduled by a freshly-booted device
    # that re-syncs the clock, re-fetches prayer times, and runs the OTA check —
    # so devices stay updated (the whole reason for the reset).
    times = state["prayer_times"]
    for prayer in ATHANS_ORDER:
        t = times.get(prayer)
        if not t or _time_passed(t):
            continue

        vol = PRAYER_VOLUMES.get(prayer, 0.5)
        if vol <= 0:
            continue  # volume "Off" for this prayer — skip pre-athan and athan

        state["next_prayer"] = prayer
        state["next_prayer_time"] = t

        if PRE_ATHAN_MINS > 0:
            pre_t = pre_athan_time(t, PRE_ATHAN_MINS)
            if not _time_passed(pre_t):
                secs_to_pre = seconds_until(pre_t)
                if secs_to_pre > 0:
                    await asyncio.sleep(secs_to_pre)
                # Fire-and-forget so it doesn't delay the athan sleep; the athan
                # reboot below comes minutes later, after this has finished.
                asyncio.create_task(
                    do_cast(PRE_ATHAN, "pre_{}, {}".format(prayer, pre_t), vol)
                )

        secs_to_prayer = seconds_until(t)
        if secs_to_prayer > 0:
            await asyncio.sleep(secs_to_prayer)

        # A network/reachability blip at prayer time shouldn't drop the athan, so
        # keep retrying for up to ~3 minutes past the trigger (a couple minutes
        # late beats a missed prayer). Strategy:
        #   - Trust the known endpoint FIRST — most failures are transient blips
        #     that clear by simply retrying the same host.
        #   - After a few straight failures the endpoint may have genuinely moved
        #     (a group's dynamic port can change), so periodically try one mDNS
        #     rediscovery and adopt whatever it finds. Only adopt a real result —
        #     a flaky empty scan must never blank the working host.
        #   - On success, do_cast() persists the endpoint to config, so a moved
        #     port becomes the new durable pin automatically.
        cast_started = time.time()
        ok = await do_cast(ATHANS[prayer], "{}, {}".format(prayer, t), vol)
        fails = 0
        while not ok and (time.time() - cast_started) < 180:
            await asyncio.sleep(15)
            fails += 1
            if fails == 3 or fails == 6:
                nh, np = await resolve_cast_device(state["local_ip"], CAST_DEVICE_NAME)
                if nh and (nh, np) != (state["cast_host"], state["cast_port"]):
                    log("cast endpoint moved: {}:{} -> {}:{}".format(
                        state["cast_host"], state["cast_port"], nh, np))
                    state["cast_host"], state["cast_port"] = nh, np
            ok = await do_cast(ATHANS[prayer], "{}, {}".format(prayer, t), vol)
        if not ok:
            # Not even rediscovery could reach it in 3 minutes — drop the mDNS
            # cache so the reboot below starts from a clean discovery. A config
            # pin is re-seeded on boot (the user's authoritative choice) and left
            # untouched.
            try:
                os.remove("cast_device.json")
                os.sync()
            except Exception:
                pass

        # Reboot for OTA + a fresh reschedule of the next prayer. The athan is
        # already playing on the speaker (LOAD confirmed), so this does not cut
        # it off. _time_passed() uses <=, so the just-fired prayer is treated as
        # passed on the next boot and won't double-fire.
        await asyncio.sleep(5)
        machine.reset()

    # No prayers remain today — wait until just after midnight, then reboot to
    # rebuild the new day (fresh clock/location/prayer-times) and OTA-check.
    state["next_prayer"] = None
    state["next_prayer_time"] = None
    await asyncio.sleep(max(60, seconds_until("00:05")))
    machine.reset()


async def main():
    global SSID, PASSWORD, CAST_DEVICE_NAME, PRE_ATHAN_MINS, CALC_METHOD, LAT_ADJ_METHOD, MIDNIGHT_MODE, SCHOOL, PRAYER_VOLUMES, ATHAN_SOUND, FAJR_SOUND, PRE_ATHAN_SOUND, ATHANS, PRE_ATHAN, _cfg_lat, _cfg_lon, _cfg_address, _tz_string

    logger.configure(True, None)  # always print before WiFi is up
    led_blink()
    log("athan starting")

    if check_factory_reset():
        log("Factory reset confirmed, clearing config...")
        for f in (CONFIG_FILE, "cast_device.json", CAST_STATE_FILE, PRAYER_CACHE_FILE, LOCATION_CACHE_FILE, WIFI_FAIL_FILE):
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
    PASSWORD = config.get("password", "")
    # Optional now: onboarding only collects Wi-Fi. The cast device is chosen on
    # the Settings page, which writes cast_device_name (+ host/port). None here
    # just means "no cast target yet" — the device still boots and serves status.
    CAST_DEVICE_NAME = config.get("cast_device_name")
    PRE_ATHAN_MINS = int(config.get("pre_athan_mins", 10))
    CALC_METHOD = int(config.get("method", 2))
    LAT_ADJ_METHOD = int(config.get("lat_adj", 1))
    MIDNIGHT_MODE = int(config.get("midnight", 0))
    SCHOOL = int(config.get("school", 0))
    _cfg_lat = config.get("lat")
    _cfg_lon = config.get("lon")
    _cfg_address = config.get("address")
    for _p in ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]:
        _k = "vol_" + _p.lower()
        PRAYER_VOLUMES[_p] = int(config.get(_k, "50")) / 100.0
    ATHAN_SOUND = config.get("athan") or DEFAULT_ATHAN
    FAJR_SOUND = config.get("fajr_athan") or DEFAULT_FAJR
    PRE_ATHAN_SOUND = config.get("pre_athan") or DEFAULT_PRE_ATHAN
    ATHANS = build_athans(ATHAN_SOUND, FAJR_SOUND)
    PRE_ATHAN = athan_url(PRE_ATHAN_SOUND)

    local_ip = connect_to_wifi_with_retries(SSID, PASSWORD, hostname=DEVICE_HOSTNAME)
    if not local_ip:
        # Wi-Fi didn't come up. A transient outage (router rebooting) should just
        # retry, but a persistent failure (wrong password, renamed/removed SSID)
        # must not reboot-loop forever. Count consecutive failed boots and, after
        # a few, open onboarding so the user can fix the credentials in place.
        fails = _wifi_fail_count() + 1
        _set_wifi_fail_count(fails)
        if fails >= _WIFI_FAIL_THRESHOLD:
            log("Wi-Fi failed {} boots in a row — opening onboarding.".format(fails))
            _set_wifi_fail_count(0)
            from bilalcast.captive_portal import captive_portal as _portal

            await _portal()
            return  # never reached — portal resets after save
        log("Wi-Fi failed (boot {}/{}); rebooting to retry.".format(fails, _WIFI_FAIL_THRESHOLD))
        time.sleep(1)
        machine.reset()
    _set_wifi_fail_count(0)  # connected — clear the failed-boot counter
    logger.configure(DEBUG, SSID)  # SSID as ntfy title — unique per network

    # Populate state and start HTTP server immediately after WiFi so the
    # status page is reachable as soon as possible. Remaining boot steps
    # (OTA, NTP, location, prayer times) fill in the state afterwards.
    state["local_ip"] = local_ip
    state["device_name"] = CAST_DEVICE_NAME
    state["hostname"] = DEVICE_HOSTNAME
    state["boot_epoch"] = time.time()
    # Reflect the saved config in state right away so the settings page shows
    # persisted values immediately after a reboot, not only once the (slow)
    # location/discovery/prayer boot steps finish. lat/lon are re-affirmed with
    # resolved coordinates further below.
    state["address"] = _cfg_address or ""
    state["lat"] = float(_cfg_lat) if _cfg_lat else None
    state["lon"] = float(_cfg_lon) if _cfg_lon else None
    state["lat_adj"] = LAT_ADJ_METHOD
    state["midnight"] = MIDNIGHT_MODE
    state["school"] = SCHOOL
    state["athan"] = ATHAN_SOUND
    state["fajr_athan"] = FAJR_SOUND
    state["pre_athan"] = PRE_ATHAN_SOUND
    try:
        with open(CAST_STATE_FILE) as f:
            cs = json.load(f)
        state["last_cast_ok"] = cs.get("ok")
        state["last_cast_label"] = cs.get("label")
    except Exception:
        pass

    start_status_server(state, PRE_ATHAN_MINS, CALC_METHOD, PRAYER_VOLUMES, CONFIG_FILE, ACTIVATION_URL, do_cast, local_ip)
    start_mdns_responder(local_ip, local_ip)

    try:
        from bilalcast.ota import check_and_update
        if check_and_update():
            log("OTA update applied, rebooting...")
            time.sleep(1)
            machine.reset()
    except Exception as e:
        warn("OTA check failed: " + str(e))

    geo_lat, geo_lon, utc_offset, tz_string = _resolve_location()
    _tz_string = tz_string
    await set_rtc()
    if utc_offset:
        adjust_rtc(utc_offset)

    # Cast endpoint. Prefer an endpoint we already know — an explicit pin from
    # settings, else the mDNS cache from a previous boot — and TRUST it: no
    # reachability probe, no mDNS, just use it. We reboot after every prayer, so
    # any pre-cast probe runs before every cast; a momentary blip during that
    # probe would otherwise blank a perfectly good endpoint and drop us into a
    # flaky mDNS group scan. The cast itself (with its 3-min retry) is the real
    # reachability test, and a full end-to-end failure clears the cache (see
    # run_schedule) so the next reboot rediscovers. Discovery runs here only when
    # we have no known endpoint at all.
    from bilalcast.discovery import _load_cast_cache, _save_cast_cache
    _cfg_ch = config.get("cast_device_host")
    _cfg_cp = config.get("cast_device_port")
    if _cfg_ch and _cfg_cp:
        cast_host, cast_port = _cfg_ch, int(_cfg_cp)
        _save_cast_cache(cast_host, cast_port)  # keep the durable pin authoritative
        log("using pinned cast endpoint: {}:{}".format(cast_host, cast_port))
    else:
        cast_host, cast_port = _load_cast_cache()
        if cast_host:
            log("using cached cast endpoint: {}:{}".format(cast_host, cast_port))
        elif not CAST_DEVICE_NAME:
            # Wi-Fi-only onboarding, no device chosen yet. Boot normally and
            # serve the status/settings page so the user can pick one.
            cast_host, cast_port = None, None
            log("no cast device configured yet — pick one at Settings")
        else:
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
    state["athan"] = ATHAN_SOUND
    state["fajr_athan"] = FAJR_SOUND
    state["pre_athan"] = PRE_ATHAN_SOUND

    # Fetch prayer times with a persisted offline backup so an Aladhan/network
    # outage can't leave the device silent. Strategy:
    #   - Try the API a bounded number of times (prefer lat/lon, else address,
    #     else IP-geolocated coords). Bounded so it never blocks the event loop
    #     forever the way the old retry-forever path did.
    #   - On success: cache {date, times} to flash.
    #   - On failure: reuse the last cached day. Prayer times drift only ~1 min
    #     per day, so a recent cached day is a safe backup for a good while.
    #   - Only if we've NEVER cached (first boot during an outage) do we fall
    #     back to a blocking retry, since a device with no schedule is useless.
    def _fetch_once(_lat, _lon):
        if _lat is not None and _lon is not None:
            return try_prayers(_lat, _lon, CALC_METHOD, _tz_string, LAT_ADJ_METHOD, MIDNIGHT_MODE, SCHOOL)
        if _cfg_address:
            return try_prayers_by_address(_cfg_address, CALC_METHOD, _tz_string, LAT_ADJ_METHOD, MIDNIGHT_MODE, SCHOOL)
        return None

    times = None
    for _i in range(5):
        times = _fetch_once(lat, lon)
        if not times and (lat is None or lon is None) and geo_lat is not None:
            # address / no-coords attempt failed — try IP-geolocated coordinates
            times = _fetch_once(geo_lat, geo_lon)
            if times:
                lat, lon = geo_lat, geo_lon
                state["lat"], state["lon"] = lat, lon
        if times:
            break
        time.sleep(2)

    if times:
        _save_prayer_cache(times)
    else:
        cached, cached_date = _load_prayer_cache()
        if cached:
            warn("prayer API unavailable — using cached prayer times from {}".format(cached_date))
            send_ntfy("prayer API down — using cached times ({})".format(cached_date), priority=4, tags=["warning"])
            times = cached
        else:
            warn("prayer API unavailable and no cache — retrying until it responds")
            _flat = lat if lat is not None else geo_lat
            _flon = lon if lon is not None else geo_lon
            times = _get_prayer_times(_flat, _flon, CALC_METHOD, _tz_string)
            if times:
                _save_prayer_cache(times)
    state["prayer_times"] = times or {}

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
