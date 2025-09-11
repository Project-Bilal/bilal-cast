import machine, gc  # pyright: ignore[reportMissingImports]

LOG_INFO = 0b00001
LOG_WARNING = 0b00010
LOG_ERROR = 0b00100
LOG_DEBUG = 0b01000
LOG_EXCEPTION = 0b10000
LOG_ALL = LOG_INFO | LOG_WARNING | LOG_ERROR | LOG_DEBUG | LOG_EXCEPTION

_logging_types = LOG_ALL


def datetime_string():
    dt = machine.RTC().datetime()
    return "{0:04d}-{1:02d}-{2:02d} {4:02d}:{5:02d}:{6:02d}".format(*dt)


def log(level, text):
    datetime = datetime_string()
    log_entry = "{0} [{1:8} /{2:>4}kB] {3}".format(datetime, level, round(gc.mem_free() / 1024), text)
    print(log_entry)


def info(*items):
    if _logging_types & LOG_INFO:
        log("info", " ".join(map(str, items)))


def warn(*items):
    if _logging_types & LOG_WARNING:
        log("warning", " ".join(map(str, items)))


def error(*items):
    if _logging_types & LOG_ERROR:
        log("error", " ".join(map(str, items)))


def debug(*items):
    if _logging_types & LOG_DEBUG:
        log("debug", " ".join(map(str, items)))


def exception(*items):
    if _logging_types & LOG_EXCEPTION:
        log("exception", " ".join(map(str, items)))
