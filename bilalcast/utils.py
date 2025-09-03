async def disconnect_wifi(wifi_file):
    import os, time, machine
    os.remove(wifi_file)
    time.sleep(1)
    machine.reset()

async def sync_hms_from_http(url, retries=5, delay_ms=2000):
    import requests, asyncio, machine, time, gc
    while retries:
        try:
            r = requests.get(url)
            print(r.text)
            try:
                dh = r.headers.get('date') or r.headers.get('Date')
                if dh:
                    p = dh.split()  # "Tue, 02 Sep 2025 17:36:55 GMT"
                    t = p[4] if len(p) >= 5 else None
                    if t:
                        hh, mm, ss = int(t[0:2]), int(t[3:5]), int(t[6:8])
                        print(f"Synced time from {url} to {hh}:{mm}:{ss}")
                        y, m, d, wd, *_ = time.localtime()
                        machine.RTC().datetime((y, m, d, wd, hh, mm, ss, 0))
                        return True
            finally:
                r.close()
        except:
            pass
        gc.collect()
        await asyncio.sleep_ms(delay_ms)
        retries -= 1
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

def get_pre_time(t):
    h = int(t[:2]); m = int(t[3:5])
    mins = (h*60 + m - 10) % 1440
    return "%02d:%02d" % (mins // 60, mins % 60)


async def fetch_with_retry(url, retries=5, delay_ms=2000):
    import requests, asyncio, gc, json
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

async def get_next_prayer(method=None, 
                          school=None,
                          locationMode=None,
                          latitudeAdjustmentMethod=None, 
                          address=None, 
                          latitude=None, 
                          longitude=None):
    import time
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
    return resp["data"]['timings'].popitem() if resp else None