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
GUARD_MS     = const(250)      # wake this many ms before the minute
POLL_MS      = const(20)       # fine polling to hit ss == 0
FEW_MIN_MS   = const(120000)   # "few minutes" before event (2 min)
MAX_CHUNK_MS = const(600000)   # cap re-check sleeps to 10 min


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
    cd   = settings["cast_device"]
    host = cd["host"]
    port = cd["port"]

    # Ask API for the next prayer
    prayer_tuple = await get_next_prayer(settings)  # expected ("Fajr", "05:12")
    if not prayer_tuple:
        return False

    prayer_name, prayer_time = prayer_tuple
    prayers = settings["prayers"]
    p_cfg = prayers[prayer_name]

    # Main (per-prayer) audio
    main_url = p_cfg.get("file")
    main_vol = p_cfg.get("volume", 0.5)

    # Reminder (global)
    r_cfg     = prayers.get("reminder") or {}
    r_enabled = bool((r_cfg.get("minutes") or 0) > 0)
    r_minutes = int(r_cfg.get("minutes") or 0)
    r_url     = r_cfg.get("file")
    r_vol     = r_cfg.get("volume", main_vol)

    # Minutes since midnight
    tgt = _hhmm_to_min(prayer_time)
    pre = (tgt - r_minutes) % 1440 if r_enabled else -1

    while True:
        # ----- compute time to next event (reminder or main) -----
        _y,_m,_d, hh, mm, ss, *_ = time.localtime()
        now = hh * 60 + mm

        d_tgt = (tgt - now) % 1440
        d_pre = (pre - now) % 1440 if r_enabled else 1 << 30

        # choose sooner non-zero delta
        delta_min = d_pre if (r_enabled and d_pre and d_pre < d_tgt) else d_tgt
        
        ms_to_event = delta_min * 60000 - ss * 1000
        if ms_to_event < 0:
            ms_to_event = 0

        # ----- dynamic coarse sleep: wake a few minutes before event -----
        WAKE_MARGIN_MS = FEW_MIN_MS + GUARD_MS
        while ms_to_event > WAKE_MARGIN_MS:
            chunk = ms_to_event - WAKE_MARGIN_MS
            if chunk > MAX_CHUNK_MS:
                chunk = MAX_CHUNK_MS
            await asyncio.sleep_ms(chunk)

            # recompute remaining time
            _y,_m,_d, hh, mm, ss, *_ = time.localtime()
            now = hh * 60 + mm
            d_tgt = (tgt - now) % 1440
            d_pre = (pre - now) % 1440 if r_enabled else 1 << 30
            delta_min = d_pre if (r_enabled and d_pre and d_pre < d_tgt) else d_tgt
            ms_to_event = delta_min * 60000 - ss * 1000
            if ms_to_event < 0:
                ms_to_event = 0
            gc.collect()

        # sleep until just before the minute boundary
        if ms_to_event > GUARD_MS:
            await asyncio.sleep_ms(ms_to_event - GUARD_MS)

        # fine poll to hit ss == 0 exactly
        while time.localtime()[5] != 0:
            await asyncio.sleep_ms(POLL_MS)

        # ----- top of minute: fire if match -----
        _y,_m,_d, hh, mm, _ss, *_ = time.localtime()
        now = hh * 60 + mm

        if r_enabled and now == pre:
            await play(r_url, host, port, r_vol)
            await asyncio.sleep(60)  # let it play
            machine.reset()

        if now == tgt:
            await play(main_url, host, port, main_vol)
            await asyncio.sleep(60)
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
            _athan_task.cancel()
            try:
                await _athan_task
            except asyncio.CancelledError:
                pass
            _athan_task = None
        _athan_task = asyncio.create_task(athan_scheduler(store))


def get_athan_task():
    return _athan_task
