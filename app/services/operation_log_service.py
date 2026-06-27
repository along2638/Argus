"""操作日志服务 — 记录用户操作行为。"""

from typing import Optional
from datetime import datetime

from sqlalchemy import select, func, delete

from app.db import async_session
from app.models.operation_log import OperationLog
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def write_log(
    action: str,
    user_id: Optional[int] = None,
    username: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    detail: Optional[dict] = None,
    ip_address: Optional[str] = None,
) -> None:
    """写入一条操作日志。"""
    try:
        async with async_session() as session:
            log = OperationLog(
                user_id=user_id,
                username=username,
                action=action,
                target_type=target_type,
                target_id=str(target_id) if target_id is not None else None,
                detail=detail,
                ip_address=ip_address,
                create_by=username,
            )
            session.add(log)
            await session.commit()
    except Exception as e:
        logger.error("operation_log_write_error", action=action, error=str(e))


async def get_logs(
    limit: int = 100,
    offset: int = 0,
    action: Optional[str] = None,
    username: Optional[str] = None,
) -> dict:
    """查询操作日志列表。"""
    async with async_session() as session:
        stmt = select(OperationLog)
        count_stmt = select(func.count(OperationLog.id))

        if action:
            stmt = stmt.where(OperationLog.action == action)
            count_stmt = count_stmt.where(OperationLog.action == action)
        if username:
            stmt = stmt.where(OperationLog.username == username)
            count_stmt = count_stmt.where(OperationLog.username == username)

        total = await session.scalar(count_stmt)
        stmt = stmt.order_by(OperationLog.create_time.desc()).limit(limit).offset(offset)
        result = await session.execute(stmt)

        items = []
        for r in result.scalars().all():
            items.append({
                "id": r.id,
                "user_id": r.user_id,
                "username": r.username,
                "action": r.action,
                "target_type": r.target_type,
                "target_id": r.target_id,
                "detail": r.detail,
                "ip_address": r.ip_address,
                "create_time": str(r.create_time) if r.create_time else None,
            })

        return {"total": total or 0, "items": items}


async def delete_logs(before_date: Optional[str] = None) -> int:
    """清空操作日志。before_date 格式: YYYY-MM-DD。"""
    async with async_session() as session:
        if before_date:
            dt = datetime.strptime(before_date, "%Y-%m-%d")
            count_stmt = select(func.count(OperationLog.id)).where(OperationLog.create_time < dt)
            total = await session.scalar(count_stmt)
            await session.execute(delete(OperationLog).where(OperationLog.create_time < dt))
        else:
            total = await session.scalar(select(func.count(OperationLog.id)))
            await session.execute(delete(OperationLog))
        await session.commit()
        logger.info("operation_logs_deleted", count=total)
        return total or 0
