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
    else:
        if level in (WARN, ERROR):
            send_ntfy("[{}] {}".format(level, msg))
        else:
            send_ntfy(msg)


def warn(msg):
    log(msg, WARN)


def error(msg):
    log(msg, ERROR)
