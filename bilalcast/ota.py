import urequests  # pyright: ignore[reportMissingImports]
import ujson as json  # pyright: ignore[reportMissingImports]
import os

OTA_OWNER  = "Project-Bilal"
OTA_REPO   = "bilal-cast"
OTA_BRANCH = "main"

_RAW = "https://raw.githubusercontent.com/{}/{}/{}".format(OTA_OWNER, OTA_REPO, OTA_BRANCH)
_API = "https://api.github.com/repos/{}/{}/contents".format(OTA_OWNER, OTA_REPO)
_VER_FILE = "ota_version.txt"

# (github_dir, local_dir) — non-recursive; subdirectories are skipped automatically
_OTA_DIRS = [
    ("bilalcast", "bilalcast"),  # .py app files
    ("bilalcast/www", "www"),    # HTML + icon → /www/ on filesystem
]

# Infrastructure files frozen into the UF2 — skip even if present in directory listing
_FROZEN = {"bilalcast/captive_portal.py", "bilalcast/logger.py", "bilalcast/ota.py", "bilalcast/www/icon.png"}


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
        print("OTA failed:", local_path, e)
        return False


def _list_dir(github_path):
    try:
        r = urequests.get(
            _API + "/" + github_path,
            headers={"User-Agent": "bilalcast-ota"},
        )
        try:
            items = json.loads(r.text)
        finally:
            r.close()
        return [(i["path"], i["download_url"]) for i in items if i["type"] == "file"]
    except Exception as e:
        print("OTA list failed:", github_path, e)
        return []


def download_all():
    """Download all OTA app files. Returns True if all succeeded."""
    failed = 0
    for github_dir, local_dir in _OTA_DIRS:
        for github_path, url in _list_dir(github_dir):
            if github_path in _FROZEN:
                continue
            filename = github_path[len(github_dir) + 1:]
            if not _download(url, local_dir + "/" + filename):
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
