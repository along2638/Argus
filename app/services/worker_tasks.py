import asyncio
import json
from datetime import datetime
from typing import Optional
import urllib.parse

import aiomysql
import httpx
from arq import create_pool
from arq.connections import RedisSettings
from arq.jobs import Job

from app.config import settings
from app.services.database import db_service
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ARQ Redis settings from config
def get_redis_settings() -> RedisSettings:
    """Parse Redis URL and create RedisSettings."""
    from urllib.parse import urlparse, unquote

    parsed = urlparse(settings.REDIS_URL)

    # Extract password (URL decoded)
    password = unquote(parsed.password) if parsed.password else None

    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/") or 0),
        password=password,
    )


# Global ARQ pool
_arq_pool = None


async def get_arq_pool():
    """Get or create ARQ Redis pool."""
    global _arq_pool
    if _arq_pool is None:
        _arq_pool = await create_pool(get_redis_settings())
    return _arq_pool


async def close_arq_pool():
    """Close ARQ Redis pool."""
    global _arq_pool
    if _arq_pool is not None:
        try:
            await _arq_pool.close()
        except Exception:
            pass
        _arq_pool = None
        logger.info("arq_pool_closed")


async def enqueue_alarm_task(
    stream_url: str,
    stream_id: str,
    alarm_type: str,
    confidence: float,
    minio_key: str,
    track_id: int,
    class_name: str = "",
    severity: str = "normal",
) -> Optional[str]:
    """Enqueue an alarm save task to ARQ.

    Returns:
        Job ID if enqueued, None if failed.
    """
    try:
        pool = await get_arq_pool()
        job = await pool.enqueue_job(
            "save_alarm",
            stream_url,
            stream_id,
            alarm_type,
            confidence,
            minio_key,
            track_id,
            class_name,
            severity,
        )

        if job:
            logger.info(
                "alarm_task_enqueued",
                job_id=job.job_id,
                stream_id=stream_id,
                alarm_type=alarm_type,
            )
            return job.job_id
        else:
            logger.error("alarm_task_enqueue_failed", stream_id=stream_id)
            return None
    except Exception as e:
        logger.error("alarm_task_enqueue_error", error=str(e), stream_id=stream_id)
        return None


async def save_alarm(
    ctx,
    stream_url: str,
    stream_id: str,
    alarm_type: str,
    confidence: float,
    minio_key: str,
    track_id: int,
    class_name: str = "",
    severity: str = "normal",
) -> bool:
    """ARQ task: Save alarm record to MySQL.

    This function runs in the ARQ worker process.
    """
    # Create a new connection pool for this worker if needed
    if 'db_pool' not in ctx:
        parsed = urllib.parse.urlparse(settings.MYSQL_DSN.replace("mysql+aiomysql://", "mysql://"))
        password = urllib.parse.unquote(parsed.password) if parsed.password else None
        ctx['db_pool'] = await aiomysql.create_pool(
            host=parsed.hostname,
            port=parsed.port or 3306,
            user=parsed.username,
            password=password,
            db=parsed.path.lstrip("/"),
            minsize=1,
            maxsize=5,
            charset="utf8mb4",
            autocommit=True,
        )

    try:
        async with ctx['db_pool'].acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO alarm_record (stream_url, stream_id, alarm_type, confidence, image_path, track_id, class_name, severity)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (stream_url, stream_id, alarm_type, confidence, minio_key, track_id, class_name, severity),
                )
                alarm_id = cursor.lastrowid

            logger.info(
                "alarm_saved_to_db",
                alarm_id=alarm_id,
                stream_id=stream_id,
                alarm_type=alarm_type,
            )

            # 触发 Webhook 通知
            await _send_webhook(alarm_type, stream_id, confidence, class_name, alarm_id)

            return True
    except Exception as e:
        logger.error(
            "alarm_save_failed",
            error=str(e),
            stream_id=stream_id,
            alarm_type=alarm_type,
        )
        raise  # Let ARQ retry


