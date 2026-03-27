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
            resp = urequests.get("http://ip-api.com/json?fields=status,lat,lon,offset,timezone")
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
        resp = urequests.get(url)
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
        url += "&timezonestring=" + timezone
    resp = urequests.get(url)
    try:
        d = resp.json()
    finally:
        resp.close()
    return d


def get_all_prayers(lat, lon, method=2, timezone="", lat_adj=1, midnight=0, school=0):
    """Return all 5 prayer times for today as a dict, in local time."""
    while True:
        try:
            ct = time.localtime()
            date = "{:02d}-{:02d}-{:04d}".format(ct[2], ct[1], ct[0])
            d = _fetch_timings(date, lat, lon, method, timezone, lat_adj, midnight, school)
            if d.get("code") == 200:
                timings = d["data"]["timings"]
                result = {}
                for prayer in ATHANS_ORDER:
                    t = timings.get(prayer, "")[:5]
                    if t:
                        result[prayer] = t
                if result:
                    log("prayer times: " + str(result))
                    return result
                log("Prayer times empty, retrying...")
            else:
                log("Timings fetch failed (code {}), retrying...".format(d.get("code")))
        except Exception as e:
            log("Prayer times fetch failed, retrying: " + str(e))
        time.sleep(2)


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
    resp = urequests.get(url)
    try:
        d = resp.json()
    finally:
        resp.close()
    return d


def get_all_prayers_by_address(address, method=2, timezone="", lat_adj=1, midnight=0, school=0):
    """Return all 5 prayer times for today using an address string, retrying until success."""
    while True:
        try:
            ct = time.localtime()
            date = "{:02d}-{:02d}-{:04d}".format(ct[2], ct[1], ct[0])
            d = _fetch_timings_by_address(date, address, method, timezone, lat_adj, midnight, school)
            if d.get("code") == 200:
                timings = d["data"]["timings"]
                result = {}
                for prayer in ATHANS_ORDER:
                    t = timings.get(prayer, "")[:5]
                    if t:
                        result[prayer] = t
                if result:
                    log("prayer times (by address): " + str(result))
                    return result
                log("Prayer times empty, retrying...")
            else:
                log("Timings fetch failed (code {}), retrying...".format(d.get("code")))
        except Exception as e:
            log("Prayer times fetch failed, retrying: " + str(e))
        time.sleep(2)


def try_prayers_by_address(address, method=2, timezone="", lat_adj=1, midnight=0, school=0):
    """Single attempt, returns dict or None on failure (no retry)."""
    try:
        ct = time.localtime()
        date = "{:02d}-{:02d}-{:04d}".format(ct[2], ct[1], ct[0])
        d = _fetch_timings_by_address(date, address, method, timezone, lat_adj, midnight, school)
        if d.get("code") == 200:
            timings = d["data"]["timings"]
            result = {}
            for prayer in ATHANS_ORDER:
                t = timings.get(prayer, "")[:5]
                if t:
                    result[prayer] = t
            if result:
                return result
    except Exception as e:
        log("try_prayers_by_address failed: " + str(e))
    return None


def get_next_prayer(lat, lon, method=2, timezone=""):
    while True:
        try:
            ct = time.localtime()
            now_mins = ct[3] * 60 + ct[4]
            date = "{:02d}-{:02d}-{:04d}".format(ct[2], ct[1], ct[0])
            d = _fetch_timings(date, lat, lon, method, timezone)
            if d.get("code") == 200:
                timings = d["data"]["timings"]
                for prayer in ATHANS_ORDER:
                    t = timings.get(prayer, "")[:5]
                    if not t:
                        continue
                    h, m = t.split(":")
                    if int(h) * 60 + int(m) > now_mins:
                        log("next prayer: {} {}".format(prayer, t))
                        return prayer, t
                # All today's prayers have passed — fetch tomorrow's first
                tomorrow = time.localtime(time.mktime(ct) + 86400)
                date2 = "{:02d}-{:02d}-{:04d}".format(tomorrow[2], tomorrow[1], tomorrow[0])
                d2 = _fetch_timings(date2, lat, lon, method, timezone)
                if d2.get("code") == 200:
                    timings2 = d2["data"]["timings"]
                    for prayer in ATHANS_ORDER:
                        t = timings2.get(prayer, "")[:5]
                        if t:
                            log("next prayer (tomorrow): {} {}".format(prayer, t))
                            return prayer, t
                log("No known prayer found, retrying...")
            else:
                log("Timings fetch failed (code {}), retrying...".format(d.get("code")))
        except Exception as e:
            log("Next prayer fetch failed, retrying: " + str(e))
        time.sleep(2)
