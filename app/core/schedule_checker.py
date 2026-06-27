"""Background task — check stream schedules and auto-start/stop streams."""

import asyncio
from datetime import datetime

from app.db import async_session
from app.models.stream_config import StreamConfig
from app.utils.logger import get_logger

from sqlalchemy import select

logger = get_logger(__name__)

CHECK_INTERVAL = 60  # seconds


def _matches_cron(expr: str, now: datetime) -> bool:
    """Simple cron matcher for 'minute hour day month weekday' format.

    Supports:
    - * (any)
    - N (exact value)
    - N-M (range)
    - N/S (step, e.g. */5)
    - N,M,O (list)
    """
    parts = expr.strip().split()
    if len(parts) != 5:
        return False

    fields = [now.minute, now.hour, now.day, now.month, now.isoweekday() % 7]

    for part, value in zip(parts, fields):
        if part == "*":
            continue
        if "/" in part:
            base, step = part.split("/", 1)
            step = int(step)
            if base == "*":
                if value % step != 0:
                    return False
            else:
                start = int(base)
                if (value - start) % step != 0 or value < start:
                    return False
        elif "-" in part:
            lo, hi = part.split("-", 1)
            if not (int(lo) <= value <= int(hi)):
                return False
        elif "," in part:
            if value not in [int(x) for x in part.split(",")]:
                return False
        else:
            if value != int(part):
                return False

    return True


async def check_schedules(stream_manager) -> None:
    """Periodically check stream schedules and auto-start/stop."""
    while True:
        try:
            await asyncio.sleep(CHECK_INTERVAL)
            now = datetime.now()

            async with async_session() as session:
                result = await session.execute(
                    select(StreamConfig).where(StreamConfig.schedule.isnot(None))
                )
                configs = result.scalars().all()

            for cfg in configs:
                should_run = _matches_cron(cfg.schedule, now)
                is_running = cfg.stream_id in stream_manager.stream_ids

                if should_run and not is_running:
                    try:
                        r = await stream_manager.start_stream(
                            stream_id=cfg.stream_id,
                            stream_url=cfg.stream_url,
                            validate=False,
                            alarm_types=cfg.alarm_types or ["helmet", "fire", "intrusion"],
                        )
                        if r["success"]:
                            logger.info("schedule_auto_start", stream_id=cfg.stream_id, schedule=cfg.schedule)
                    except Exception as e:
                        logger.error("schedule_auto_start_error", stream_id=cfg.stream_id, error=str(e))

                elif not should_run and is_running:
                    try:
                        await stream_manager.stop_stream(cfg.stream_id)
                        logger.info("schedule_auto_stop", stream_id=cfg.stream_id, schedule=cfg.schedule)
                    except Exception as e:
                        logger.error("schedule_auto_stop_error", stream_id=cfg.stream_id, error=str(e))

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("schedule_checker_error", error=str(e))
            await asyncio.sleep(CHECK_INTERVAL)
