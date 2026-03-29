import urequests  # pyright: ignore[reportMissingImports]
import ujson as json  # pyright: ignore[reportMissingImports]
import os

OTA_OWNER  = "Project-Bilal"
OTA_REPO   = "bilal-cast"
OTA_BRANCH = "main"

_RAW = "https://raw.githubusercontent.com/{}/{}/{}".format(OTA_OWNER, OTA_REPO, OTA_BRANCH)
_VER_FILE = "ota_version.txt"


def _local_version():
    try:
        with open(_VER_FILE) as f:
            return f.read().strip()
    except Exception:
        return None


def _remote_version():
    try:
        r = urequests.get(_RAW + "/version.txt")
        try:
            return r.text.strip()
        finally:
            r.close()
    except Exception as e:
        print("OTA version check failed:", e)
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
            r = urequests.get(url)
            try:
                with open(local_path, "wb") as f:
                    f.write(r.content)
            finally:
                r.close()
            print("OTA:", local_path)
            return True
        except Exception as e:
            print("OTA retry", attempt + 1, local_path, e)
            if attempt < 2:
                import utime
                utime.sleep(2)
    return False


def _fetch_manifest():
    for attempt in range(3):
        try:
            r = urequests.get(_RAW + "/manifest.json")
            try:
                return json.loads(r.text)
            finally:
                r.close()
        except Exception as e:
            print("OTA manifest retry", attempt + 1, e)
            if attempt < 2:
                import utime
                utime.sleep(2)
    return None


def download_all():
    """Download all OTA app files listed in manifest.json. Returns True if all succeeded."""
    manifest = _fetch_manifest()
    if manifest is None:
        print("OTA: could not fetch manifest")
        return False
    failed = 0
    for entry in manifest:
        url = _RAW + "/" + entry["remote"]
        if not _download(url, entry["local"]):
            failed += 1
    return failed == 0


def check_and_update():
    """Check remote version; download everything if outdated. Returns True if updated."""
    local_v = _local_version()
    remote_v = _remote_version()
    if remote_v is None or local_v == remote_v:
        return False
    print("OTA: updating", local_v, "->", remote_v)
    if download_all():
        try:
            with open(_VER_FILE, "w") as f:
                f.write(remote_v)
        except Exception as e:
            print("OTA: version write failed:", e)
        return True
    print("OTA: some downloads failed, not marking updated")
    return False