async def check_queue_depth(ctx) -> None:
    """Periodic task to check ARQ queue depth."""
    try:
        pool = await get_arq_pool()
        # Get pending job count
        pending = await pool.zcard("arq:queue")

        if pending and pending > settings.ARQ_QUEUE_WARNING_THRESHOLD:
            logger.warning(
                "queue_depth_high",
                pending_jobs=pending,
                threshold=settings.ARQ_QUEUE_WARNING_THRESHOLD,
            )
        else:
            logger.debug("queue_depth_check", pending_jobs=pending or 0)
    except Exception as e:
        logger.error("queue_depth_check_error", error=str(e))


# ARQ Worker functions
async def _send_webhook(alarm_type: str, stream_id: str, confidence: float, class_name: str, alarm_id: int):
    """告警推送 Webhook（钉钉/企业微信）"""
    try:
        # 从数据库读取配置
        from app.db import async_session
        from app.models.system_config import SystemConfig
        from sqlalchemy import select
        async with async_session() as session:
            url_row = await session.execute(select(SystemConfig).where(SystemConfig.config_key == "WEBHOOK_URL"))
            enabled_row = await session.execute(select(SystemConfig).where(SystemConfig.config_key == "WEBHOOK_ENABLED"))
            webhook_url = url_row.scalar_one_or_none()
            enabled = enabled_row.scalar_one_or_none()

        if not enabled or enabled.config_value.lower() != "true" or not webhook_url or not webhook_url.config_value:
            return

        url = webhook_url.config_value.strip()
        type_names = {"helmet": "安全帽", "fire": "火灾", "intrusion": "入侵检测", "no-helmet": "未戴安全帽"}
        type_cn = type_names.get(alarm_type, alarm_type)

        # 钉钉 Webhook 格式
        if "oapi.dingtalk.com" in url:
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": "Argus 告警通知",
                    "text": f"### Argus 告警通知\n- **类型**: {type_cn}\n- **流**: {stream_id}\n- **置信度**: {confidence:.1%}\n- **类别**: {class_name}\n- **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                }
            }
        # 企业微信 Webhook 格式
        elif "qyapi.weixin.qq.com" in url:
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "content": f"### Argus 告警通知\n> 类型: <font color=\"warning\">{type_cn}</font>\n> 流: {stream_id}\n> 置信度: {confidence:.1%}\n> 类别: {class_name}\n> 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                }
            }
        else:
            # 通用 JSON 格式
            payload = {
                "event": "alarm",
                "alarm_type": alarm_type,
                "stream_id": stream_id,
                "confidence": confidence,
                "class_name": class_name,
                "alarm_id": alarm_id,
                "timestamp": datetime.now().isoformat(),
            }

        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json=payload)
            logger.info("webhook_sent", url=url[:50], alarm_type=alarm_type)

    except Exception as e:
        logger.warning("webhook_failed", error=str(e))


class WorkerSettings:
    """ARQ Worker configuration."""

    functions = [save_alarm]

    # Redis settings
    redis_settings = get_redis_settings()

    # Worker settings
    max_jobs = settings.ARQ_MAX_JOBS
    retry_jobs = True
    max_tries = 3
    retry_delay = 5  # seconds

    # Health check
    health_check_interval = 10

    # Queue name
    queue_name = "arq:queue"

    @staticmethod
    async def startup(ctx):
        """Worker startup hook."""
        logger.info("arq_worker_starting")
        # Initialize database connection pool
        await db_service.get_pool()
        logger.info("arq_worker_started")

    @staticmethod
    async def shutdown(ctx):
        """Worker shutdown hook."""
        logger.info("arq_worker_shutting_down")
        # 关闭 worker 进程独立创建的 db pool（避免泄漏）
        if 'db_pool' in ctx:
            try:
                await ctx['db_pool'].close()
            except Exception:
                pass
        await db_service.close()
        logger.info("arq_worker_stopped")
