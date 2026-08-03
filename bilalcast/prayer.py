import utime as time
import urequests

from bilalcast.logger import log

FAJR_ATHAN = "https://storage.googleapis.com/athans/athan_fajr_1.mp3"
ATHAN = "https://storage.googleapis.com/athans/athan_1.mp3"
PRE_ATHAN = "https://storage.googleapis.com/athans/Salat_Ibrahimiyya.mp3"
ATHANS = {
    "Fajr": FAJR_ATHAN,
    "Dhuhr": ATHAN,
    "Asr": ATHAN,
    "Maghrib": ATHAN,
    "Isha": ATHAN,
}
ATHANS_ORDER = ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]

_HTTP_TIMEOUT = 15  # seconds; keeps a stalled server from hanging the device forever


def _get(url):
    """urequests.get with a socket timeout where the port/urequests supports it.

    Falls back to a plain get if this build's urequests predates the timeout
    kwarg, so hardening can never break networking outright.
    """
    try:
        return urequests.get(url, timeout=_HTTP_TIMEOUT)
    except TypeError:
        return urequests.get(url)


def pre_athan_time(hhmm, mins=10):
    h, m = hhmm.split(":")
    total = int(h) * 60 + int(m) - int(mins)
    return "{:02d}:{:02d}".format((total // 60) % 24, total % 60)


def seconds_until(hhmm):
    now = time.localtime()
    now_secs = now[3] * 3600 + now[4] * 60 + now[5]
    h, m = hhmm.split(":")
    target_secs = int(h) * 3600 + int(m) * 60
    diff = target_secs - now_secs
    if diff < 0:
        diff += 86400
    return diff


def get_location():
    while True:
        try:
            resp = _get("http://ip-api.com/json?fields=status,lat,lon,offset,timezone")
            try:
                d = resp.json()
            finally:
                resp.close()
            if d.get("status") == "success":
                lat, lon = d["lat"], d["lon"]
                offset = d.get("offset", 0)
                timezone = d.get("timezone", "")
                log("location: {}, {} (UTC offset {}s, tz {})".format(lat, lon, offset, timezone))
                return lat, lon, offset, timezone
            log("IP geolocation failed, retrying...")
        except Exception as e:
            log("IP geolocation error, retrying: " + str(e))
        time.sleep(2)


def _url_encode(s):
    """Percent-encode a string for use in a URL query parameter."""
    result = ""
    for c in s:
        cp = ord(c)
        if cp < 128 and (c.isalpha() or c.isdigit() or c in "-_.~"):
            result += c
        elif c == " ":
            result += "+"
        elif cp < 128:
            result += "%{:02X}".format(cp)
        else:
            for b in c.encode("utf-8"):
                result += "%{:02X}".format(b)
    return result


def geocode_address(address):
    """Geocode an address via Nominatim. Returns (lat, lon) floats or (None, None)."""
    try:
        url = "https://nominatim.openstreetmap.org/search?q=" + _url_encode(address) + "&format=json&limit=1"
        resp = _get(url)
        try:
            results = resp.json()
        finally:
            resp.close()
        if results:
            log("geocoded '{}' → {}, {}".format(address, results[0]["lat"], results[0]["lon"]))
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception as e:
        log("geocode failed: " + str(e))
    return None, None


def _extract_timings(d):
    """Pull the 5 prayer HH:MM values out of an Aladhan response, or None.

    Uses .get() throughout so a malformed/partial response returns None
    instead of raising.
    """
    if not d or d.get("code") != 200:
        return None
    timings = d.get("data", {}).get("timings", {})
    result = {}
    for prayer in ATHANS_ORDER:
        t = timings.get(prayer, "")[:5]
        if t:
            result[prayer] = t
    return result or None


def _fetch_timings(date, lat, lon, method=2, timezone="", lat_adj=1, midnight=0, school=0):
    url = (
        "https://api.aladhan.com/v1/timings/" + date
        + "?latitude={:.4f}".format(lat)
        + "&longitude={:.4f}".format(lon)
        + "&latitudeAdjustmentMethod={}".format(int(lat_adj))
        + "&calendarMethod=MATHEMATICAL"
        + "&method={}".format(int(method))
        + "&midnightMode={}".format(int(midnight))
        + "&school={}".format(int(school))
    )
    if timezone:
        url += "&timezonestring=" + _url_encode(timezone)
    resp = _get(url)
    try:
        return resp.json()
    finally:
        resp.close()


def _fetch_timings_by_address(date, address, method=2, timezone="", lat_adj=1, midnight=0, school=0):
    url = (
        "https://api.aladhan.com/v1/timingsByAddress/" + date
        + "?address=" + _url_encode(address)
        + "&latitudeAdjustmentMethod={}".format(int(lat_adj))
        + "&calendarMethod=MATHEMATICAL"
        + "&method={}".format(int(method))
        + "&midnightMode={}".format(int(midnight))
        + "&school={}".format(int(school))
    )
    if timezone:
        url += "&timezonestring=" + _url_encode(timezone)
    resp = _get(url)
    try:
        return resp.json()
    finally:
        resp.close()


def _today(ct):
    return "{:02d}-{:02d}-{:04d}".format(ct[2], ct[1], ct[0])


def get_all_prayers(lat, lon, method=2, timezone="", lat_adj=1, midnight=0, school=0):
    """Return all 5 prayer times for today as a dict, in local time. Retries until success."""
    while True:
        try:
            d = _fetch_timings(_today(time.localtime()), lat, lon, method, timezone, lat_adj, midnight, school)
            result = _extract_timings(d)
            if result:
                log("prayer times: " + str(result))
                return result
            log("Prayer times fetch failed (code {}), retrying...".format(d.get("code") if d else "?"))
        except Exception as e:
            log("Prayer times fetch failed, retrying: " + str(e))
        time.sleep(2)


def get_all_prayers_by_address(address, method=2, timezone="", lat_adj=1, midnight=0, school=0):
    """Return all 5 prayer times for today using an address string. Retries until success."""
    while True:
        try:
            d = _fetch_timings_by_address(_today(time.localtime()), address, method, timezone, lat_adj, midnight, school)
            result = _extract_timings(d)
            if result:
                log("prayer times (by address): " + str(result))
                return result
            log("Prayer times fetch failed (code {}), retrying...".format(d.get("code") if d else "?"))
        except Exception as e:
            log("Prayer times fetch failed, retrying: " + str(e))
        time.sleep(2)


def try_prayers_by_address(address, method=2, timezone="", lat_adj=1, midnight=0, school=0):
    """Single attempt, returns dict or None on failure (no retry)."""
    try:
        d = _fetch_timings_by_address(_today(time.localtime()), address, method, timezone, lat_adj, midnight, school)
        return _extract_timings(d)
    except Exception as e:
        log("try_prayers_by_address failed: " + str(e))
    return None
