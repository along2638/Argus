from typing import List, Optional
from datetime import datetime

import asyncio
from fastapi import APIRouter, HTTPException, Request, Header, Response
from pydantic import BaseModel, Field

from app.config import settings
from app.services.auth_service import (
    authenticate, register, get_current_user, logout_token, list_users,
    update_user_role, toggle_user_active, reset_password, delete_user,
    has_permission, Permission,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def log_operation(action: str, username: str = None, detail: str = None, request: Request = None):
    """记录操作日志到数据库"""
    try:
        from app.db import async_session
        from app.models.operation_log import OperationLog
        ip = request.client.host if request and request.client else None
        async with async_session() as session:
            session.add(OperationLog(
                action=action,
                username=username,
                detail=detail,
                ip_address=ip,
                create_by=username,
            ))
            await session.commit()
    except Exception as e:
        logger.warning("log_operation_failed", error=str(e))

router = APIRouter(prefix="/auth", tags=["认证"])

_config_init_lock = asyncio.Lock()


# ── Request/Response Models ──

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)
    display_name: str = Field(None, max_length=128)
    role: str = Field("viewer")


class RoleUpdateRequest(BaseModel):
    role: str = Field(..., description="admin/operator/annotator/viewer")


class PasswordResetRequest(BaseModel):
    new_password: str = Field(..., min_length=6, max_length=128)


# ── Helper ──

def _extract_token(authorization: Optional[str] = None, request: Request = None) -> Optional[str]:
    # 1. Authorization header: Bearer <token>
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    # 2. Cookie fallback (for browser pages)
    if request:
        token = request.cookies.get("token")
        if token:
            return token
    return None


async def _get_current_user(authorization: Optional[str] = None, request: Request = None) -> dict:
    token = _extract_token(authorization, request)
    user = await get_current_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="未登录或 token 已过期")
    return user


# ── Public Endpoints ──

@router.post("/login")
async def api_login(body: LoginRequest, response: Response, request: Request = None):
    # Rate limit: 5 login attempts per minute per IP
    ip = request.client.host if request and request.client else "unknown"
    from app.core.rate_limiter import RateLimiter
    allowed, retry_after = await RateLimiter.is_allowed(f"login:{ip}", max_requests=5, window_seconds=60)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"登录尝试过于频繁，请 {retry_after} 秒后重试",
            headers={"Retry-After": str(retry_after)},
        )

    result = await authenticate(body.username, body.password)
    if not result["success"]:
        raise HTTPException(status_code=401, detail=result["message"])
    await log_operation("login", body.username, "登录成功", request)
    # Set JWT as HttpOnly cookie for page navigation
    response.set_cookie(
        key="token",
        value=result["token"],
        max_age=settings.JWT_EXPIRE_MINUTES * 60,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return result


@router.post("/register")
async def api_register(body: RegisterRequest, request: Request = None):
    # Rate limit: 3 register attempts per minute per IP
    ip = request.client.host if request and request.client else "unknown"
    from app.core.rate_limiter import RateLimiter
    allowed, retry_after = await RateLimiter.is_allowed(f"register:{ip}", max_requests=3, window_seconds=60)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"注册尝试过于频繁，请 {retry_after} 秒后重试",
            headers={"Retry-After": str(retry_after)},
        )

    # 自注册强制为 viewer 角色，防止权限提升
    result = await register(body.username, body.password, body.display_name, "viewer")
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


# ── Auth-required Endpoints ──

@router.get("/me")
async def api_me(authorization: Optional[str] = Header(None), request: Request = None):
    user = await _get_current_user(authorization, request)
    return {"success": True, "user": user}


@router.post("/logout")
async def api_logout(response: Response, authorization: Optional[str] = Header(None), request: Request = None):
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    if not token:
        token = request.cookies.get("token") if request else None
    if token:
        await logout_token(token)
    user = getattr(request.state, "user", {}) if request else {}
    await log_operation("logout", user.get("username"), "退出登录", request)
    response.delete_cookie("token")
    return {"success": True, "message": "已退出登录"}


# ── User Management (admin only) ──

