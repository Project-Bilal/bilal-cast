WIFI_FILE = "wifi.json"
CONFIG_FILE = "config.json"


async def disconnect_wifi(wifi_file):
    import uos as os, utime as time, machine  # pyright: ignore[reportMissingImports]

    os.remove(wifi_file)
    time.sleep(1)
    machine.reset()


async def set_rtc(retries=3, delay_ms=500):
    # MicroPython-friendly imports
    import utime as time            # pyright: ignore[reportMissingImports]
    import machine, gc              # pyright: ignore[reportMissingImports]
    import urequests as requests  # pyright: ignore[reportMissingImports]
    import uasyncio as asyncio  # pyright: ignore[reportMissingImports]


    URL = "https://worldtimeapi.org/api/timezone/utc.txt"

    for _ in range(retries):
        r = None
        try:
            r = requests.get(URL)          # blocking; keep call brief
            txt = r.text

            # Parse "unixtime: 1756971434" (fastest way to get full UTC date+time+weekday)
            unixtime = None
            for line in txt.split("\n"):
                if line.startswith("unixtime:"):
                    unixtime = int(line.split(":", 1)[1].strip())
                    break

            y, m, d, H, M, S, wd, _ = time.gmtime(unixtime)
            machine.RTC().datetime((y, m, d, wd, H, M, S, 0))
            return True

        except Exception as e:
            # Log and retry; don't hard-reset the board from a helper
            print("RTC set error:", e)
        finally:
            try:
                if r: r.close()            # always free the socket on MicroPython
            except: 
                pass
            gc.collect()
            await asyncio.sleep_ms(delay_ms)  # yield back to the loop

    return False



def url_encode(s):
    safe = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~"
    res = []
    for c in s:
        if c in safe:
            res.append(c)
        else:
            res.append("%%%02X" % ord(c))
    return "".join(res)


def get_pre_time(t, offset=10):
    h = (ord(t[0]) - 48) * 10 + (ord(t[1]) - 48)
    m = (ord(t[3]) - 48) * 10 + (ord(t[4]) - 48)
    mins = (h * 60 + m - offset) % 1440
    return "%02d:%02d" % (mins // 60, mins % 60)


async def fetch_with_retry(url, retries=5, delay_ms=2000):
    import urequests as requests, uasyncio as asyncio, gc, json  # pyright: ignore[reportMissingImports]
    while retries:
        try:
            r = requests.get(url)
            try:
                obj = json.loads(r.text) if r.status_code == 200 else None
            finally:
                r.close()  # critical on MicroPython
            if obj and obj.get("code") == 200:
                return obj
        except Exception:
            pass
        gc.collect()
        await asyncio.sleep_ms(delay_ms)
        retries -= 1
    return None


async def get_next_prayer(
    method=None,
    school=None,
    locationMode=None,
    latitudeAdjustmentMethod=None,
    address=None,
    latitude=None,
    longitude=None,
):
    import utime as time  # pyright: ignore[reportMissingImports]

    y, m, d, *_ = time.localtime()
    base_url = "https://api.aladhan.com/v1/"
    q = None
    if locationMode == "address":
        q = "nextPrayerByAddress/%02d-%02d-%04d?timezonestring=UTC&address=%s" % (d, m, y, url_encode(address))
    else:
        q = "nextPrayer/%02d-%02d-%04d?timezonestring=UTC&latitude=%s&longitude=%s" % (d, m, y, latitude, longitude)

    q += "&method=%s&school=%s&latitudeAdjustmentMethod=%s" % (method or 2, school or 0, latitudeAdjustmentMethod or 3)
    url = base_url + q

    resp = await fetch_with_retry(url)
    return resp["data"]["timings"].popitem() if resp else None
