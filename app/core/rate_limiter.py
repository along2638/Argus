"""Redis-based sliding window rate limiter."""

from typing import Optional, Callable
from functools import wraps

import redis.asyncio as aioredis
from fastapi import Request, HTTPException

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
        """Check if a request is allowed under the rate limit."""
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
            return True, 0

    @classmethod
    def limit(
        cls,
        max_requests: int,
        window_seconds: int,
        key_func: Optional[Callable] = None,
    ):
        """Decorator for rate-limiting FastAPI endpoints.

        Usage:
            @router.post("/detect")
            @RateLimiter.limit(max_requests=10, window_seconds=60)
            async def detect(...):
                ...
        """
        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                # Get request from args or kwargs
                request = kwargs.get("request")
                if request is None:
                    for arg in args:
                        if isinstance(arg, Request):
                            request = arg
                            break

                if request is None:
                    return await func(*args, **kwargs)

                # Determine rate limit key
                if key_func:
                    key = key_func(request)
                else:
                    ip = request.client.host if request.client else "unknown"
                    key = f"{func.__name__}:{ip}"

                allowed, retry_after = await cls.is_allowed(key, max_requests, window_seconds)
                if not allowed:
                    raise HTTPException(
                        status_code=429,
                        detail=f"请求过于频繁，请 {retry_after} 秒后重试",
                        headers={"Retry-After": str(retry_after)},
                    )
                return await func(*args, **kwargs)
            return wrapper
        return decorator
