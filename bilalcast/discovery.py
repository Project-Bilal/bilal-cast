import asyncio
import utime as time
import ujson as json

from bilalcast.cast import Chromecast
from bilalcast.logger import log

_persistent_client = None

CAST_CACHE_FILE = "cast_device.json"


def _load_cast_cache():
    try:
        with open(CAST_CACHE_FILE) as f:
            d = json.load(f)
        host, port = d.get("host"), d.get("port")
        if host and port:
            return host, int(port)
    except Exception:
        pass
    return None, None


def _save_cast_cache(host, port):
    try:
        with open(CAST_CACHE_FILE, "w") as f:
            json.dump({"host": host, "port": port}, f)
    except Exception as e:
        log("Cache save failed: " + str(e))


def _device_reachable(host, port):
    s = None
    try:
        import socket

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect((host, port))
        return True
    except Exception:
        return False
    finally:
        if s:
            try:
                s.close()
            except Exception:
                pass


def start_mdns_responder(local_ip, device_ip):
    global _persistent_client
    from bilalcast.mdns_client import Client
    _persistent_client = Client(local_ip)
    _persistent_client.enable_responder("bilalcast.local", device_ip)


async def _scan_cast_services(local_ip, passes=6, timeout=3, want=None):
    """Multi-pass _googlecast scan that merges partial records across passes.

    A single mDNS query usually resolves only a subset of the services on the
    network: each service needs SRV (port) + A (ip) + TXT (friendly name),
    and those records often arrive across different passes. Cast groups are
    frequently the ones missing from any given pass, which made single-pass
    lookups fail to find them. Keying by the stable per-service instance name
    and merging host/port/fn across passes makes discovery reliable for
    groups and individual devices alike.

    Returns {instance_name: {"host": ip|None, "port": int|None, "fn": str|None}}.
    If ``want`` (a friendly name) is given, returns early as soon as that
    entry is fully resolved.
    """
    from bilalcast.mdns_client import Client
    from bilalcast.mdns_client.service_discovery.txt_discovery import TXTServiceDiscovery
    client = _persistent_client if _persistent_client is not None else Client(local_ip)
    discovery = TXTServiceDiscovery(client)
    want = want.lower() if want else None
    acc = {}
    for _ in range(passes):
        try:
            results = await discovery.query_once("_googlecast", "_tcp", timeout=timeout)
        except Exception as e:
            log("cast scan error: " + str(e))
            results = ()
        for d in results or ():
            entry = acc.setdefault(d.name, {"host": None, "port": None, "fn": None})
            if entry["port"] is None and d.port:
                entry["port"] = int(d.port)
            if entry["host"] is None:
                for ip in (d.ips or []):
                    if "." in ip:
                        entry["host"] = ip
                        break
            if entry["fn"] is None:
                try:
                    fn = (d.txt_records or {}).get("fn") or []
                    if fn:
                        entry["fn"] = fn[0].strip()
                except Exception:
                    pass
        if want is not None:
            for entry in acc.values():
                if entry["fn"] and entry["fn"].lower() == want and entry["host"] and entry["port"]:
                    return acc
        await asyncio.sleep_ms(200)
    return acc


async def _mdns_find(local_ip, name):
    target = name.lower()
    acc = await _scan_cast_services(local_ip, passes=10, timeout=3, want=name)
    for entry in acc.values():
        if entry["fn"] and entry["fn"].lower() == target and entry["host"] and entry["port"]:
            return entry["host"], entry["port"]
    log("mDNS scan failed finding device...")
    return None, None


async def list_cast_devices(local_ip, scans=5):
    """Multi-pass mDNS scan. Returns deduplicated list of {name, host, port}."""
    acc = await _scan_cast_services(local_ip, passes=scans, timeout=3)
    devices = []
    seen = []
    for entry in acc.values():
        name = entry["fn"]
        if not name or name in seen:
            continue
        seen.append(name)
        devices.append({"name": name, "host": entry["host"], "port": entry["port"]})
    return devices


async def resolve_cast_device(local_ip, name):
    host, port = _load_cast_cache()
    if host and port:
        log("Cache hit: {}:{}, verifying...".format(host, port))
        if _device_reachable(host, port):
            log("Cached device confirmed.")
            return host, port
        log("Cached device unreachable, scanning mDNS...")

    log("Scanning mDNS for '{}'...".format(name))
    host, port = await _mdns_find(local_ip, name)
    if host and port:
        log("Found via mDNS: {}:{}".format(host, port))
        _save_cast_cache(host, port)
        return host, port

    log("mDNS scan failed — cast device not found. Proceeding without cast.")
    return None, None


def cast_url(url, host, port, volume=0.5, max_retries=3):
    last_error = "transport_id timeout"
    for attempt in range(1, max_retries + 1):
        cc = None
        try:
            cc = Chromecast(host, port)
            # Set the speaker volume BEFORE playback. play_url then does
            # STOP -> LAUNCH -> (wait transport) -> LOAD, so the volume is
            # applied seconds before any audio starts.
            if volume is not None:
                cc.set_volume(volume)
            if cc.play_url(url):
                return True, None
            log("Cast attempt {}/{}: transport_id timeout".format(attempt, max_retries))
        except Exception as e:
            last_error = str(e)
            log("Cast attempt {}/{} failed: {}".format(attempt, max_retries, e))
        finally:
            if cc:
                cc.disconnect()
        if attempt < max_retries:
            time.sleep(3)
    return False, last_error
