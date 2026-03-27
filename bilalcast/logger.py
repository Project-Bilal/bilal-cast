import utime as time
import urequests
import ujson as json

_debug = True
_device_name = "Bilal Cast"
_log_buffer = []
_MAX_ENTRIES = 200

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
    t = time.localtime()
    ts = "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(
        t[0], t[1], t[2], t[3], t[4], t[5])
    _log_buffer.append([ts, level, str(msg)])
    if len(_log_buffer) > _MAX_ENTRIES:
        _log_buffer.pop(0)
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


def get_log_buffer():
    return _log_buffer


def clear_log():
    global _log_buffer
    _log_buffer = []


def flush_log(filename):
    """Write buffer to disk. Called ~6x/day to minimise flash write cycles."""
    try:
        with open(filename, "w") as f:
            for entry in _log_buffer:
                f.write("{} [{}] {}\n".format(entry[0], entry[1], entry[2]))
    except Exception as e:
        print("log flush failed:", e)


def load_log(filename):
    """Read persisted log file and prepend to buffer at boot."""
    global _log_buffer
    loaded = []
    try:
        with open(filename) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    # format: "YYYY-MM-DD HH:MM:SS [LEVEL] message"
                    ts = line[:19]
                    lb = line.index("[", 19)
                    rb = line.index("]", lb)
                    level = line[lb + 1:rb]
                    msg = line[rb + 2:]
                    loaded.append([ts, level, msg])
                except Exception:
                    pass
        if len(loaded) > _MAX_ENTRIES:
            loaded = loaded[-_MAX_ENTRIES:]
    except Exception:
        pass  # no file yet — first boot
    # Prepend loaded entries so old history appears before current session
    _log_buffer = loaded + _log_buffer
    if len(_log_buffer) > _MAX_ENTRIES:
        _log_buffer = _log_buffer[-_MAX_ENTRIES:]
