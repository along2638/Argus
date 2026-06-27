from typing import List, Optional

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

router = APIRouter(prefix="/auth", tags=["认证"])


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
        token = request.cookies.get("session_token")
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
async def api_login(body: LoginRequest, response: Response):
    result = await authenticate(body.username, body.password)
    if not result["success"]:
        raise HTTPException(status_code=401, detail=result["message"])
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
async def api_register(body: RegisterRequest):
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
    # 提取 token 并加入黑名单
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    if not token:
        token = request.cookies.get("token") if request else None
    if token:
        await logout_token(token)
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
    ok = await reset_password(user_id, body.new_password)
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
    return {"success": True, "message": "已删除"}
