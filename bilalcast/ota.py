import urequests  # pyright: ignore[reportMissingImports]
import ujson as json  # pyright: ignore[reportMissingImports]
import os

# ota runs in two contexts: the normal app flow (logger present) and the
# first-boot bootstrap, where logger.py has not been downloaded yet. Fall back
# to print() so logging never breaks the initial install.
try:
    from bilalcast.logger import log
except Exception:  # pragma: no cover - bootstrap path only
    def log(msg, level="INFO"):
        print(msg)

_HTTP_TIMEOUT = 15  # seconds; a stalled mirror shouldn't hang the OTA/boot


def _get(url):
    """urequests.get with a socket timeout, degrading gracefully if unsupported."""
    try:
        return urequests.get(url, timeout=_HTTP_TIMEOUT)
    except TypeError:
        return urequests.get(url)

OTA_OWNER  = "Project-Bilal"
OTA_REPO   = "bilal-cast"
OTA_BRANCH = "main"

_RAW = "https://raw.githubusercontent.com/{}/{}/{}".format(OTA_OWNER, OTA_REPO, OTA_BRANCH)
_VER_FILE = "ota_version.txt"
_FILE_VERS = "ota_file_versions.json"


def _local_version():
    try:
        with open(_VER_FILE) as f:
            return f.read().strip()
    except Exception:
        return None


def _remote_version():
    try:
        r = _get(_RAW + "/version.txt")
        try:
            return r.text.strip()
        finally:
            r.close()
    except Exception as e:
        log("OTA version check failed: " + str(e), "WARN")
        return None


def _makedirs(path):
    parts = path.split("/")
    for i in range(1, len(parts)):
        d = "/".join(parts[:i])
        if d:
            try:
                os.mkdir(d)
            except Exception:
                pass


def _download(url, local_path):
    _makedirs(local_path)
    for attempt in range(3):
        try:
            r = _get(url)
            try:
                with open(local_path, "wb") as f:
                    f.write(r.content)
            finally:
                r.close()
            log("OTA: " + local_path)
            return True
        except Exception as e:
            log("OTA retry {} {}: {}".format(attempt + 1, local_path, e), "WARN")
            if attempt < 2:
                import utime
                utime.sleep(2)
    return False


def _fetch_manifest():
    for attempt in range(3):
        try:
            r = _get(_RAW + "/manifest.json")
            try:
                return json.loads(r.text)
            finally:
                r.close()
        except Exception as e:
            log("OTA manifest retry {}: {}".format(attempt + 1, e), "WARN")
            if attempt < 2:
                import utime
                utime.sleep(2)
    return None


def _load_file_versions():
    try:
        with open(_FILE_VERS) as f:
            return json.loads(f.read())
    except Exception:
        return {}


def _save_file_versions(versions):
    try:
        with open(_FILE_VERS, "w") as f:
            f.write(json.dumps(versions))
    except Exception as e:
        log("OTA: file versions save failed: " + str(e), "ERROR")


def download_all():
    """Download all app files (first-boot install). Returns True if all succeeded."""
    manifest = _fetch_manifest()
    if manifest is None:
        log("OTA: could not fetch manifest", "ERROR")
        return False
    return download_changed(manifest)


def download_changed(manifest):
    """Download only files whose version differs from the locally recorded version.
    Returns True if all attempted downloads succeeded."""
    local_vers = _load_file_versions()
    failed = 0
    updated = {}
    for entry in manifest:
        remote_v = entry.get("version")
        local_v = local_vers.get(entry["local"])
        if remote_v is not None and remote_v == local_v:
            continue
        url = _RAW + "/" + entry["remote"]
        if _download(url, entry["local"]):
            updated[entry["local"]] = remote_v
        else:
            failed += 1
    if updated:
        local_vers.update(updated)
        _save_file_versions(local_vers)
    return failed == 0


def check_and_update():
    """Check remote version; download only changed files if outdated. Returns True if updated."""
    local_v = _local_version()
    remote_v = _remote_version()
    if remote_v is None or local_v == remote_v:
        return False
    log("OTA: updating {} -> {}".format(local_v, remote_v))
    manifest = _fetch_manifest()
    if manifest is None:
        log("OTA: could not fetch manifest", "ERROR")
        return False
    if download_changed(manifest):
        try:
            with open(_VER_FILE, "w") as f:
                f.write(remote_v)
        except Exception as e:
            log("OTA: version write failed: " + str(e), "ERROR")
        return True
    log("OTA: some downloads failed, not marking updated", "ERROR")
    return False
