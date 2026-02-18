"""engine.core.cache

Simple in-memory cache with TTL.

A cache is a lie you tell yourself to go faster.
A TTL is the part where you admit you might be wrong.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any


class TTLCache:
    """Thread-safe TTL cache."""

    def __init__(self, default_ttl_s: float = 60.0):
        self._default_ttl_s = float(default_ttl_s)
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.RLock()

    def get(self, key: str) -> Any | None:
        now = time.time()
        with self._lock:
            item = self._store.get(key)
            if item is None:
                return None
            expires_at, value = item
            if now < expires_at:
                return value
            self._store.pop(key, None)
            return None

    def set(self, key: str, value: Any, *, ttl_s: float | None = None) -> None:
        ttl = self._default_ttl_s if ttl_s is None else float(ttl_s)
        with self._lock:
            self._store[str(key)] = (time.time() + ttl, value)

    def get_or_set(self, key: str, factory: Callable[[], Any], *, ttl_s: float | None = None) -> Any:
        val = self.get(key)
        if val is not None:
            return val
        val = factory()
        self.set(key, val, ttl_s=ttl_s)
        return val

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


_global_cache = TTLCache()


def get_cache() -> TTLCache:
    return _global_cache
