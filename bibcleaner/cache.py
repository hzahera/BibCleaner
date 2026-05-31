"""Process-wide, thread-safe TTL cache.

Used to memoize provider lookups so repeated arXiv IDs / DOIs / titles — within
a run and across requests on a long-lived server — don't re-hit the (rate-
limited) upstream APIs.  In-memory and per-instance; swap for Redis when the
service needs to scale beyond one process.
"""

import time
import threading
from typing import Any, Optional


class TTLCache:
    def __init__(self, ttl: float = 86400.0, maxsize: int = 5000):
        self.ttl = ttl
        self.maxsize = maxsize
        self._data: dict = {}  # key -> (expires_at, value)
        self._lock = threading.Lock()

    def get(self, key) -> Optional[Any]:
        now = time.time()
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            expires_at, value = item
            if expires_at < now:
                self._data.pop(key, None)
                return None
            return value

    def set(self, key, value) -> None:
        with self._lock:
            if len(self._data) >= self.maxsize and key not in self._data:
                # Evict the entry closest to expiry.
                oldest = min(self._data, key=lambda k: self._data[k][0])
                self._data.pop(oldest, None)
            self._data[key] = (time.time() + self.ttl, value)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
