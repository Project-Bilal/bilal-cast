import asyncio
import time



class DeviceRegistry:
    """
    Maintains cached device list + names.
    Runs background scans in multiple attempts, merges results, and reports progress.
    """
    def __init__(
        self,
        ip_address,
        *,
        cache_ttl_ms=30_000,
        attempts_total=10,
        attempt_timeout_ms=500,
        attempt_gap_ms=150,
        debounce_ms=300,
    ):
        # Tunables
        self._CACHE_TTL_MS = cache_ttl_ms
        self._ATTEMPTS_TOTAL = attempts_total
        self._ATTEMPT_TIMEOUT_MS = attempt_timeout_ms
        self._ATTEMPT_GAP_MS = attempt_gap_ms
        self._DEBOUNCE_MS = debounce_ms

        # State
        self._devices = []          # List[dict]: {"name","host","port"}
        self._fetched_at = 0
        self._scan_task = None
        self._scan_started_at = 0
        self._attempts_done = 0
        self._lock = asyncio.Lock()
        self._discovery = None
        self._ip_address = ip_address
        self._initialize_discovery()

    # ---------- Public API ----------

    def snapshot(self):
        """
        Returns dict with status + progress + device lists.
        """
        if self._scan_task and not self._scan_task.done():
            return {
                "status": "scanning",
                "percent": self._percent(),
                "attempts_done": self._attempts_done,
                "attempts_total": self._ATTEMPTS_TOTAL,
                "devices": self._devices,
            }
        if self._fresh():
            return {
                "status": "ready",
                "percent": 100,
                "attempts_done": self._ATTEMPTS_TOTAL,
                "attempts_total": self._ATTEMPTS_TOTAL,
                "devices": self._devices,
            }
        return {
            "status": "stale",
            "percent": 0,
            "attempts_done": 0,
            "attempts_total": self._ATTEMPTS_TOTAL,
            "devices": self._devices if self._devices else None,
        }

    async def ensure_scan(self, *, force=False):
        """Start a background scan if needed."""
        async with self._lock:
            if not force and self._fresh():
                return
            if self._scan_task and not self._scan_task.done():
                return
            await asyncio.sleep_ms(self._DEBOUNCE_MS)
            self._scan_started_at = time.ticks_ms()
            self._attempts_done = 0
            self._scan_task = asyncio.create_task(self._run_scan_multi_attempt())

    # ---------- Internals ----------
    def _initialize_discovery(self):
        from mdns_client import Client
        from mdns_client.service_discovery.txt_discovery import TXTServiceDiscovery
        
        client = Client(self._ip_address)
        self._discovery = TXTServiceDiscovery(client)

    def _fresh(self):
        if not self._devices:
            return False
        return time.ticks_diff(time.ticks_ms(), self._fetched_at) < self._CACHE_TTL_MS

    def _percent(self):
        done = min(self._attempts_done, self._ATTEMPTS_TOTAL)
        return int((done * 100) // self._ATTEMPTS_TOTAL)

    async def _run_scan_multi_attempt(self):
        merged = []
        try:
            for i in range(self._ATTEMPTS_TOTAL):
                try:
                    partial = await self.discover_cast_devices_attempt(discovery=self._discovery)
                except Exception as e:
                    print("scan attempt failed:", e)
                    partial = []
                merged = self._merge_devices(merged, partial)
                self._devices = merged
                self._attempts_done = i + 1
                if i + 1 < self._ATTEMPTS_TOTAL:
                    await asyncio.sleep_ms(self._ATTEMPT_GAP_MS)
        except Exception as e:
            print("Device scan run failed:", e)
            return
        self._devices = merged
        self._fetched_at = time.ticks_ms()

    # ---------- Merge & Extract ----------

    @staticmethod
    def _merge_devices(existing, new_list):
        index = {}
        out = []

        def key(d):
            if d.get("host") and d.get("port") is not None:
                return ("hp", d["host"], d["port"])
            return ("name", (d.get("name") or "").lower())

        for d in existing:
            k = key(d)
            index[k] = len(out)
            out.append(d)

        for d in new_list:
            k = key(d)
            if k in index:
                out[index[k]] = d
            else:
                index[k] = len(out)
                out.append(d)

        return out

    @staticmethod
    async def discover_cast_devices_attempt(discovery):
        r = []
        ds = await discovery.query_once("_googlecast", "_tcp", timeout=1.0)
        for d in ds if ds else []:
            if hasattr(d, 'txt_records') and 'fn' in d.txt_records and d.txt_records['fn']:
                    r.append({'port': d.port, 'host': d.ips.pop(), 'name': d.txt_records['fn'][0]})
        return r