@router.get("/users")
async def api_list_users(authorization: Optional[str] = Header(None), request: Request = None):
    user = await _get_current_user(authorization, request)
    if not has_permission(user["role"], Permission.MANAGE_USER):
        raise HTTPException(status_code=403, detail="权限不足")
    users = await list_users()
    return {"success": True, "users": users}


@router.put("/users/{user_id}/role")
async def api_update_role(user_id: int, body: RoleUpdateRequest,
                          authorization: Optional[str] = Header(None), request: Request = None):
    user = await _get_current_user(authorization, request)
    if not has_permission(user["role"], Permission.ADMIN):
        raise HTTPException(status_code=403, detail="权限不足")
    if body.role not in ("admin", "operator", "annotator", "viewer"):
        raise HTTPException(status_code=400, detail="无效的角色")
    ok = await update_user_role(user_id, body.role)
    if not ok:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"success": True, "message": f"已更新为 {body.role}"}


@router.post("/users/{user_id}/toggle")
async def api_toggle_user(user_id: int,
                          authorization: Optional[str] = Header(None), request: Request = None):
    user = await _get_current_user(authorization, request)
    if not has_permission(user["role"], Permission.ADMIN):
        raise HTTPException(status_code=403, detail="权限不足")
    if user["id"] == user_id:
        raise HTTPException(status_code=400, detail="不能禁用自己的账号")
    ok = await toggle_user_active(user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"success": True}


@router.post("/users/{user_id}/reset-password")
async def api_reset_password(user_id: int, body: PasswordResetRequest,
                             authorization: Optional[str] = Header(None), request: Request = None):
    user = await _get_current_user(authorization, request)
    if not has_permission(user["role"], Permission.ADMIN):
        raise HTTPException(status_code=403, detail="权限不足")
    try:
        ok = await reset_password(user_id, body.new_password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"success": True, "message": "密码已重置"}


@router.delete("/users/{user_id}")
async def api_delete_user(user_id: int,
                          authorization: Optional[str] = Header(None), request: Request = None):
    user = await _get_current_user(authorization, request)
    if not has_permission(user["role"], Permission.ADMIN):
        raise HTTPException(status_code=403, detail="权限不足")
    if user["id"] == user_id:
        raise HTTPException(status_code=400, detail="不能删除自己")
    ok = await delete_user(user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="用户不存在")
    await log_operation("delete_user", user["username"], f"删除用户 ID={user_id}", request)
    return {"success": True, "message": "已删除"}


@router.post("/change-password")
async def api_change_password(body: PasswordResetRequest,
                               authorization: Optional[str] = Header(None), request: Request = None):
    """当前用户修改自己的密码"""
    user = await _get_current_user(authorization, request)
    try:
        ok = await reset_password(user["id"], body.new_password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=400, detail="修改失败")
    await log_operation("change_password", user["username"], "修改密码", request)
    return {"success": True, "message": "密码已修改"}


@router.get("/sessions")
async def api_list_sessions(authorization: Optional[str] = Header(None), request: Request = None):
    """查看当前用户的会话信息"""
    user = await _get_current_user(authorization, request)
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    if not token and request:
        token = request.cookies.get("token")

    session_info = {
        "user_id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "permissions": user.get("permissions", []),
    }

    # Decode token to get expiry
    if token:
        from app.services.auth_service import decode_access_token
        payload = decode_access_token(token)
        if payload and payload.get("exp"):
            from datetime import datetime, timezone
            exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
            session_info["expires_at"] = exp.isoformat()

    return {"success": True, "sessions": [session_info]}


@router.get("/logs")
async def api_list_logs(limit: int = 100, authorization: Optional[str] = Header(None), request: Request = None):
    user = await _get_current_user(authorization, request)
    if not has_permission(user["role"], Permission.MANAGE_USER):
        raise HTTPException(status_code=403, detail="权限不足")
    try:
        from app.db import async_session
        from app.models.operation_log import OperationLog
        from sqlalchemy import select
        async with async_session() as session:
            result = await session.execute(
                select(OperationLog).order_by(OperationLog.create_time.desc()).limit(limit)
            )
            logs = [
                {"id": r.id, "action": r.action, "username": r.username,
                 "detail": r.detail, "ip_address": r.ip_address,
                 "create_time": str(r.create_time) if r.create_time else None}
                for r in result.scalars().all()
            ]
        return {"success": True, "logs": logs}
    except Exception as e:
        return {"success": False, "logs": [], "detail": str(e)}


