"""Alarm severity escalation — determine severity based on alarm frequency.

使用 Redis Sorted Set 缓存告警频率，避免每次查 DB。
"""

import time

from app.config import settings
from app.core.alarm_dedup import alarm_dedup
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def compute_severity(stream_id: str, alarm_type: str) -> str:
    """Determine alarm severity based on recent frequency.

    Args:
        stream_id: The stream that triggered the alarm.
        alarm_type: The alarm type (helmet/fire/intrusion).

    Returns:
        Severity string: "normal", "important", or "critical".
    """
    try:
        redis = await alarm_dedup.get_redis()
        key = f"severity:{stream_id}:{alarm_type}"
        now = time.time()
        window_start = now - settings.ALARM_ESCALATION_WINDOW

        # 添加当前时间戳到 Sorted Set
        await redis.zadd(key, {str(now): now})
        # 清理窗口外的旧数据
        await redis.zremrangebyscore(key, 0, window_start)
        # 统计窗口内数量
        count = await redis.zcard(key)
        # 设置过期时间（窗口 + 60s 缓冲）
        await redis.expire(key, settings.ALARM_ESCALATION_WINDOW + 60)

        if count >= settings.ALARM_ESCALATION_CRITICAL:
            logger.warning(
                "alarm_escalated_critical",
                stream_id=stream_id,
                alarm_type=alarm_type,
                count=count,
            )
            return "critical"
        elif count >= settings.ALARM_ESCALATION_IMPORTANT:
            logger.info(
                "alarm_escalated_important",
                stream_id=stream_id,
                alarm_type=alarm_type,
                count=count,
            )
            return "important"

        return "normal"
    except Exception as e:
        logger.error("severity_compute_error", error=str(e))
        return "normal"
