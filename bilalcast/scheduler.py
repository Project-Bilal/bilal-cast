# athan_scheduler.py
from micropython import const  # pyright: ignore[reportMissingImports]
import asyncio, time, machine, gc  # pyright: ignore[reportMissingImports]

try:  # support for local development with local files
    from utils import get_next_prayer  # async -> returns (prayer_name:str, prayer_time:"HH:MM")
    from cast import Chromecast
except ImportError:
    from bilalcast.utils import get_next_prayer  # async -> returns (prayer_name:str, prayer_time:"HH:MM")
    from bilalcast.cast import Chromecast

# ---------- small helpers ----------
GUARD_MS = const(250)  # wake this many ms before the minute
POLL_MS = const(20)  # fine-grained wait to hit ss == 0 exactly


def _hhmm_to_min(s):
    # s like "HH:MM"
    return int(s[:2]) * 60 + int(s[3:5])


def _file_url(name):
    base = "https://storage.googleapis.com/athans/"

    if name.startswith("https://"):
        return name
    return base + name


async def play(file, host, port, volume=None):
    # retry 3 times
    file_url = _file_url(file)
    success = False
    for _ in range(3):
        try:
            cast = Chromecast(host, port)
            cast.set_volume(volume)
            cast.disconnect()
            asyncio.sleep(1)
            cast = Chromecast(host, port)
            cast.play_url(file_url)
            cast.disconnect()
            success = True
            break
        except Exception as e:
            print(e)
            asyncio.sleep(1)
    if not success:
        return False
    return True


# ---------- core casting ----------
async def cast(settings):
    cd = settings["cast_device"]
    host = cd["host"]
    port = cd["port"]
    # Ask API for the next prayer
    prayer_tuple = await get_next_prayer(
        method=settings.get("method"),
        school=settings.get("school"),
        locationMode=settings.get("locationMode"),
        latitudeAdjustmentMethod=settings["latitudeAdjustmentMethod"],
        address=settings.get("address"),
        latitude=settings.get("latitude"),
        longitude=settings.get("longitude"),
    )
    if not prayer_tuple:
        return False
    prayer_name, prayer_time = prayer_tuple  # e.g. ("Fajr", "05:12")
    prayers = settings["prayers"]
    p_cfg = prayers[prayer_name]

    # Main (per-prayer) audio
    main_url = p_cfg.get("file")
    main_vol = p_cfg.get("volume", None)

    # Reminder (global)
    r_cfg = prayers.get("reminder") or {}
    r_enabled = bool((r_cfg.get("minutes") or 0) > 0)
    r_minutes = int(r_cfg.get("minutes") or 0)
    r_url = r_cfg.get("file")
    # default reminder volume to the prayer's volume if not set
    r_vol = r_cfg.get("volume", main_vol)

    tgt = _hhmm_to_min(prayer_time)  # target minute of day
    pre = (tgt - r_minutes) % 1440 if r_enabled else -1

    while True:
        # --- coarse sleep: wake just before next minute ---
        ss = time.localtime()[5]
        ms_to_min = (60 - ss) * 1000
        if ms_to_min > GUARD_MS:
            await asyncio.sleep_ms(ms_to_min - GUARD_MS)

        # --- fine wait: hit the exact minute boundary (ss == 0) ---
        while True:
            if time.localtime()[5] == 0:
                break
            await asyncio.sleep_ms(POLL_MS)

        # --- top of minute ---
        _y, _m, _d, hh, mm, _ss, *_ = time.localtime()
        now = hh * 60 + mm

        if r_enabled and now == pre:
            await play(r_url, host, port, r_vol)
            # let it play a bit, then reset to re-fetch next prayer
            await asyncio.sleep(100)
            machine.reset()

        if now == tgt:
            await play(main_url, host, port, main_vol)
            await asyncio.sleep(200)
            machine.reset()

        gc.collect()


# ---------- Athan scheduler ----------
# One global handle to the scheduler task
_athan_task = None
_restart_lock = asyncio.Lock()


async def athan_scheduler(store):
    """
    Long-running background job:
    - waits until settings are available
    - then calls cast(settings) which should handle scheduling/prayer playback
    """
    try:
        settings = await _wait_for_settings(store)
        await cast(settings)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print("athan_scheduler error:", e)


async def _wait_for_settings(store):
    while True:
        settings = await store.read_all()
        if settings:
            return settings
        await asyncio.sleep_ms(200)


async def restart_athan(store):
    """
    Cancel the current athan task (if any) and start a new one.
    This function is safe to call from anywhere (including request handlers).
    """
    global _athan_task
    async with _restart_lock:
        if _athan_task is not None:
            # Cancel and await to let it process CancelledError
            _athan_task.cancel()
            try:
                await _athan_task
            except asyncio.CancelledError:
                pass
            _athan_task = None

        # Start fresh in the background (do NOT return it to be awaited by callers)
        print("re-starting athan")
        _athan_task = asyncio.create_task(athan_scheduler(store))


def get_athan_task():
    return _athan_task
