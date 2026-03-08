import machine
import network
import utime as time
import urequests
import ujson as json
import ntptime
from cast import Chromecast


# USER CONFIGURED DATA
SSID = "Sarhan"
PASSWORD = "7860000000"
ADDRESS = "2305%20N%20159th%20st,%20shoreline%20wa%2098133"  # URL encoded address
CAST_HOST = "10.0.0.73"        # hardcoded fallback if mDNS fails
CAST_PORT = 32067               # hardcoded fallback if mDNS fails
CAST_DEVICE_NAME = "Bilal Cast" # friendly name shown in Google Home
DEBUG = True                    # True = print to console, False = send via ntfy


# constants
FAJR_ATHAN = "athan_fajr_1"
ATHAN = "athan_1"
PRE_ATHAN = "Salat_Ibrahimiyya"
ATHANS = {
    "Fajr": FAJR_ATHAN,
    "Dhuhr": ATHAN,
    "Asr": ATHAN,
    "Maghrib": ATHAN,
    "Isha": ATHAN,
}
CAST_CACHE_FILE = "cast_device.json"


def log(msg):
    if DEBUG:
        print(msg)
    else:
        send_ntfy(msg)


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
                log("connected to wifi: " + str(wlan.ifconfig()))
                time.sleep(2)
                return wlan.ifconfig()[0]

        except Exception as e:
            log("Wi-Fi error on attempt {}/{}: {}".format(attempt, max_retries, e))

        time.sleep(retry_delay_s)

    log("Wi-Fi failed after {} attempts; resetting.".format(max_retries))
    time.sleep(1)
    machine.reset()


def set_rtc():
    ntptime.host = "pool.ntp.org"
    while True:
        try:
            ntptime.settime()
        except Exception as e:
            log("NTP sync failed, retrying: " + str(e))
            time.sleep(2)
            continue

        # Guard against silent failure: ntptime can succeed without raising
        # but leave the RTC at the Pico's default boot time (2021-01-01).
        year = time.localtime()[0]
        if year >= 2024:
            log("RTC set (UTC): " + str(time.localtime()))
            return

        log("RTC year implausible ({}), retrying...".format(year))
        time.sleep(2)


