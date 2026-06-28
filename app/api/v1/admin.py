"""系统管理 API — 操作日志、系统配置、仪表盘统计、告警导出。"""

import csv
import io
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func, text

from app.db import async_session
from app.models.operation_log import OperationLog
from app.models.system_config import SystemConfig
from app.models.alarm_record import AlarmRecord
from app.models.detection_result import DetectionResult
from app.models.training_record import TrainingRecord
from app.models.dataset import Dataset
from app.models.annotation_image import AnnotationImage
from app.models.sys_user import SysUser
from app.services import operation_log_service
from app.services.auth_service import has_permission, Permission
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["系统管理"])


# ── 权限检查辅助 ──

async def _require_admin(request: Request):
    user = getattr(request.state, "user", None)
    if not user or not await has_permission(user.get("role", ""), Permission.ADMIN):
        raise HTTPException(status_code=403, detail="权限不足，需要管理员角色")
    return user


def _require_auth(request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    return user


# ══════════════════════════════════════════
# 操作日志
# ══════════════════════════════════════════

@router.get("/logs", summary="查询操作日志")
async def get_operation_logs(
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    action: Optional[str] = None,
    username: Optional[str] = None,
):
    """查询操作日志列表，支持按操作类型和用户名筛选。"""
    _require_auth(request)
    return await operation_log_service.get_logs(limit=limit, offset=offset, action=action, username=username)


@router.delete("/logs", summary="清空操作日志")
async def clear_operation_logs(request: Request, before_date: Optional[str] = None):
    """清空操作日志（仅管理员）。可选 before_date 参数按日期筛选删除。"""
    await _require_admin(request)
    count = await operation_log_service.delete_logs(before_date=before_date)
    return {"success": True, "message": f"已删除 {count} 条日志"}


# ══════════════════════════════════════════
# 系统配置
# ══════════════════════════════════════════

class ConfigUpdateRequest(BaseModel):
    config_key: str = Field(..., min_length=1, max_length=128)
    config_value: str = Field(..., max_length=4096)
    config_type: str = Field("string", description="string/int/bool/json")
    description: Optional[str] = Field(None, max_length=512)


@router.get("/configs", summary="获取系统配置列表")
async def get_configs(request: Request):
    """获取所有系统配置项。"""
    _require_auth(request)
    async with async_session() as session:
        result = await session.execute(select(SystemConfig).order_by(SystemConfig.id))
        items = []
        for r in result.scalars().all():
            items.append({
                "id": r.id,
                "config_key": r.config_key,
                "config_value": r.config_value,
                "config_type": r.config_type,
                "description": r.description,
                "update_time": str(r.update_time) if r.update_time else None,
            })
    return {"total": len(items), "items": items}


@router.get("/configs/{config_key}", summary="获取单个配置")
async def get_config(config_key: str, request: Request):
    """根据 key 获取配置值。"""
    _require_auth(request)
    async with async_session() as session:
        result = await session.execute(select(SystemConfig).where(SystemConfig.config_key == config_key))
        cfg = result.scalar_one_or_none()
        if not cfg:
            raise HTTPException(status_code=404, detail="配置项不存在")
        return {
            "config_key": cfg.config_key,
            "config_value": cfg.config_value,
            "config_type": cfg.config_type,
            "description": cfg.description,
        }


@router.post("/configs", summary="新增/更新系统配置")
async def upsert_config(body: ConfigUpdateRequest, request: Request):
    """新增或更新系统配置项（仅管理员）。"""
    user = await _require_admin(request)
    async with async_session() as session:
        result = await session.execute(select(SystemConfig).where(SystemConfig.config_key == body.config_key))
        cfg = result.scalar_one_or_none()
        if cfg:
            cfg.config_value = body.config_value
            cfg.config_type = body.config_type
            cfg.description = body.description
            cfg.update_by = user.get("username")
        else:
            cfg = SystemConfig(
                config_key=body.config_key,
                config_value=body.config_value,
                config_type=body.config_type,
                description=body.description,
                create_by=user.get("username"),
            )
            session.add(cfg)
        await session.commit()

    await operation_log_service.write_log(
        action="config_update",
        user_id=user.get("id"),
        username=user.get("username"),
        target_type="system_config",
        target_id=body.config_key,
        detail={"config_key": body.config_key, "config_value": body.config_value},
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "message": f"配置 {body.config_key} 已保存"}


@router.delete("/configs/{config_key}", summary="删除系统配置")
async def delete_config(config_key: str, request: Request):
    """删除系统配置项（仅管理员）。"""
    user = await _require_admin(request)
    async with async_session() as session:
        result = await session.execute(select(SystemConfig).where(SystemConfig.config_key == config_key))
        cfg = result.scalar_one_or_none()
        if not cfg:
            raise HTTPException(status_code=404, detail="配置项不存在")
        await session.delete(cfg)
        await session.commit()

    await operation_log_service.write_log(
        action="config_delete",
        user_id=user.get("id"),
        username=user.get("username"),
        target_type="system_config",
        target_id=config_key,
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "message": f"配置 {config_key} 已删除"}


# ══════════════════════════════════════════
# 仪表盘统计
# ══════════════════════════════════════════

@router.get("/stats/dashboard", summary="仪表盘统计数据")
async def get_dashboard_stats(request: Request):
    """获取仪表盘统计数据：告警总数、今日告警、各类型分布、近7天趋势等。"""
    _require_auth(request)

    async with async_session() as session:
        # 告警总数
        total_alarms = await session.scalar(select(func.count(AlarmRecord.id))) or 0

        # 今日告警数
        today_alarms = await session.scalar(
            select(func.count(AlarmRecord.id)).where(func.date(AlarmRecord.detected_at) == func.curdate())
        ) or 0

        # 告警类型分布
        type_dist_result = await session.execute(
            select(AlarmRecord.alarm_type, func.count(AlarmRecord.id))
            .group_by(AlarmRecord.alarm_type)
        )
        alarm_type_distribution = {row[0]: row[1] for row in type_dist_result.all()}

        # 近 7 天每日告警趋势
        trend_result = await session.execute(text("""
            SELECT DATE(detected_at) as d, COUNT(*) as c
            FROM alarm_record
            WHERE detected_at >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
            GROUP BY DATE(detected_at)
            ORDER BY d
        """))
        alarm_trend = [{"date": str(row[0]), "count": row[1]} for row in trend_result.all()]

        # 检测总数
        total_detections = await session.scalar(select(func.count(DetectionResult.id))) or 0

        # 用户总数
        total_users = await session.scalar(select(func.count(SysUser.id))) or 0

        # 标注统计
        total_annotations = await session.scalar(select(func.count(AnnotationImage.id))) or 0
        annotated_count = await session.scalar(
            select(func.count(AnnotationImage.id)).where(AnnotationImage.is_annotated == True)
        ) or 0

        # 数据集数量
        total_datasets = await session.scalar(select(func.count(Dataset.id))) or 0

        # 训练记录统计
        total_trainings = await session.scalar(select(func.count(TrainingRecord.id))) or 0
        training_status_result = await session.execute(
            select(TrainingRecord.status, func.count(TrainingRecord.id))
            .group_by(TrainingRecord.status)
        )
        training_status_dist = {row[0]: row[1] for row in training_status_result.all()}

    return {
        "alarm": {
            "total": total_alarms,
            "today": today_alarms,
            "type_distribution": alarm_type_distribution,
            "trend_7d": alarm_trend,
        },
        "detection": {
            "total": total_detections,
        },
        "annotation": {
            "total": total_annotations,
            "completed": annotated_count,
        },
        "user": {
            "total": total_users,
        },
        "dataset": {
            "total": total_datasets,
        },
        "training": {
            "total": total_trainings,
            "status_distribution": training_status_dist,
        },
    }


# ══════════════════════════════════════════
# 告警记录导出 (CSV)
# ══════════════════════════════════════════

@router.get("/export/alarms", summary="导出告警记录为 CSV")
async def export_alarms_csv(
    request: Request,
    stream_id: Optional[str] = None,
    alarm_type: Optional[str] = None,
):
    """导出告警记录为 CSV 文件（仅管理员）。"""
    await _require_admin(request)

    async with async_session() as session:
        stmt = select(AlarmRecord)
        if stream_id:
            stmt = stmt.where(AlarmRecord.stream_id == stream_id)
        if alarm_type:
            stmt = stmt.where(AlarmRecord.alarm_type == alarm_type)
        stmt = stmt.order_by(AlarmRecord.detected_at.desc())
        result = await session.execute(stmt)
        alarms = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "流ID", "流地址", "告警类型", "类别名", "置信度", "TrackID", "检测时间", "图片路径"])
    for a in alarms:
        writer.writerow([
            a.id, a.stream_id, a.stream_url, a.alarm_type, a.class_name,
            f"{a.confidence:.4f}" if a.confidence else "",
            a.track_id if a.track_id is not None else "",
            str(a.detected_at) if a.detected_at else "",
            a.image_path or "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=alarm_records.csv"},
    )


