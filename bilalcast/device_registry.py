# DeviceRegistry (MicroPython / Pico W)
import asyncio
import time

class DeviceRegistry:
    """Small-footprint device cache + background scanner (10 attempts w/ progress)."""

    def __init__(self, ip_address, *, cache_ttl_ms=30_000, attempts_total=10,
                 attempt_timeout_ms=500, attempt_gap_ms=150, debounce_ms=300):
        # Tunables
        self._TTL = cache_ttl_ms
        self._N   = attempts_total
        self._TO  = attempt_timeout_ms   # per-attempt timeout (ms)
        self._GAP = attempt_gap_ms
        self._DB  = debounce_ms

        # State
        self._devices = []      # List[{"name","host","port"}]
        self._fetched_at = 0
        self._scan_task = None
        self._attempts_done = 0
        self._lock = asyncio.Lock()

        # Discovery
        from bilalcast.mdns_client import Client
        from bilalcast.mdns_client.service_discovery.txt_discovery import TXTServiceDiscovery
        self._discovery = TXTServiceDiscovery(Client(ip_address))

    # ----- Public -----
    def snapshot(self):
        scanning = self._scan_task and not self._scan_task.done()
        if scanning:
            return {
                "status": "scanning",
                "percent": self._percent(),
                "attempts_done": self._attempts_done,
                "attempts_total": self._N,
                "devices": self._devices,
            }
        if self._fresh():
            return {
                "status": "ready",
                "percent": 100,
                "attempts_done": self._N,
                "attempts_total": self._N,
                "devices": self._devices,
            }
        return {
            "status": "stale",
            "percent": 0,
            "attempts_done": 0,
            "attempts_total": self._N,
            "devices": self._devices if self._devices else None,
        }

    async def ensure_scan(self, *, force=False):
        async with self._lock:
            if not force and self._fresh():
                return
            if self._scan_task and not self._scan_task.done():
                return
            await asyncio.sleep_ms(self._DB)
            self._attempts_done = 0
            # keep last-known devices during scan (no UI flash)
            self._scan_task = asyncio.create_task(self._run_scan())

    # ----- Internals -----
    def _fresh(self):
        return self._devices and time.ticks_diff(time.ticks_ms(), self._fetched_at) < self._TTL

    def _percent(self):
        d = self._attempts_done
        if d <= 0:
            return 0
        n = self._N
        return (d * 100) // n if n else 100

    async def _run_scan(self):
        merged = self._devices  # reuse list; we’ll rebuild into a new list below
        index = {}              # key -> position in 'out'
        out = []                # rebuilt list to minimize realloc thrash

        for i in range(self._N):
            # one attempt
            partial = await self._discover_once(self._TO)
            # merge (no copies)
            for d in partial:
                k = (("hp", d.get("host"), d.get("port"))
                     if (d.get("host") and (d.get("port") is not None))
                     else ("name", (d.get("name") or "").lower()))
                pos = index.get(k, -1)
                if pos >= 0:
                    out[pos] = d
                else:
                    index[k] = len(out)
                    out.append(d)

            # expose partials
            merged = out
            self._devices = merged
            self._attempts_done = i + 1

            if i + 1 < self._N:
                await asyncio.sleep_ms(self._GAP)

        self._devices = merged
        self._fetched_at = time.ticks_ms()

    # ----- Discovery (single attempt) -----
    async def _discover_once(self, timeout_ms):
        """Return List[{'name','host','port'}] from a single mDNS TXT pass."""
        timeout_s = max(0.05, (timeout_ms or 0) / 1000)
        try:
            ds = await self._discovery.query_once("_googlecast", "_tcp", timeout=timeout_s)
        except Exception:
            return []

        res = []
        # local refs to avoid attribute lookups in loop
        for d in ds or ():
            # name from TXT 'fn'
            name = ""
            try:
                fn = d.txt_records.get("fn")
                if fn and isinstance(fn, list) and fn:
                    v = fn[0]
                    if isinstance(v, str):
                        name = v.strip()
            except Exception:
                pass

            # prefer IPv4 if present, but do not mutate d.ips
            host = None
            try:
                ips = d.ips or []
                for ip in ips:
                    if "." in ip:
                        host = ip
                        break
                if host is None and ips:
                    host = ips[0]
            except Exception:
                pass

            # port
            port = None
            try:
                port = int(d.port) if d.port is not None else None
            except Exception:
                pass

            if name or host:
                res.append({"name": name, "host": host, "port": port})
        return res