# ── System Config ──

@router.get("/config")
async def api_get_config(authorization: Optional[str] = Header(None), request: Request = None):
    user = await _get_current_user(authorization, request)
    try:
        from app.db import async_session
        from app.models.system_config import SystemConfig
        from sqlalchemy import select
        async with async_session() as session:
            result = await session.execute(select(SystemConfig).order_by(SystemConfig.id))
            configs = [
                {"key": r.config_key, "value": r.config_value, "type": r.config_type, "description": r.description}
                for r in result.scalars().all()
            ]
        if not configs:
            async with _config_init_lock:
                # Double-check after acquiring lock
                async with async_session() as session:
                    result = await session.execute(select(SystemConfig).order_by(SystemConfig.id))
                    configs = [
                        {"key": r.config_key, "value": r.config_value, "type": r.config_type, "description": r.description}
                        for r in result.scalars().all()
                    ]
                if not configs:
                    await _init_default_config()
                    async with async_session() as session:
                        result = await session.execute(select(SystemConfig).order_by(SystemConfig.id))
                        configs = [
                            {"key": r.config_key, "value": r.config_value, "type": r.config_type, "description": r.description}
                            for r in result.scalars().all()
                        ]
        return {"success": True, "configs": configs}
    except Exception as e:
        return {"success": False, "configs": [], "detail": str(e)}


@router.put("/config")
async def api_update_config(body: dict, authorization: Optional[str] = Header(None), request: Request = None):
    user = await _get_current_user(authorization, request)
    if not has_permission(user["role"], Permission.ADMIN):
        raise HTTPException(status_code=403, detail="仅管理员可修改配置")
    try:
        from app.db import async_session
        from app.models.system_config import SystemConfig
        from sqlalchemy import select
        username = user.get("username")
        updates = body.get("configs", [])
        async with async_session() as session:
            for item in updates:
                key = item.get("key")
                value = item.get("value")
                if not key or value is None:
                    continue
                result = await session.execute(select(SystemConfig).where(SystemConfig.config_key == key))
                cfg = result.scalar_one_or_none()
                if cfg:
                    old_val = cfg.config_value
                    cfg.config_value = str(value)
                    cfg.update_by = username
            await session.commit()
        changed_keys = [item.get("key") for item in updates if item.get("key") and item.get("value") is not None]
        await log_operation("update_config", username, f"修改配置: {', '.join(changed_keys)}", request)
        return {"success": True, "message": "配置已更新"}
    except Exception as e:
        return {"success": False, "detail": str(e)}


async def _init_default_config():
    """初始化默认系统配置"""
    from app.db import async_session
    from app.models.system_config import SystemConfig
    from sqlalchemy import select
    defaults = [
        ("CONFIDENCE_THRESHOLD", "0.3", "float", "通用检测置信度阈值"),
        ("FIRE_SMOKE_CONFIDENCE_THRESHOLD", "0.01", "float", "火灾烟雾检测置信度阈值"),
        ("ALARM_COOLDOWN_TTL", "30", "int", "告警冷却时间（秒）"),
        ("MAX_CONCURRENT_STREAMS", "10", "int", "最大并发流数"),
        ("WEBHOOK_URL", "", "string", "告警推送 Webhook 地址"),
        ("WEBHOOK_ENABLED", "false", "bool", "是否启用告警推送"),
    ]
    async with async_session() as session:
        for key, value, ctype, desc in defaults:
            exists = await session.execute(select(SystemConfig).where(SystemConfig.config_key == key))
            if not exists.scalar_one_or_none():
                session.add(SystemConfig(config_key=key, config_value=value, config_type=ctype, description=desc))
        # 标注类别配置
        exists = await session.execute(select(SystemConfig).where(SystemConfig.config_key == "ANNOTATION_CLASSES"))
        if not exists.scalar_one_or_none():
            session.add(SystemConfig(
                config_key="ANNOTATION_CLASSES",
                config_value='[{"id":0,"name":"fire"},{"id":1,"name":"smoke"}]',
                config_type="json",
                description="标注类别列表 JSON 格式",
            ))
        await session.commit()


