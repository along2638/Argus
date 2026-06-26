import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
import redis.asyncio as aioredis
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import async_session
from app.models.sys_user import SysUser
from app.utils.logger import get_logger

logger = get_logger(__name__)

ITERATIONS = 260000

# ── Redis 连接 ──
_redis: Optional[aioredis.Redis] = None


async def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    return _redis


def _b64(data: bytes) -> str:
    from base64 import b64encode
    return b64encode(data).decode("ascii").rstrip("=")


def make_password(password: str, salt: str = None, iterations: int = ITERATIONS) -> str:
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${_b64(dk)}"


def check_password(password: str, password_hash: str) -> bool:
    try:
        algo, iterations, salt, stored_hash = password_hash.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations))
        return hmac.compare_digest(_b64(dk), stored_hash)
    except (ValueError, TypeError):
        return False


# ── JWT ──

def create_access_token(user_id: int, username: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return {
            "id": int(payload["sub"]),
            "username": payload["username"],
            "role": payload["role"],
            "exp": payload.get("exp"),
        }
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


async def is_token_blacklisted(token: str) -> bool:
    """检查 token 是否在 Redis 黑名单中"""
    try:
        r = await _get_redis()
        return await r.exists(f"jwt:blacklist:{token}") > 0
    except Exception:
        return False


async def blacklist_token(token: str, expire_seconds: int) -> None:
    """将 token 加入 Redis 黑名单，TTL = token 剩余有效期"""
    try:
        r = await _get_redis()
        await r.set(f"jwt:blacklist:{token}", "1", ex=expire_seconds)
        logger.info("token_blacklisted", expire_seconds=expire_seconds)
    except Exception as e:
        logger.error("token_blacklist_failed", error=str(e))


# ── Role / Permission ──

class Permission:
    VIEW_STREAM = "view_stream"
    MANAGE_STREAM = "manage_stream"
    VIEW_ALARM = "view_alarm"
    MANAGE_ALARM = "manage_alarm"
    ANNOTATE = "annotate"
    MANAGE_USER = "manage_user"
    ADMIN = "admin"


ROLE_PERMISSIONS = {
    "admin": [Permission.VIEW_STREAM, Permission.MANAGE_STREAM, Permission.VIEW_ALARM,
              Permission.MANAGE_ALARM, Permission.ANNOTATE, Permission.MANAGE_USER, Permission.ADMIN],
    "operator": [Permission.VIEW_STREAM, Permission.MANAGE_STREAM, Permission.VIEW_ALARM,
                 Permission.MANAGE_ALARM, Permission.ANNOTATE],
    "annotator": [Permission.VIEW_ALARM, Permission.ANNOTATE],
    "viewer": [Permission.VIEW_STREAM, Permission.VIEW_ALARM],
}


def has_permission(role: str, perm: str) -> bool:
    return perm in ROLE_PERMISSIONS.get(role, [])


def get_user_permissions(role: str) -> list:
    return ROLE_PERMISSIONS.get(role, [])


# ── Auth CRUD ──

async def register(username: str, password: str, display_name: str = None, role: str = "viewer") -> dict:
    async with async_session() as session:
        exists = await session.execute(select(SysUser.id).where(SysUser.username == username))
        if exists.scalar_one_or_none():
            return {"success": False, "message": "用户名已存在"}

        user = SysUser(
            username=username,
            password_hash=make_password(password),
            display_name=display_name or username,
            role=role,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        logger.info("user_registered", user_id=user.id, username=username, role=role)
        return {"success": True, "user": {"id": user.id, "username": user.username, "display_name": user.display_name, "role": user.role}}


async def authenticate(username: str, password: str) -> dict:
    async with async_session() as session:
        result = await session.execute(select(SysUser).where(SysUser.username == username))
        user = result.scalar_one_or_none()
        if not user:
            return {"success": False, "message": "用户名或密码错误"}
        if not user.is_active:
            return {"success": False, "message": "账号已被禁用"}
        if not check_password(password, user.password_hash):
            return {"success": False, "message": "用户名或密码错误"}

        user.last_login = func.now()
        await session.commit()

        token = create_access_token(user.id, user.username, user.role)
        logger.info("user_authenticated", user_id=user.id, username=username)
        return {
            "success": True,
            "token": token,
            "user": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "role": user.role,
                "permissions": get_user_permissions(user.role),
            },
        }


async def get_current_user(token: str) -> Optional[dict]:
    if not token:
        return None
    if await is_token_blacklisted(token):
        return None
    payload = decode_access_token(token)
    if not payload:
        return None

    try:
        async with async_session() as session:
            result = await session.execute(select(SysUser).where(SysUser.id == payload["id"]))
            user = result.scalar_one_or_none()
            if not user or not user.is_active:
                return None
            return {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "role": user.role,
                "permissions": get_user_permissions(user.role),
            }
    except Exception as e:
        logger.error("get_current_user_error", error=str(e), user_id=payload.get("sub"))
        return None


async def logout_token(token: str) -> None:
    """退出登录：将 token 加入黑名单"""
    if not token:
        return
    payload = decode_access_token(token)
    if not payload or not payload.get("exp"):
        return
    # 计算 token 剩余有效期
    expire_seconds = payload["exp"] - int(datetime.now(timezone.utc).timestamp())
    if expire_seconds > 0:
        await blacklist_token(token, expire_seconds)


async def create_default_admin():
    async with async_session() as session:
        exists = await session.execute(select(SysUser.id).where(SysUser.username == "admin"))
        if not exists.scalar_one_or_none():
            session.add(SysUser(username="admin", password_hash=make_password("admin123"), display_name="管理员", role="admin"))
            await session.commit()
            logger.info("default_admin_created")


async def list_users() -> list:
    async with async_session() as session:
        result = await session.execute(
            select(SysUser.id, SysUser.username, SysUser.display_name, SysUser.role,
                   SysUser.is_active, SysUser.last_login, SysUser.create_time)
            .order_by(SysUser.id)
        )
        return [{"id": r[0], "username": r[1], "display_name": r[2], "role": r[3],
                 "is_active": r[4], "last_login": r[5], "create_time": r[6]} for r in result.all()]


async def update_user_role(user_id: int, role: str) -> bool:
    async with async_session() as session:
        result = await session.execute(select(SysUser).where(SysUser.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            return False
        user.role = role
        await session.commit()
        return True


async def toggle_user_active(user_id: int) -> bool:
    async with async_session() as session:
        result = await session.execute(select(SysUser).where(SysUser.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            return False
        user.is_active = not user.is_active
        await session.commit()
        return True


async def reset_password(user_id: int, new_password: str) -> bool:
    async with async_session() as session:
        result = await session.execute(select(SysUser).where(SysUser.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            return False
        user.password_hash = make_password(new_password)
        await session.commit()
        return True


async def delete_user(user_id: int) -> bool:
    async with async_session() as session:
        result = await session.execute(select(SysUser).where(SysUser.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            return False
        await session.delete(user)
        await session.commit()
        return True
