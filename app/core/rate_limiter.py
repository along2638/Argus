"""Redis-based sliding window rate limiter."""

from typing import Optional

import redis.asyncio as aioredis

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class RateLimiter:
    """Sliding window rate limiter backed by Redis."""

    _redis: Optional[aioredis.Redis] = None

    @classmethod
    async def _get_redis(cls) -> aioredis.Redis:
        if cls._redis is None:
            cls._redis = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
            )
        return cls._redis

    @classmethod
    async def close(cls) -> None:
        if cls._redis is not None:
            await cls._redis.close()
            cls._redis = None

    @classmethod
    async def is_allowed(
        cls,
        key: str,
        max_requests: int,
        window_seconds: int,
    ) -> tuple[bool, int]:
        """Check if a request is allowed under the rate limit.

        Uses a simple fixed-window counter with TTL.

        Args:
            key: Unique identifier (e.g. IP address, user ID).
            max_requests: Maximum requests allowed in the window.
            window_seconds: Window duration in seconds.

        Returns:
            Tuple of (is_allowed, retry_after_seconds).
            retry_after_seconds is 0 when allowed, otherwise seconds until the window resets.
        """
        try:
            redis = await cls._get_redis()
            redis_key = f"ratelimit:{key}"

            current = await redis.incr(redis_key)
            if current == 1:
                await redis.expire(redis_key, window_seconds)

            if current > max_requests:
                ttl = await redis.ttl(redis_key)
                retry_after = max(ttl, 1)
                logger.warning(
                    "rate_limit_exceeded",
                    key=key,
                    current=current,
                    max_requests=max_requests,
                    retry_after=retry_after,
                )
                return False, retry_after

            return True, 0
        except Exception as e:
            logger.error("rate_limiter_error", key=key, error=str(e))
            # Fail-open: allow the request if Redis is down
            return True, 0
