# led_status.py  — MicroPython (Pico W)
from machine import Pin  # pyright: ignore[reportMissingImports]
from micropython import const  # pyright: ignore[reportMissingImports]
import uasyncio as asyncio  # pyright: ignore[reportMissingImports]

# States
ONBOARDING = const(0)  # fast blink
WIFI_CONNECTED = const(1)  # slow blink
NO_CONFIG = const(2)  # solid on
HAS_CONFIG = const(3)  # off
EXCEPTION_STATE = const(4)  # solid on (same as NO_CONFIG but kept separate)

# Timing (ms) kept small & simple
_FAST = const(120)  # ~8 Hz blink period/2 (on/off halves)
_SLOW = const(600)  # ~0.8 Hz blink period/2

# Module-level singletons (keeps footprint small)
_led = Pin("LED", Pin.OUT)
_state = HAS_CONFIG
_task = None


async def _runner():
    global _state
    while True:
        s = _state

        # Solid ON states
        if s == NO_CONFIG or s == EXCEPTION_STATE:
            _led.value(1)
            # Sleep in chunks so state changes apply quickly without CPU spin
            await asyncio.sleep_ms(200)
            continue

        # Solid OFF
        if s == HAS_CONFIG:
            _led.value(0)
            await asyncio.sleep_ms(200)
            continue

        # Blinks
        if s == ONBOARDING:
            _led.value(1)
            await asyncio.sleep_ms(_FAST)
            _led.value(0)
            await asyncio.sleep_ms(_FAST)
            continue

        if s == WIFI_CONNECTED:
            _led.value(1)
            await asyncio.sleep_ms(_SLOW)
            _led.value(0)
            await asyncio.sleep_ms(_SLOW)
            continue

        # Fallback safety
        _led.value(0)
        await asyncio.sleep_ms(200)


def start(initial_state=HAS_CONFIG):
    """Start the background LED task once."""
    global _task, _state
    if _task is None:
        _state = initial_state
        _task = asyncio.create_task(_runner())


def stop():
    """Stop the background LED task (LED turns off)."""
    global _task
    if _task:
        _task.cancel()
        _task = None
    _led.value(0)


def set_state(s):
    """Update LED behavior immediately."""
    global _state
    _state = s


# Convenience helpers (optional)
def onboarding():
    set_state(ONBOARDING)


def wifi_connected():
    set_state(WIFI_CONNECTED)


def no_config():
    set_state(NO_CONFIG)


def has_config():
    set_state(HAS_CONFIG)


def exception():
    set_state(EXCEPTION_STATE)
