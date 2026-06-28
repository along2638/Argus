import asyncio
from typing import Optional

import redis.asyncio as aioredis

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class AlarmDeduplicator:
    """Redis-based alarm deduplication with cooldown TTL."""

    _redis: Optional[aioredis.Redis] = None

    @classmethod
    async def get_redis(cls) -> aioredis.Redis:
        """Get or create Redis connection."""
        if cls._redis is None:
            cls._redis = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
            )
            # Mask password in log
            safe_url = settings.REDIS_URL
            if "@" in safe_url:
                prefix = safe_url.split("@")[0]
                safe_url = prefix.split("://")[0] + "://***@" + safe_url.split("@")[1]
            logger.info("redis_connected", url=safe_url)
        return cls._redis

    @classmethod
    async def close(cls) -> None:
        """Close Redis connection."""
        if cls._redis:
            await cls._redis.close()
            cls._redis = None
            logger.info("redis_disconnected")

    @classmethod
    def _make_key(cls, stream_id: str, class_name: str, track_id: int,
                  position: tuple = None) -> str:
        """Generate Redis key for alarm deduplication.

        Key format: alarm:{stream_id}:{class_name}:{track_id}
        When track_id is -1 (no tracking), use grid position for dedup.
        """
        if track_id == -1 and position is not None:
            # 将画面分成 4x3=12 个网格，不同网格的同一类目标独立告警
            gx = min(position[0] // 3, 3)  # 0-3
            gy = min(position[1] // 3, 2)  # 0-2
            return f"alarm:{stream_id}:{class_name}:g{gx}_{gy}"
        return f"alarm:{stream_id}:{class_name}:{track_id}"

    @classmethod
    async def should_trigger_alarm(
        cls,
        stream_id: str,
        class_name: str,
        track_id: int,
        ttl: Optional[int] = None,
        position: tuple = None,
    ) -> bool:
        """Check if alarm should be triggered based on cooldown.

        Returns:
            True if alarm should be triggered (new track or TTL expired),
            False if within cooldown period.
        """
        if ttl is None:
            ttl = settings.ALARM_COOLDOWN_TTL

        redis = await cls.get_redis()
        key = cls._make_key(stream_id, class_name, track_id, position)

        try:
            # SET NX returns True if key was set (doesn't exist), False if exists
            was_set = await redis.set(key, "1", nx=True, ex=ttl)

            if was_set:
                logger.debug(
                    "alarm_triggered",
                    stream_id=stream_id,
                    class_name=class_name,
                    track_id=track_id,
                )
                return True
            else:
                logger.debug(
                    "alarm_cooldown_active",
                    stream_id=stream_id,
                    class_name=class_name,
                    track_id=track_id,
                )
                return False
        except Exception as e:
            logger.error(
                "alarm_dedup_error",
                stream_id=stream_id,
                error=str(e),
            )
            # On Redis error, allow alarm to trigger (fail-open)
            return True

    @classmethod
    async def get_queue_depth(cls) -> int:
        """Get the number of active alarm keys (approximate)."""
        try:
            redis = await cls.get_redis()
            # Use SCAN to count alarm keys
            count = 0
            async for _ in redis.scan_iter(match="alarm:*", count=100):
                count += 1
            return count
        except Exception as e:
            logger.error("queue_depth_error", error=str(e))
            return -1


# Singleton instance
alarm_dedup = AlarmDeduplicator()