# ══════════════════════════════════════════
# 训练记录管理
# ══════════════════════════════════════════

class TrainingRecordRequest(BaseModel):
    model_name: str = Field(..., max_length=64)
    dataset_name: Optional[str] = Field(None, max_length=128)
    epochs: Optional[int] = None
    batch_size: Optional[int] = None
    img_size: Optional[int] = None
    best_map50: Optional[float] = None
    best_map50_95: Optional[float] = None
    model_path: Optional[str] = None
    config: Optional[dict] = None
    status: str = Field("pending", description="pending/running/completed/failed")


@router.get("/trainings", summary="查询训练记录列表")
async def get_trainings(request: Request, limit: int = 50, offset: int = 0, status: Optional[str] = None):
    """查询训练记录列表。"""
    _require_auth(request)
    async with async_session() as session:
        stmt = select(TrainingRecord)
        count_stmt = select(func.count(TrainingRecord.id))
        if status:
            stmt = stmt.where(TrainingRecord.status == status)
            count_stmt = count_stmt.where(TrainingRecord.status == status)
        total = await session.scalar(count_stmt)
        stmt = stmt.order_by(TrainingRecord.create_time.desc()).limit(limit).offset(offset)
        result = await session.execute(stmt)
        items = []
        for r in result.scalars().all():
            items.append({
                "id": r.id,
                "model_name": r.model_name,
                "dataset_name": r.dataset_name,
                "epochs": r.epochs,
                "batch_size": r.batch_size,
                "img_size": r.img_size,
                "best_map50": r.best_map50,
                "best_map50_95": r.best_map50_95,
                "model_path": r.model_path,
                "config": r.config,
                "status": r.status,
                "started_at": str(r.started_at) if r.started_at else None,
                "finished_at": str(r.finished_at) if r.finished_at else None,
                "create_time": str(r.create_time) if r.create_time else None,
            })
    return {"total": total or 0, "items": items}


