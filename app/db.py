from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    settings.MYSQL_DSN,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    echo=False,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session


async def init_db():
    """Create all tables defined by Base.metadata."""
    from app.models.alarm_record import AlarmRecord
    from app.models.annotation_image import AnnotationImage
    from app.models.annotation_box import AnnotationBox
    from app.models.dataset import Dataset
    from app.models.sys_user import SysUser
    from app.models.detection_result import DetectionResult
    from app.models.detection_box import DetectionBox
    from app.models.stream_config import StreamConfig
    from app.models.stream_health import StreamHealth
    from app.models.operation_log import OperationLog
    from app.models.system_config import SystemConfig
    from app.models.training_record import TrainingRecord

    async with engine.connect() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.commit()
    logger.info("sqlalchemy_tables_created")


async def close_db():
    await engine.dispose()
    logger.info("sqlalchemy_engine_disposed")


def get_pool_status() -> dict:
    """获取连接池状态"""
    pool = engine.pool
    return {
        "pool_size": pool.size(),
        "checked_in": pool.checkedin(),
        "checked_out": pool.checkedout(),
        "overflow": pool.overflow(),
    }
