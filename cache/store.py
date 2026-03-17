"""
cache/store.py
--------------
Simple in-memory cache with per-key TTL.
Thread-safe for use across the agent thread pool.
"""

import time
import threading
from typing import Any, Optional

_cache: dict = {}
_lock = threading.Lock()


def get(key: str) -> Optional[Any]:
    with _lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.time() > expires_at:
            del _cache[key]
            return None
        return value


def set(key: str, value: Any, ttl: int) -> None:
    with _lock:
        _cache[key] = (value, time.time() + ttl)


def delete(key: str) -> None:
    with _lock:
        _cache.pop(key, None)


def clear_ticker(ticker: str) -> None:
    """Remove all cached entries for a specific ticker."""
    with _lock:
        keys = [k for k in _cache if k.startswith(f"{ticker}:")]
        for k in keys:
            del _cache[k]


def stats() -> dict:
    with _lock:
        now = time.time()
        live = sum(1 for _, (_, exp) in _cache.items() if exp > now)
        return {"total_keys": len(_cache), "live_keys": live}
