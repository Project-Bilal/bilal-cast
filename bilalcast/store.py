import asyncio
import time
import os
import gc
import ujson as json


def _fsync_best_effort():
    try:
        os.sync()
    except Exception:
        pass


class AsyncConfigStore:
    def __init__(self, file_path="config.json", *, retry_ms=50, timeout_ms=3000):
        self._file_path = file_path
        self._lock_path = file_path + ".lock"
        self._retry_ms = retry_ms
        self._timeout_ms = timeout_ms
        self._view = {}  # <= in-memory snapshot for sync reads

    async def _acquire_lock(self):
        start = time.ticks_ms()
        while True:
            try:
                os.mkdir(self._lock_path)
                return
            except Exception:
                if time.ticks_diff(time.ticks_ms(), start) > self._timeout_ms:
                    raise OSError("Config lock timeout")
                await asyncio.sleep_ms(self._retry_ms)

    def _release_lock(self):
        try:
            os.rmdir(self._lock_path)
        except Exception:
            pass

    # --- NEW: zero-await snapshot for Phew routes ---
    def snapshot_sync(self):
        # _view is only replaced while holding the FS lock,
        # so copying it here is safe and non-blocking.
        return dict(self._view)

    async def read_all(self, default=None):
        await self._acquire_lock()
        try:
            gc.collect()
            try:
                with open(self._file_path, "r") as f:
                    obj = json.load(f)
            except Exception:
                obj = {} if default is None else default
            finally:
                gc.collect()
            if not isinstance(obj, dict):
                obj = {}
            self._view = dict(obj)
            return obj
        finally:
            self._release_lock()

    async def write_all(self, data):
        await self._acquire_lock()
        tmp_path = self._file_path + ".tmp"
        try:
            gc.collect()
            with open(tmp_path, "w") as f:
                json.dump(data, f, separators=(",", ":"))
                try:
                    f.flush()
                except Exception:
                    pass
            _fsync_best_effort()
            try:
                os.remove(self._file_path)
            except Exception:
                pass
            os.rename(tmp_path, self._file_path)
            _fsync_best_effort()
            # update snapshot after successful replace (still under lock)
            self._view = dict(data) if isinstance(data, dict) else {}
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            self._release_lock()