import utime as time
import ujson as json
import machine

from bilalcast.cast import Chromecast
from bilalcast.logger import log

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


def _mdns_find(local_ip, name):
    import asyncio
    from bilalcast.mdns_client import Client
    from bilalcast.mdns_client.service_discovery.txt_discovery import TXTServiceDiscovery

    async def _scan():
        discovery = TXTServiceDiscovery(Client(local_ip))
        for attempt in range(10):
            try:
                results = await discovery.query_once("_googlecast", "_tcp", timeout=3)
                for d in results or ():
                    try:
                        fn = d.txt_records.get("fn") or []
                        found_name = fn[0].strip() if fn else ""
                    except Exception:
                        found_name = ""
                    if found_name.lower() == name.lower():
                        host = None
                        for ip in (d.ips or []):
                            if "." in ip:
                                host = ip
                                break
                        port = int(d.port) if d.port is not None else None
                        if host and port:
                            return host, port
            except Exception as e:
                log("mDNS attempt {} failed: {}".format(attempt + 1, e))
            await asyncio.sleep_ms(300)
        log("mDNS scan failed finding device...")
        return None, None

    try:
        return asyncio.run(_scan())
    except Exception as e:
        log("mDNS scan error: " + str(e))
        return None, None


def resolve_cast_device(local_ip, name):
    host, port = _load_cast_cache()
    if host and port:
        log("Cache hit: {}:{}, verifying...".format(host, port))
        if _device_reachable(host, port):
            log("Cached device confirmed.")
            return host, port
        log("Cached device unreachable, scanning mDNS...")

    log("Scanning mDNS for '{}'...".format(name))
    host, port = _mdns_find(local_ip, name)
    if host and port:
        log("Found via mDNS: {}:{}".format(host, port))
        _save_cast_cache(host, port)
        return host, port

    log("mDNS failed, resetting...")

    machine.reset()


def cast_url(url, host, port, max_retries=3):
    last_error = "transport_id timeout"
    for attempt in range(1, max_retries + 1):
        cc = None
        try:
            cc = Chromecast(host, port)
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
