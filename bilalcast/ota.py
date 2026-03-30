import urequests  # pyright: ignore[reportMissingImports]
import ujson as json  # pyright: ignore[reportMissingImports]
import os

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
        print("OTA: file versions save failed:", e)


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
    print("OTA: updating", local_v, "->", remote_v)
    manifest = _fetch_manifest()
    if manifest is None:
        print("OTA: could not fetch manifest")
        return False
    if download_changed(manifest):
        try:
            with open(_VER_FILE, "w") as f:
                f.write(remote_v)
        except Exception as e:
            print("OTA: version write failed:", e)
        return True
    print("OTA: some downloads failed, not marking updated")
    return False
