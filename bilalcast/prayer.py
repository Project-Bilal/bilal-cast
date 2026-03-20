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


def get_next_prayer(lat, lon):
    ct = time.localtime()
    date = "{:02d}-{:02d}-{:04d}".format(ct[2], ct[1], ct[0])
    url = (
        "https://api.aladhan.com/v1/nextPrayer/" + date
        + "?latitude={:.4f}".format(lat)
        + "&longitude={:.4f}".format(lon)
        + "&latitudeAdjustmentMethod=1"
        + "&calendarMethod=MATHEMATICAL"
        + "&method=2"
        + "&timezonestring=UTC"
    )
    while True:
        try:
            resp = urequests.get(url)
            try:
                resp_json = resp.json()
            finally:
                resp.close()
            if resp_json.get("code") == 200:
                timings = resp_json["data"]["timings"]
                for prayer, prayer_time in timings.items():
                    if prayer in ATHANS:
                        prayer_time = prayer_time[:5]
                        log("next prayer: {} {}".format(prayer, prayer_time))
                        return prayer, prayer_time
                log("No known prayer in response, retrying...")
        except Exception as e:
            log("Next prayer fetch failed, retrying: " + str(e))
        time.sleep(2)