# ── Training Records ──

@router.get("/training")
async def api_list_training(limit: int = 50, authorization: Optional[str] = Header(None), request: Request = None):
    user = await _get_current_user(authorization, request)
    try:
        from app.db import async_session
        from app.models.training_record import TrainingRecord
        from sqlalchemy import select
        import os, glob, yaml

        async with async_session() as session:
            result = await session.execute(
                select(TrainingRecord).order_by(TrainingRecord.create_time.desc()).limit(limit)
            )
            records = [
                {"id": r.id, "model_name": r.model_name, "dataset_name": r.dataset_name,
                 "epochs": r.epochs, "batch_size": r.batch_size, "img_size": r.img_size,
                 "best_map50": r.best_map50, "best_map50_95": r.best_map50_95,
                 "model_path": r.model_path, "status": r.status,
                 "started_at": str(r.started_at) if r.started_at else None,
                 "finished_at": str(r.finished_at) if r.finished_at else None,
                 "create_time": str(r.create_time) if r.create_time else None}
                for r in result.scalars().all()
            ]

        # 自动扫描 runs/ 目录补充训练记录
        runs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "runs", "detect")
        if os.path.exists(runs_dir):
            existing_names = {r["model_name"] for r in records}
            for name in os.listdir(runs_dir):
                if name in existing_names:
                    continue
                run_path = os.path.join(runs_dir, name)
                if not os.path.isdir(run_path):
                    continue
                # 尝试读取 results.csv
                csv_path = os.path.join(run_path, "results.csv")
                best_map50 = None
                best_map50_95 = None
                if os.path.exists(csv_path):
                    try:
                        with open(csv_path) as f:
                            lines = f.readlines()
                            if len(lines) > 1:
                                last = lines[-1].strip().split(",")
                                # results.csv columns: epoch, box_loss, cls_loss, dfl_loss, ...
                                # mAP50 is typically column index 6, mAP50-95 is column index 7
                                if len(last) > 7:
                                    best_map50 = float(last[6]) if last[6] else None
                                    best_map50_95 = float(last[7]) if last[7] else None
                    except Exception:
                        pass
                records.append({
                    "id": None, "model_name": name, "dataset_name": "-",
                    "epochs": None, "batch_size": None, "img_size": None,
                    "best_map50": best_map50, "best_map50_95": best_map50_95,
                    "model_path": run_path, "status": "completed",
                    "started_at": None, "finished_at": None, "create_time": None,
                })

        return {"success": True, "records": records}
    except Exception as e:
        return {"success": False, "records": [], "detail": str(e)}


@router.post("/training")
async def api_add_training(body: dict, authorization: Optional[str] = Header(None), request: Request = None):
    user = await _get_current_user(authorization, request)
    if not has_permission(user["role"], Permission.MANAGE_USER):
        raise HTTPException(status_code=403, detail="权限不足")
    try:
        from app.db import async_session
        from app.models.training_record import TrainingRecord
        async with async_session() as session:
            record = TrainingRecord(
                model_name=body.get("model_name", ""),
                dataset_name=body.get("dataset_name"),
                epochs=body.get("epochs"),
                batch_size=body.get("batch_size"),
                img_size=body.get("img_size"),
                best_map50=body.get("best_map50"),
                best_map50_95=body.get("best_map50_95"),
                model_path=body.get("model_path"),
                status=body.get("status", "pending"),
                create_by=user.get("username"),
            )
            session.add(record)
            await session.commit()
        await log_operation("add_training", user.get("username"), f"新增训练记录: {body.get('model_name')}", request)
        return {"success": True, "message": "训练记录已添加"}
    except Exception as e:
        return {"success": False, "detail": str(e)}


