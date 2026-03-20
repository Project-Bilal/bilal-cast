import urequests
import ujson as json

_debug = True
_device_name = "Bilal Cast"


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
        print("ntfy failed:", e)  # non-fatal, do not crash


def log(msg):
    if _debug:
        print(msg)
    else:
        send_ntfy(msg)
