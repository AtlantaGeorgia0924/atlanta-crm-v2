"""
Distributed Redis cache with in-process fallback.

All financial statement summaries are cached here so multiple Render
dynos share the same view.  If Redis is unavailable, the app falls back
to the in-process dict that was used previously – meaning degraded
consistency but no downtime.

Usage
-----
    from app.core.cache import get_statement_cache, set_statement_cache, invalidate_statement_cache

Environment variables
---------------------
    REDIS_URL   redis://:<password>@<host>:<port>   (optional)
"""
import json
import os
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Redis connection (lazy, optional) ─────────────────────────────────────────
_redis_client = None
_redis_available = False

REDIS_URL = os.getenv("REDIS_URL", "")
STATEMENT_CACHE_KEY = "cashflow:statement"
STATEMENT_TTL_SECONDS = 60

# In-process fallback (single-dyno consistency only)
_local_cache: dict[str, tuple[float, str]] = {}
_LOCAL_TTL = 60


def _get_redis():
    global _redis_client, _redis_available
    if _redis_client is not None:
        return _redis_client if _redis_available else None
    if not REDIS_URL:
        return None
    try:
        import redis  # type: ignore
        client = redis.from_url(REDIS_URL, socket_connect_timeout=2, socket_timeout=2, decode_responses=True)
        client.ping()
        _redis_client = client
        _redis_available = True
        logger.info("cache_backend=redis connected")
        return _redis_client
    except Exception as exc:
        _redis_available = False
        logger.warning("cache_backend=redis unavailable fallback=local error=%s", exc)
        return None


# ── Public helpers ────────────────────────────────────────────────────────────

def get_statement_cache() -> Optional[dict]:
    """Return cached statement dict or None if missing/expired."""
    r = _get_redis()
    try:
        if r is not None:
            raw = r.get(STATEMENT_CACHE_KEY)
            if raw:
                return json.loads(raw)
            return None
    except Exception as exc:
        logger.warning("cache_get_error key=%s error=%s", STATEMENT_CACHE_KEY, exc)

    # Fallback to local
    entry = _local_cache.get(STATEMENT_CACHE_KEY)
    if entry:
        stored_at, raw = entry
        if time.monotonic() - stored_at <= _LOCAL_TTL:
            return json.loads(raw)
        _local_cache.pop(STATEMENT_CACHE_KEY, None)
    return None


def set_statement_cache(statement: dict) -> None:
    """Store statement in Redis (with TTL) and local fallback."""
    raw = json.dumps(statement)
    r = _get_redis()
    try:
        if r is not None:
            r.setex(STATEMENT_CACHE_KEY, STATEMENT_TTL_SECONDS, raw)
    except Exception as exc:
        logger.warning("cache_set_error key=%s error=%s", STATEMENT_CACHE_KEY, exc)
    _local_cache[STATEMENT_CACHE_KEY] = (time.monotonic(), raw)


def invalidate_statement_cache() -> None:
    """Remove statement from Redis and local store."""
    r = _get_redis()
    try:
        if r is not None:
            r.delete(STATEMENT_CACHE_KEY)
    except Exception as exc:
        logger.warning("cache_invalidate_error key=%s error=%s", STATEMENT_CACHE_KEY, exc)
    _local_cache.pop(STATEMENT_CACHE_KEY, None)


# ── Generic helpers for future analytics caches ───────────────────────────────

def cache_get(key: str) -> Optional[str]:
    r = _get_redis()
    try:
        if r is not None:
            return r.get(key)
    except Exception as exc:
        logger.warning("cache_get_error key=%s error=%s", key, exc)
    entry = _local_cache.get(key)
    if entry:
        stored_at, val = entry
        if time.monotonic() - stored_at <= _LOCAL_TTL:
            return val
        _local_cache.pop(key, None)
    return None


def cache_set(key: str, value: str, ttl: int = STATEMENT_TTL_SECONDS) -> None:
    r = _get_redis()
    try:
        if r is not None:
            r.setex(key, ttl, value)
    except Exception as exc:
        logger.warning("cache_set_error key=%s error=%s", key, exc)
    _local_cache[key] = (time.monotonic(), value)


def cache_delete(key: str) -> None:
    r = _get_redis()
    try:
        if r is not None:
            r.delete(key)
    except Exception as exc:
        logger.warning("cache_delete_error key=%s error=%s", key, exc)
    _local_cache.pop(key, None)


def cache_hit_rate() -> dict:
    """Return basic Redis info for metrics/observability."""
    r = _get_redis()
    if r is None:
        return {"backend": "local", "available": False}
    try:
        info = r.info("stats")
        hits = info.get("keyspace_hits", 0)
        misses = info.get("keyspace_misses", 0)
        total = hits + misses
        rate = round(hits / total, 4) if total else 0.0
        return {"backend": "redis", "available": True, "hit_rate": rate, "hits": hits, "misses": misses}
    except Exception:
        return {"backend": "redis", "available": False}
