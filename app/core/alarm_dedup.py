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
        """Get or create Redis connection with connection pool."""
        if cls._redis is None:
            cls._redis = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                max_connections=20,
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

        使用距离去重：同一位置 30 秒内不重复告警，不同位置独立告警。
        """
        if ttl is None:
            ttl = settings.ALARM_COOLDOWN_TTL

        redis = await cls.get_redis()

        # 有 track_id 时用精确跟踪去重
        if track_id != -1:
            key = f"alarm:{stream_id}:{class_name}:{track_id}"
            try:
                was_set = await redis.set(key, "1", nx=True, ex=ttl)
                return was_set
            except Exception:
                return True

        # 无 track_id 时，用距离去重
        if position is not None:
            prefix = f"alarm:{stream_id}:{class_name}"
            # 查找该流+类型的所有活跃告警 key
            try:
                keys = []
                async for k in redis.scan_iter(match=f"{prefix}:*", count=50):
                    keys.append(k)

                # 检查是否有足够近的告警
                for k in keys:
                    val = await redis.get(k)
                    if val and val.startswith("pos:"):
                        # 解析上次告警位置
                        try:
                            old_x, old_y = map(int, val.split(":")[1].split(","))
                            dist = ((position[0] - old_x) ** 2 + (position[1] - old_y) ** 2) ** 0.5
                            if dist < 50:  # 50 像素内视为同一目标
                                return False
                        except (ValueError, IndexError):
                            continue

                # 没有近距离告警，触发新告警
                pos_key = f"{prefix}:pos:{position[0]},{position[1]}"
                await redis.set(pos_key, f"pos:{position[0]},{position[1]}", ex=ttl)
                return True
            except Exception:
                return True

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
