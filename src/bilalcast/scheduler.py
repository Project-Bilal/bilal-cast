from bilalcast.cast_functions import play_url
from micropython import const
import asyncio
from bilalcast.utils import get_next_prayer
import time

import machine, gc

DING_URL = "https://storage.googleapis.com/athans/ding.mp3"
FAJR_ATHAN_URL = "https://storage.googleapis.com/athans/athan_fajr_1.mp3"
ATHAN_URL = "https://storage.googleapis.com/athans/athan_1.mp3"
PRE_ATHAN_URL = "https://storage.googleapis.com/athans/Salat_Ibrahimiyya.mp3"

async def cast(settings):
    GUARD_MS = const(250)   # wake this many ms before the minute
    POLL_MS  = const(20)    # fine-grained wait to hit ss == 0 exactly

    def _hhmm_to_min(s):
        # s like "HH:MM"
        return int(s[:2]) * 60 + int(s[3:5])

    host = settings.get('cast_device', {}).get('host')
    port = settings.get('cast_device', {}).get('port')

    prayer_tuple = await get_next_prayer(method=settings.get('method'), 
                                                     school=settings.get('school'),
                                                     locationMode=settings.get('locationMode'),
                                                     latitudeAdjustmentMethod=settings.get('latitudeAdjustmentMethod'),
                                                     address=settings.get('address'), 
                                                     latitude=settings.get('latitude'), 
                                                     longitude=settings.get('longitude'))

    if not prayer_tuple:
        return False
    prayer_name, prayer_time = prayer_tuple

    tgt = _hhmm_to_min(prayer_time)
    pre = (tgt - 10) % 1440
    url_main = FAJR_ATHAN_URL if prayer_name == 'Fajr' else ATHAN_URL

    while True:
        # --- coarse sleep: wake just before next minute ---
        ss = time.localtime()[5]
        ms_to_min = (60 - ss) * 1000
        if ms_to_min > GUARD_MS:
            await asyncio.sleep_ms(ms_to_min - GUARD_MS)

        # --- fine wait: hit the exact minute boundary (ss == 0) ---
        while True:
            ss = time.localtime()[5]
            if ss == 0:
                break
            await asyncio.sleep_ms(POLL_MS)

        # --- at the top of the minute; do exact-equality checks ---
        _y, _m, _d, hh, mm, _ss, *_ = time.localtime()
        now = hh * 60 + mm

        if now == pre:
            await play_url(PRE_ATHAN_URL, host, port=port)
            await asyncio.sleep(100)
            machine.reset()

        if now == tgt:
            await play_url(url_main, host, port=port)
            await asyncio.sleep(200)
            machine.reset()

        gc.collect()

# ---------- Athan scheduler ----------
# Keep this simple & non-blocking. It reads config snapshots and schedules work.
async def athan_scheduler(store):    
    print("athan scheduler started")
    try:
        settings = None
        while True:
            settings = await store.read_all()
            if not settings:
                asyncio.sleep(200)
            break
        await cast(settings)
    except asyncio.CancelledError:
        pass


async def restart_athan(store, loop):
    print("restarting athan")
    """Cancel the current athan task (if any) and start a new one."""
    if loop and not loop.done():
        print("athan found")
        loop.cancel()
        try:
            await loop   # let it process CancelledError
            print("athan loop cancelled")
        except asyncio.CancelledError:
            
            pass
    loop = asyncio.create_task(athan_scheduler(store))
    return loop