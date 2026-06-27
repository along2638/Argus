from typing import Optional
import urllib.parse

import aiomysql

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class DatabaseService:
    """Async MySQL connection pool manager."""

    _pool: Optional[aiomysql.Pool] = None

    @classmethod
    async def get_pool(cls) -> aiomysql.Pool:
        if cls._pool is None or cls._pool.closed:
            parsed = urllib.parse.urlparse(settings.MYSQL_DSN.replace("mysql+aiomysql://", "mysql://"))
            password = urllib.parse.unquote(parsed.password) if parsed.password else None
            cls._pool = await aiomysql.create_pool(
                host=parsed.hostname,
                port=parsed.port or 3306,
                user=parsed.username,
                password=password,
                db=parsed.path.lstrip("/"),
                minsize=2,
                maxsize=10,
                charset="utf8mb4",
                autocommit=True,
            )
            logger.info("database_pool_created", minsize=2, maxsize=10)
        return cls._pool

    @classmethod
    async def close(cls) -> None:
        if cls._pool and not cls._pool.closed:
            cls._pool.close()
            await cls._pool.wait_closed()
            cls._pool = None
            logger.info("database_pool_closed")

    @classmethod
    async def init_db(cls) -> None:
        await cls.get_pool()
        logger.info("mysql_pool_ready")

    @classmethod
    async def insert_alarm(
        cls,
        stream_url: str,
        stream_id: str,
        alarm_type: str,
        confidence: float,
        image_path: str,
        track_id: Optional[int] = None,
        class_name: Optional[str] = None,
    ) -> int:
        from app.db import async_session
        from app.models.alarm_record import AlarmRecord

        async with async_session() as session:
            record = AlarmRecord(
                stream_url=stream_url, stream_id=stream_id, alarm_type=alarm_type,
                confidence=confidence, image_path=image_path, track_id=track_id, class_name=class_name,
            )
            session.add(record)
            await session.commit()
            await session.refresh(record)
            logger.info("alarm_inserted", alarm_id=record.id, stream_id=stream_id, alarm_type=alarm_type, confidence=confidence)
            return record.id

    @classmethod
    async def get_alarms(
        cls,
        stream_id: Optional[str] = None,
        alarm_type: Optional[str] = None,
        severity: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list:
        from app.db import async_session
        from app.models.alarm_record import AlarmRecord
        from sqlalchemy import select

        async with async_session() as session:
            stmt = select(AlarmRecord)
            if stream_id:
                stmt = stmt.where(AlarmRecord.stream_id == stream_id)
            if alarm_type:
                stmt = stmt.where(AlarmRecord.alarm_type == alarm_type)
            if severity:
                stmt = stmt.where(AlarmRecord.severity == severity)
            stmt = stmt.order_by(AlarmRecord.detected_at.desc()).limit(limit).offset(offset)
            result = await session.execute(stmt)
            return [
                {"id": r.id, "stream_url": r.stream_url, "stream_id": r.stream_id,
                 "alarm_type": r.alarm_type, "confidence": r.confidence, "image_path": r.image_path,
                 "track_id": r.track_id, "class_name": r.class_name, "severity": r.severity,
                 "detected_by": r.detected_at}
                for r in result.scalars().all()
            ]

    @classmethod
    async def delete_alarm(cls, alarm_id: int) -> bool:
        from app.db import async_session
        from app.models.alarm_record import AlarmRecord
        from sqlalchemy import select

        async with async_session() as session:
            result = await session.execute(select(AlarmRecord).where(AlarmRecord.id == alarm_id))
            record = result.scalar_one_or_none()
            if not record:
                return False
            await session.delete(record)
            await session.commit()
            logger.info("alarm_deleted", alarm_id=alarm_id)
            return True

    @classmethod
    async def delete_all_alarms(cls) -> int:
        from app.db import async_session
        from app.models.alarm_record import AlarmRecord
        from sqlalchemy import delete, func, select

        async with async_session() as session:
            result = await session.execute(select(func.count(AlarmRecord.id)))
            count = result.scalar()
            await session.execute(delete(AlarmRecord))
            await session.commit()
            logger.info("alarms_deleted_all", count=count)
            return count


# Singleton instance
db_service = DatabaseService()
