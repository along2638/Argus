from typing import Optional

import asyncpg

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class DatabaseService:
    """Async PostgreSQL connection pool manager."""

    _pool: Optional[asyncpg.Pool] = None

    @classmethod
    async def get_pool(cls) -> asyncpg.Pool:
        """Get or create the connection pool."""
        if cls._pool is None or cls._pool._closed:
            cls._pool = await asyncpg.create_pool(
                dsn=settings.PG_DSN,
                min_size=2,
                max_size=10,
                command_timeout=60,
            )
            logger.info("database_pool_created", min_size=2, max_size=10)
        return cls._pool

    @classmethod
    async def close(cls) -> None:
        """Close the connection pool."""
        if cls._pool and not cls._pool._closed:
            await cls._pool.close()
            cls._pool = None
            logger.info("database_pool_closed")

    @classmethod
    async def init_db(cls) -> None:
        """Initialize database tables and migrate schema if needed."""
        pool = await cls.get_pool()
        async with pool.acquire() as conn:
            # Create table if not exists (with full schema)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS alarm_records (
                    id BIGSERIAL PRIMARY KEY,
                    stream_url TEXT NOT NULL,
                    stream_id VARCHAR(64),
                    alarm_type VARCHAR(32) NOT NULL,
                    confidence FLOAT4 NOT NULL,
                    image_path TEXT NOT NULL,
                    track_id INTEGER,
                    detected_by TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    created_by TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            # Add missing columns for existing tables (migration)
            try:
                await conn.execute("""
                    ALTER TABLE alarm_records
                    ADD COLUMN IF NOT EXISTS stream_id VARCHAR(64)
                """)
                await conn.execute("""
                    ALTER TABLE alarm_records
                    ADD COLUMN IF NOT EXISTS track_id INTEGER
                """)
                await conn.execute("""
                    ALTER TABLE alarm_records
                    ADD COLUMN IF NOT EXISTS class_name VARCHAR(64)
                """)
            except Exception as e:
                logger.debug("columns_already_exist_or_migration_skipped", error=str(e))

            # Create indexes
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_alarm_detected_brin
                ON alarm_records USING brin(detected_by)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_alarm_stream_id
                ON alarm_records(stream_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_alarm_type
                ON alarm_records(alarm_type)
            """)
            logger.info("database_initialized")

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
        """Insert a new alarm record."""
        pool = await cls.get_pool()
        async with pool.acquire() as conn:
            record = await conn.fetchrow(
                """
                INSERT INTO alarm_records (stream_url, stream_id, alarm_type, confidence, image_path, track_id, class_name)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
                """,
                stream_url,
                stream_id,
                alarm_type,
                confidence,
                image_path,
                track_id,
                class_name,
            )
            logger.info(
                "alarm_inserted",
                alarm_id=record["id"],
                stream_id=stream_id,
                alarm_type=alarm_type,
                confidence=confidence,
            )
            return record["id"]

    @classmethod
    async def get_alarms(
        cls,
        stream_id: Optional[str] = None,
        alarm_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list:
        """Query alarm records with optional filters."""
        pool = await cls.get_pool()
        async with pool.acquire() as conn:
            query = "SELECT * FROM alarm_records WHERE 1=1"
            params = []
            param_idx = 1

            if stream_id:
                query += f" AND stream_id = ${param_idx}"
                params.append(stream_id)
                param_idx += 1

            if alarm_type:
                query += f" AND alarm_type = ${param_idx}"
                params.append(alarm_type)
                param_idx += 1

            query += f" ORDER BY detected_by DESC LIMIT ${param_idx} OFFSET ${param_idx + 1}"
            params.extend([limit, offset])

            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]

    @classmethod
    async def delete_alarm(cls, alarm_id: int) -> bool:
        """Delete an alarm record by ID."""
        pool = await cls.get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM alarm_records WHERE id = $1",
                alarm_id,
            )
            # result 会是 "DELETE 1" 或 "DELETE 0"
            deleted = result == "DELETE 1"
            if deleted:
                logger.info("alarm_deleted", alarm_id=alarm_id)
            return deleted

    @classmethod
    async def delete_all_alarms(cls) -> int:
        """Delete all alarm records. Returns number of deleted records."""
        pool = await cls.get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute("DELETE FROM alarm_records")
            # 解析删除数量
            count = int(result.split()[-1]) if result else 0
            logger.info("alarms_deleted_all", count=count)
            return count


# Singleton instance
db_service = DatabaseService()
