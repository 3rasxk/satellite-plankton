"""
High-Performance In-Memory Cache Service with TTL support.
Prevents redundant DB queries and GEE overhead, ensuring sub-150ms response latency.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

_CACHE_STORE: Dict[str, Dict[str, Any]] = {}


def get_cached(key: str) -> Optional[Any]:
    """Retrieves data from in-memory cache if not expired."""
    entry = _CACHE_STORE.get(key)
    if entry is None:
        return None

    now = time.time()
    if (now - entry["timestamp"]) < entry["ttl_seconds"]:
        return entry["data"]

    # Expired
    del _CACHE_STORE[key]
    return None


def set_cached(key: str, data: Any, ttl_seconds: int = 300) -> None:
    """Sets data in in-memory cache with specified TTL in seconds."""
    _CACHE_STORE[key] = {
        "timestamp": time.time(),
        "ttl_seconds": ttl_seconds,
        "data": data,
    }


def clear_cache(key: Optional[str] = None) -> None:
    """Clears a specific key or entire cache."""
    global _CACHE_STORE
    if key is not None:
        _CACHE_STORE.pop(key, None)
    else:
        _CACHE_STORE.clear()
