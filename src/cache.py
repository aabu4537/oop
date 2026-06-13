"""Redis cache module — cache-aside pattern.

All public methods fail silently when Redis is unavailable so the application
degrades gracefully to direct DB reads.  Callers never need to handle Redis
errors; a cache miss (None) is always the safe fallback.

Cache key conventions
─────────────────────
  teams:list        — full team list (sorted by Elo), TTL 1hr
  teams:{team_id}   — single team, TTL 1hr

Invalidation
────────────
  Call cache.invalidate("teams:*") after ingest_elo completes to bust all
  stale Elo ratings.  With the 1hr TTL, stale reads are bounded even without
  explicit invalidation.
"""
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_TEAMS_TTL = 3600  # 1 hour

_client = None


def _get_client():
    """Return a Redis client, initialising lazily.  Returns None if unavailable."""
    global _client
    if _client is not None:
        return _client
    try:
        import redis
        from src.config import get_settings
        _client = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
        _client.ping()
        logger.debug("Redis connection established")
    except Exception as exc:
        logger.debug("Redis unavailable — cache disabled: %s", exc)
        _client = None
    return _client


class RedisCache:
    """Cache-aside Redis wrapper. All methods fail silently if Redis is unavailable."""

    def get(self, key: str) -> Any | None:
        try:
            client = _get_client()
            if client is None:
                return None
            raw = client.get(key)
            return json.loads(raw) if raw is not None else None
        except Exception as exc:
            logger.debug("Cache get(%r) failed: %s", key, exc)
            return None

    def set(self, key: str, value: Any, ttl: int = _TEAMS_TTL) -> None:
        try:
            client = _get_client()
            if client is None:
                return
            client.setex(key, ttl, json.dumps(value, default=str))
        except Exception as exc:
            logger.debug("Cache set(%r) failed: %s", key, exc)

    def invalidate(self, pattern: str) -> None:
        """Delete all keys matching a glob pattern (e.g. 'teams:*')."""
        try:
            client = _get_client()
            if client is None:
                return
            deleted = 0
            for key in client.scan_iter(pattern):
                client.delete(key)
                deleted += 1
            logger.info("Cache invalidated %d key(s) matching %r", deleted, pattern)
        except Exception as exc:
            logger.debug("Cache invalidate(%r) failed: %s", pattern, exc)


# Module-level singleton used by routers
cache = RedisCache()