@router.post("/trainings", summary="新增训练记录")
async def create_training(body: TrainingRecordRequest, request: Request):
    """新增训练记录（仅管理员/操作员）。"""
    user = await _require_admin(request)
    async with async_session() as session:
        record = TrainingRecord(
            model_name=body.model_name,
            dataset_name=body.dataset_name,
            epochs=body.epochs,
            batch_size=body.batch_size,
            img_size=body.img_size,
            best_map50=body.best_map50,
            best_map50_95=body.best_map50_95,
            model_path=body.model_path,
            config=body.config,
            status=body.status,
            create_by=user.get("username"),
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)

    await operation_log_service.write_log(
        action="training_create",
        user_id=user.get("id"),
        username=user.get("username"),
        target_type="training_record",
        target_id=record.id,
        detail={"model_name": body.model_name},
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "id": record.id}


@router.put("/trainings/{training_id}", summary="更新训练记录")
async def update_training(training_id: int, body: TrainingRecordRequest, request: Request):
    """更新训练记录（仅管理员）。"""
    user = await _require_admin(request)
    async with async_session() as session:
        result = await session.execute(select(TrainingRecord).where(TrainingRecord.id == training_id))
        record = result.scalar_one_or_none()
        if not record:
            raise HTTPException(status_code=404, detail="训练记录不存在")
        record.model_name = body.model_name
        record.dataset_name = body.dataset_name
        record.epochs = body.epochs
        record.batch_size = body.batch_size
        record.img_size = body.img_size
        record.best_map50 = body.best_map50
        record.best_map50_95 = body.best_map50_95
        record.model_path = body.model_path
        record.config = body.config
        record.status = body.status
        record.update_by = user.get("username")
        await session.commit()
    return {"success": True, "message": "训练记录已更新"}