def pre_athan_time(hhmm):
    h, m = hhmm.split(":")
    total = int(h) * 60 + int(m) - 10
    return "{:02d}:{:02d}".format((total // 60) % 24, total % 60)


def seconds_until(hhmm):
    now = time.localtime()
    now_secs = now[3] * 3600 + now[4] * 60 + now[5]
    h, m = hhmm.split(":")
    target_secs = int(h) * 3600 + int(m) * 60
    diff = target_secs - now_secs
    if diff < 0:
        diff += 86400  # target is tomorrow
    return diff


def get_next_prayer():
    ct = time.localtime()
    formatted_date = f"{ct[2]:02d}-{ct[1]:02d}-{ct[0]}"
    url = f"https://api.aladhan.com/v1/nextPrayerByAddress/{formatted_date}?address={ADDRESS}&latitudeAdjustmentMethod=1&calendarMethod=MATHEMATICAL&method=2&timezonestring=UTC"

    while True:
        try:
            resp = urequests.get(url)
            try:
                resp_json = resp.json()
            finally:
                resp.close()  # always close, even if .json() throws
            if resp_json.get("code") == 200:
                timings = resp_json["data"]["timings"]
                # Filter to only prayers we know; API can include Sunrise/Imsak etc.
                for prayer, prayer_time in timings.items():
                    if prayer in ATHANS:
                        prayer_time = prayer_time[:5]  # strip any trailing timezone suffix
                        log("next prayer: {} {}".format(prayer, prayer_time))
                        return prayer, prayer_time
                log("No known prayer in response, retrying...")
        except Exception as e:
            log("Next prayer fetch failed, retrying: " + str(e))
        time.sleep(2)


def _load_cast_cache():
    try:
        with open(CAST_CACHE_FILE) as f:
            d = json.load(f)
        host, port = d.get("host"), d.get("port")
        if host and port:
            return host, int(port)
    except Exception:
        pass
    return None, None


def _save_cast_cache(host, port):
    try:
        with open(CAST_CACHE_FILE, "w") as f:
            json.dump({"host": host, "port": port}, f)
    except Exception as e:
        log("Cache save failed: " + str(e))


def _device_reachable(host, port):
    cc = None
    try:
        cc = Chromecast(host, port)
        return True
    except Exception:
        return False
    finally:
        if cc:
            try:
                cc.disconnect()
            except Exception:
                pass


def _mdns_find(local_ip, name):
    import asyncio

    try:
        from bilalcast.mdns_client import Client
        from bilalcast.mdns_client.service_discovery.txt_discovery import TXTServiceDiscovery
    except ImportError as e:
        log("mDNS not available: " + str(e))
        return None, None

    async def _scan():
        discovery = TXTServiceDiscovery(Client(local_ip))
        for attempt in range(10):
            try:
                results = await discovery.query_once("_googlecast", "_tcp", timeout=0.6)
                for d in results or ():
                    try:
                        fn = d.txt_records.get("fn") or []
                        found_name = fn[0].strip() if fn else ""
                    except Exception:
                        found_name = ""
                    if found_name.lower() == name.lower():
                        host = next((ip for ip in (d.ips or []) if "." in ip), None)
                        port = int(d.port) if d.port is not None else None
                        if host and port:
                            return host, port
            except Exception as e:
                log("mDNS attempt {} failed: {}".format(attempt + 1, e))
            await asyncio.sleep_ms(300)
        return None, None

    try:
        return asyncio.run(_scan())
    except Exception as e:
        log("mDNS scan error: " + str(e))
        return None, None


def resolve_cast_device(local_ip):
    # 1. Check cache and verify the device still responds
    host, port = _load_cast_cache()
    if host and port:
        log("Cache hit: {}:{}, verifying...".format(host, port))
        if _device_reachable(host, port):
            log("Cached device confirmed.")
            return host, port
        log("Cached device unreachable, scanning mDNS...")

    # 2. mDNS scan for the friendly name
    log("Scanning mDNS for '{}'...".format(CAST_DEVICE_NAME))
    host, port = _mdns_find(local_ip, CAST_DEVICE_NAME)
    if host and port:
        log("Found via mDNS: {}:{}".format(host, port))
        _save_cast_cache(host, port)
        return host, port

    # 3. Hardcoded fallback
    log("mDNS failed, using hardcoded fallback: {}:{}".format(CAST_HOST, CAST_PORT))
    return CAST_HOST, CAST_PORT


def cast_url(url, host, port, max_retries=3):
    for attempt in range(1, max_retries + 1):
        cc = None
        try:
            cc = Chromecast(host, port)
            if cc.play_url(url):
                return True
            log("Cast attempt {}/{}: no confirmation from device".format(attempt, max_retries))
        except Exception as e:
            log("Cast attempt {}/{} failed: {}".format(attempt, max_retries, e))
        finally:
            if cc:
                cc.disconnect()
        time.sleep(3)
    return False


def ensure_wifi():
    wlan = network.WLAN(network.STA_IF)
    if not wlan.isconnected():
        log("WiFi dropped, reconnecting...")
        connect_to_wifi_with_retries(SSID, PASSWORD)


def send_ntfy(msg):
    try:
        resp = urequests.post("https://ntfy.sh/bilalpico", data="shoreline - " + msg)
        resp.close()
    except Exception as e:
        print("ntfy failed:", e)  # non-fatal, do not crash


def main():
    log("athan starting")
    local_ip = connect_to_wifi_with_retries(SSID, PASSWORD)
    set_rtc()

    send_ntfy("online: {}".format(time.localtime()))

    cast_host, cast_port = resolve_cast_device(local_ip)
    prayer, prayer_time = get_next_prayer()
    pre_time = pre_athan_time(prayer_time)

    secs_to_pre = seconds_until(pre_time)
    secs_to_prayer = seconds_until(prayer_time)

    if secs_to_pre < secs_to_prayer:
        secs, audio_file, label = secs_to_pre, PRE_ATHAN, f"pre_{prayer}, {pre_time}"
    else:
        secs, audio_file, label = secs_to_prayer, ATHANS[prayer], f"{prayer}, {prayer_time}"

    time.sleep(secs)
    ensure_wifi()
    ok = cast_url(f"https://storage.googleapis.com/athans/{audio_file}.mp3", cast_host, cast_port)
    send_ntfy(label if ok else f"cast failed: {label}")

    machine.reset()


try:
    main()
except KeyboardInterrupt:
    log("stopped")
except Exception as e:
    log("fatal error: " + str(e))
    time.sleep(1)
    machine.reset()
