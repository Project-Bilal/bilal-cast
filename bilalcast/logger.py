import urequests  # pyright: ignore[reportMissingImports]
import ujson as json  # pyright: ignore[reportMissingImports]

_debug = True
_device_name = "Bilal Cast"

INFO  = "INFO"
WARN  = "WARN"
ERROR = "ERROR"


def configure(debug, device_name):
    global _debug, _device_name
    _debug = bool(debug)
    _device_name = device_name or "Bilal Cast"


def send_ntfy(msg, priority=3, tags=None):
    payload = {"topic": "bilalpico", "title": _device_name, "message": msg, "priority": priority}
    if tags:
        payload["tags"] = tags
    try:
        resp = urequests.post(
            "https://ntfy.sh/",
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        resp.close()
    except Exception as e:
        print("ntfy failed:", e)


def log(msg, level=INFO):
    if _debug:
        print("[{}] {}".format(level, msg))
    elif level == ERROR:
        send_ntfy("[ERROR] " + msg, priority=5, tags=["rotating_light"])
    elif level == WARN:
        send_ntfy("[WARN] " + msg, priority=4, tags=["warning"])
    # INFO in production is intentionally dropped: the device is headless (no
    # console) and routing every INFO line to ntfy floods the topic and risks
    # rate-limiting the notifications that matter. Milestone notifications
    # (boot "online", cast results) call send_ntfy() directly.


def warn(msg):
    log(msg, WARN)


def error(msg):
    log(msg, ERROR)