@router.put("/training/{record_id}")
async def api_update_training(record_id: int, body: dict, authorization: Optional[str] = Header(None), request: Request = None):
    user = await _get_current_user(authorization, request)
    if not has_permission(user["role"], Permission.MANAGE_USER):
        raise HTTPException(status_code=403, detail="权限不足")
    try:
        from app.db import async_session
        from app.models.training_record import TrainingRecord
        from sqlalchemy import select
        async with async_session() as session:
            result = await session.execute(select(TrainingRecord).where(TrainingRecord.id == record_id))
            record = result.scalar_one_or_none()
            if not record:
                return {"success": False, "detail": "记录不存在"}
            for field in ["model_name", "dataset_name", "epochs", "batch_size", "img_size",
                          "best_map50", "best_map50_95", "model_path", "status"]:
                if field in body and body[field] is not None:
                    setattr(record, field, body[field])
            record.update_by = user.get("username")
            await session.commit()
        await log_operation("update_training", user.get("username"), f"更新训练记录 #{record_id}", request)
        return {"success": True, "message": "训练记录已更新"}
    except Exception as e:
        return {"success": False, "detail": str(e)}


@router.delete("/training/{record_id}")
async def api_delete_training(record_id: int, authorization: Optional[str] = Header(None), request: Request = None):
    user = await _get_current_user(authorization, request)
    if not has_permission(user["role"], Permission.MANAGE_USER):
        raise HTTPException(status_code=403, detail="权限不足")
    try:
        from app.db import async_session
        from app.models.training_record import TrainingRecord
        from sqlalchemy import select
        async with async_session() as session:
            result = await session.execute(select(TrainingRecord).where(TrainingRecord.id == record_id))
            record = result.scalar_one_or_none()
            if not record:
                return {"success": False, "detail": "记录不存在"}
            await session.delete(record)
            await session.commit()
        await log_operation("delete_training", user.get("username"), f"删除训练记录 #{record_id}", request)
        return {"success": True, "message": "已删除"}
    except Exception as e:
        return {"success": False, "detail": str(e)}


# ── Datasets ──