@router.delete("/trainings/{training_id}", summary="删除训练记录")
async def delete_training(training_id: int, request: Request):
    """删除训练记录（仅管理员）。"""
    user = await _require_admin(request)
    async with async_session() as session:
        result = await session.execute(select(TrainingRecord).where(TrainingRecord.id == training_id))
        record = result.scalar_one_or_none()
        if not record:
            raise HTTPException(status_code=404, detail="训练记录不存在")
        await session.delete(record)
        await session.commit()
    return {"success": True, "message": "训练记录已删除"}


# ══════════════════════════════════════════
# 数据集管理
# ══════════════════════════════════════════

class DatasetRequest(BaseModel):
    name: str = Field(..., max_length=128)
    description: Optional[str] = None
    class_mapping: dict = Field(default_factory=dict)
    total_images: int = 0
    train_count: int = 0
    val_count: int = 0
    test_count: int = 0


@router.get("/datasets", summary="查询数据集列表")
async def get_datasets(request: Request, limit: int = 50, offset: int = 0):
    """查询数据集列表。"""
    _require_auth(request)
    async with async_session() as session:
        total = await session.scalar(select(func.count(Dataset.id)))
        result = await session.execute(
            select(Dataset).order_by(Dataset.create_time.desc()).limit(limit).offset(offset)
        )
        items = []
        for r in result.scalars().all():
            items.append({
                "id": r.id,
                "name": r.name,
                "description": r.description,
                "class_mapping": r.class_mapping,
                "total_images": r.total_images,
                "train_count": r.train_count,
                "val_count": r.val_count,
                "test_count": r.test_count,
                "create_time": str(r.create_time) if r.create_time else None,
            })
    return {"total": total or 0, "items": items}


@router.post("/datasets", summary="新增数据集")
async def create_dataset(body: DatasetRequest, request: Request):
    """新增数据集配置（仅管理员）。"""
    user = await _require_admin(request)
    async with async_session() as session:
        exists = await session.execute(select(Dataset.id).where(Dataset.name == body.name))
        if exists.scalar_one_or_none():
            raise HTTPException(status_code=409, detail=f"数据集 '{body.name}' 已存在")
        dataset = Dataset(
            name=body.name,
            description=body.description,
            class_mapping=body.class_mapping,
            total_images=body.total_images,
            train_count=body.train_count,
            val_count=body.val_count,
            test_count=body.test_count,
            create_by=user.get("username"),
        )
        session.add(dataset)
        await session.commit()
        await session.refresh(dataset)

    await operation_log_service.write_log(
        action="dataset_create",
        user_id=user.get("id"),
        username=user.get("username"),
        target_type="dataset",
        target_id=dataset.id,
        detail={"name": body.name},
        ip_address=request.client.host if request.client else None,
    )
    return {"success": True, "id": dataset.id}


@router.put("/datasets/{dataset_id}", summary="更新数据集")
async def update_dataset(dataset_id: int, body: DatasetRequest, request: Request):
    """更新数据集配置（仅管理员）。"""
    user = await _require_admin(request)
    async with async_session() as session:
        result = await session.execute(select(Dataset).where(Dataset.id == dataset_id))
        dataset = result.scalar_one_or_none()
        if not dataset:
            raise HTTPException(status_code=404, detail="数据集不存在")
        dataset.name = body.name
        dataset.description = body.description
        dataset.class_mapping = body.class_mapping
        dataset.total_images = body.total_images
        dataset.train_count = body.train_count
        dataset.val_count = body.val_count
        dataset.test_count = body.test_count
        dataset.update_by = user.get("username")
        await session.commit()
    return {"success": True, "message": "数据集已更新"}


@router.delete("/datasets/{dataset_id}", summary="删除数据集")
async def delete_dataset(dataset_id: int, request: Request):
    """删除数据集（仅管理员）。"""
    user = await _require_admin(request)
    async with async_session() as session:
        result = await session.execute(select(Dataset).where(Dataset.id == dataset_id))
        dataset = result.scalar_one_or_none()
        if not dataset:
            raise HTTPException(status_code=404, detail="数据集不存在")
        await session.delete(dataset)
        await session.commit()
    return {"success": True, "message": "数据集已删除"}
