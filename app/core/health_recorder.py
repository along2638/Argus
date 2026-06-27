"""Background task — periodically record stream health snapshots."""

import asyncio
from datetime import datetime

from app.db import async_session
from app.models.stream_health import StreamHealth
from app.utils.logger import get_logger

logger = get_logger(__name__)

RECORD_INTERVAL = 60  # seconds


async def record_stream_health(stream_manager) -> None:
    """Periodically snapshot each active stream's health into the database."""
    while True:
        try:
            await asyncio.sleep(RECORD_INTERVAL)
            streams = stream_manager.get_streams_info()
            if not streams:
                continue

            async with async_session() as session:
                for info in streams:
                    session.add(StreamHealth(
                        stream_id=info.get("stream_id", ""),
                        status=info.get("status", "unknown"),
                        fps=info.get("fps", 0),
                        error_message=info.get("error_message", ""),
                    ))
                await session.commit()

            logger.debug("health_snapshots_recorded", count=len(streams))
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("health_recorder_error", error=str(e))
            await asyncio.sleep(RECORD_INTERVAL)
