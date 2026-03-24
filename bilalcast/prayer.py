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
        diff += 86400
    return diff


def get_location():
    while True:
        try:
            resp = urequests.get("http://ip-api.com/json")
            try:
                d = resp.json()
            finally:
                resp.close()
            if d.get("status") == "success":
                lat, lon = d["lat"], d["lon"]
                log("location: {}, {}".format(lat, lon))
                return lat, lon
            log("IP geolocation failed, retrying...")
        except Exception as e:
            log("IP geolocation error, retrying: " + str(e))
        time.sleep(2)


def _fetch_timings(date, lat, lon):
    url = (
        "https://api.aladhan.com/v1/timings/" + date
        + "?latitude={:.4f}".format(lat)
        + "&longitude={:.4f}".format(lon)
        + "&latitudeAdjustmentMethod=1"
        + "&calendarMethod=MATHEMATICAL"
        + "&method=2"
        + "&timezonestring=UTC"
    )
    resp = urequests.get(url)
    try:
        d = resp.json()
    finally:
        resp.close()
    return d


def get_next_prayer(lat, lon):
    while True:
        try:
            ct = time.localtime()
            now_mins = ct[3] * 60 + ct[4]
            date = "{:02d}-{:02d}-{:04d}".format(ct[2], ct[1], ct[0])
            d = _fetch_timings(date, lat, lon)
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
                d2 = _fetch_timings(date2, lat, lon)
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
