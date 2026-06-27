"""Alarm severity escalation — determine severity based on alarm frequency."""

from datetime import datetime, timedelta

from sqlalchemy import select, func

from app.config import settings
from app.db import async_session
from app.models.alarm_record import AlarmRecord
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
    window_start = datetime.now() - timedelta(seconds=settings.ALARM_ESCALATION_WINDOW)

    try:
        async with async_session() as session:
            count = await session.scalar(
                select(func.count(AlarmRecord.id)).where(
                    AlarmRecord.stream_id == stream_id,
                    AlarmRecord.alarm_type == alarm_type,
                    AlarmRecord.detected_at >= window_start,
                )
            ) or 0

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