@router.get("/datasets")
async def api_list_datasets(authorization: Optional[str] = Header(None), request: Request = None):
    user = await _get_current_user(authorization, request)
    try:
        from app.db import async_session
        from app.models.dataset import Dataset
        from sqlalchemy import select
        import os

        base_dir = os.path.dirname(os.path.dirname(__file__))

        async with async_session() as session:
            result = await session.execute(select(Dataset).order_by(Dataset.id))
            datasets = []
            for r in result.scalars().all():
                # 自动统计该数据集目录下的图片数量
                total = train = val = test = 0
                ds_dir = os.path.join(base_dir, "fire_yolo", r.name)
                for split in ["train", "val", "test"]:
                    img_dir = os.path.join(ds_dir, split, "images")
                    if os.path.isdir(img_dir):
                        count = len([f for f in os.listdir(img_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
                        if split == "train": train = count
                        elif split == "val": val = count
                        elif split == "test": test = count
                total = train + val + test

                # 如果数据集没有指定目录，扫描 fire_smoke_data 下的子目录
                if total == 0:
                    smoke_dir = os.path.join(base_dir, "fire_smoke_data")
                    if os.path.isdir(smoke_dir):
                        for sub in os.listdir(smoke_dir):
                            sub_path = os.path.join(smoke_dir, sub)
                            if os.path.isdir(sub_path) and sub not in ("to_annotate",):
                                count = len([f for f in os.listdir(sub_path) if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
                                if count > 0:
                                    total += count

                datasets.append({
                    "id": r.id, "name": r.name, "description": r.description,
                    "total_images": total or r.total_images, "train_count": train or r.train_count,
                    "val_count": val or r.val_count, "test_count": test or r.test_count,
                    "create_time": str(r.create_time) if r.create_time else None,
                })
        return {"success": True, "datasets": datasets}
    except Exception as e:
        return {"success": False, "datasets": [], "detail": str(e)}


@router.post("/datasets/{dataset_id}/scan")
async def api_scan_dataset(dataset_id: int, authorization: Optional[str] = Header(None), request: Request = None):
    """扫描数据集目录，自动统计图片数量"""
    user = await _get_current_user(authorization, request)
    try:
        from app.db import async_session
        from app.models.dataset import Dataset
        from sqlalchemy import select
        import os

        base_dir = os.path.dirname(os.path.dirname(__file__))
        async with async_session() as session:
            result = await session.execute(select(Dataset).where(Dataset.id == dataset_id))
            ds = result.scalar_one_or_none()
            if not ds:
                return {"success": False, "detail": "数据集不存在"}

            total = train = val = test = 0
            # 扫描 fire_yolo/{name}/ 目录
            ds_dir = os.path.join(base_dir, "fire_yolo", ds.name)
            for split in ["train", "val", "test"]:
                img_dir = os.path.join(ds_dir, split, "images")
                if os.path.isdir(img_dir):
                    count = len([f for f in os.listdir(img_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
                    if split == "train": train = count
                    elif split == "val": val = count
                    elif split == "test": test = count
            total = train + val + test

            # 如果没有子目录，扫描 fire_smoke_data
            if total == 0:
                smoke_dir = os.path.join(base_dir, "fire_smoke_data")
                if os.path.isdir(smoke_dir):
                    for sub in os.listdir(smoke_dir):
                        sub_path = os.path.join(smoke_dir, sub)
                        if os.path.isdir(sub_path) and sub not in ("to_annotate",):
                            count = len([f for f in os.listdir(sub_path) if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
                            if count > 0:
                                total += count

            ds.total_images = total
            ds.train_count = train
            ds.val_count = val
            ds.test_count = test
            ds.update_by = user.get("username")
            await session.commit()

        return {"success": True, "message": f"扫描完成：共 {total} 张图片", "total": total, "train": train, "val": val, "test": test}
    except Exception as e:
        return {"success": False, "detail": str(e)}


@router.get("/annotation-classes")
async def api_get_annotation_classes(authorization: Optional[str] = Header(None), request: Request = None):
    """获取标注类别列表"""
    try:
        from app.db import async_session
        from app.models.system_config import SystemConfig
        from sqlalchemy import select
        import json
        async with async_session() as session:
            result = await session.execute(
                select(SystemConfig).where(SystemConfig.config_key == "ANNOTATION_CLASSES")
            )
            cfg = result.scalar_one_or_none()
            if cfg and cfg.config_value:
                classes = json.loads(cfg.config_value)
            else:
                classes = [{"id": 0, "name": "fire"}, {"id": 1, "name": "smoke"}]
        return {"success": True, "classes": classes}
    except Exception as e:
        return {"success": True, "classes": [{"id": 0, "name": "fire"}, {"id": 1, "name": "smoke"}]}


@router.get("/backup")
async def api_backup(authorization: Optional[str] = Header(None), request: Request = None):
    """导出所有数据为 JSON（告警、检测、标注、数据集、训练记录）"""
    user = await _get_current_user(authorization, request)
    try:
        from app.db import async_session
        from app.models.alarm_record import AlarmRecord
        from app.models.detection_result import DetectionResult
        from app.models.detection_box import DetectionBox
        from app.models.annotation_image import AnnotationImage
        from app.models.annotation_box import AnnotationBox
        from app.models.dataset import Dataset
        from app.models.training_record import TrainingRecord
        from sqlalchemy import select

        async with async_session() as session:
            alarms = [{"id": r.id, "stream_url": r.stream_url, "stream_id": r.stream_id,
                        "alarm_type": r.alarm_type, "confidence": r.confidence,
                        "image_path": r.image_path, "class_name": r.class_name,
                        "detected_at": str(r.detected_at) if r.detected_at else None}
                       for r in (await session.execute(select(AlarmRecord))).scalars().all()]

            det_results = [{"id": r.id, "filename": r.filename, "model_name": r.model_name,
                            "detections_count": r.detections_count,
                            "detected_at": str(r.detected_at) if r.detected_at else None}
                           for r in (await session.execute(select(DetectionResult))).scalars().all()]

            ann_images = [{"id": r.id, "filename": r.filename, "is_annotated": r.is_annotated,
                           "box_count": r.box_count, "dataset_name": r.dataset_name}
                          for r in (await session.execute(select(AnnotationImage))).scalars().all()]

            datasets = [{"id": r.id, "name": r.name, "total_images": r.total_images}
                        for r in (await session.execute(select(Dataset))).scalars().all()]

            training = [{"id": r.id, "model_name": r.model_name, "status": r.status,
                         "best_map50": r.best_map50}
                        for r in (await session.execute(select(TrainingRecord))).scalars().all()]

        backup = {
            "version": "1.0",
            "exported_at": datetime.now().isoformat(),
            "alarm_records": alarms,
            "detection_results": det_results,
            "annotation_images": ann_images,
            "datasets": datasets,
            "training_records": training,
        }

        from fastapi.responses import JSONResponse
        return JSONResponse(
            content=backup,
            headers={"Content-Disposition": f"attachment; filename=argus_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"}
        )
    except Exception as e:
        return {"success": False, "detail": str(e)}


@router.post("/datasets")
async def api_add_dataset(body: dict, authorization: Optional[str] = Header(None), request: Request = None):
    user = await _get_current_user(authorization, request)
    if not has_permission(user["role"], Permission.MANAGE_USER):
        raise HTTPException(status_code=403, detail="权限不足")
    try:
        from app.db import async_session
        from app.models.dataset import Dataset
        from sqlalchemy import select
        async with async_session() as session:
            name = body.get("name", "").strip()
            if not name:
                return {"success": False, "detail": "数据集名称不能为空"}
            exists = await session.execute(select(Dataset.id).where(Dataset.name == name))
            if exists.scalar_one_or_none():
                return {"success": False, "detail": f"数据集 '{name}' 已存在"}
            ds = Dataset(
                name=name,
                description=body.get("description"),
                class_mapping=body.get("class_mapping", {}),
                create_by=user.get("username"),
            )
            session.add(ds)
            await session.commit()
        return {"success": True, "message": "数据集已创建"}
    except Exception as e:
        return {"success": False, "detail": str(e)}


@router.put("/datasets/{dataset_id}")
async def api_update_dataset(dataset_id: int, body: dict, authorization: Optional[str] = Header(None), request: Request = None):
    user = await _get_current_user(authorization, request)
    if not has_permission(user["role"], Permission.MANAGE_USER):
        raise HTTPException(status_code=403, detail="权限不足")
    try:
        from app.db import async_session
        from app.models.dataset import Dataset
        from sqlalchemy import select
        async with async_session() as session:
            result = await session.execute(select(Dataset).where(Dataset.id == dataset_id))
            ds = result.scalar_one_or_none()
            if not ds:
                return {"success": False, "detail": "数据集不存在"}
            for field in ["name", "description", "total_images", "train_count", "val_count", "test_count"]:
                if field in body and body[field] is not None:
                    setattr(ds, field, body[field])
            ds.update_by = user.get("username")
            await session.commit()
        return {"success": True, "message": "数据集已更新"}
    except Exception as e:
        return {"success": False, "detail": str(e)}


@router.delete("/datasets/{dataset_id}")
async def api_delete_dataset(dataset_id: int, authorization: Optional[str] = Header(None), request: Request = None):
    user = await _get_current_user(authorization, request)
    if not has_permission(user["role"], Permission.MANAGE_USER):
        raise HTTPException(status_code=403, detail="权限不足")
    try:
        from app.db import async_session
        from app.models.dataset import Dataset
        from sqlalchemy import select
        async with async_session() as session:
            result = await session.execute(select(Dataset).where(Dataset.id == dataset_id))
            ds = result.scalar_one_or_none()
            if not ds:
                return {"success": False, "detail": "数据集不存在"}
            await session.delete(ds)
            await session.commit()
        return {"success": True, "message": "已删除"}
    except Exception as e:
        return {"success": False, "detail": str(e)}
