"""统一权限装饰器 — 简化端点权限检查。"""

from functools import wraps
from fastapi import Request, HTTPException
from app.services.auth_service import has_permission, Permission


def _find_request(args, kwargs):
    """从参数中查找 Request 对象。"""
    for key in ("request", "req"):
        if key in kwargs and isinstance(kwargs[key], Request):
            return kwargs[key]
    for arg in args:
        if isinstance(arg, Request):
            return arg
    return None


def require_perm(perm: str):
    """权限装饰器，检查当前用户是否拥有指定权限。"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request = _find_request(args, kwargs)
            if request is None:
                return await func(*args, **kwargs)
            user = getattr(request.state, "user", None)
            if not user:
                raise HTTPException(status_code=401, detail="未登录")
            if not await has_permission(user.get("role", ""), perm):
                raise HTTPException(status_code=403, detail=f"权限不足，需要 {perm} 权限")
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def require_admin(func):
    """管理员权限装饰器。"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        request = _find_request(args, kwargs)
        if request is None:
            return await func(*args, **kwargs)
        user = getattr(request.state, "user", None)
        if not user:
            raise HTTPException(status_code=401, detail="未登录")
        if not await has_permission(user.get("role", ""), Permission.ADMIN):
            raise HTTPException(status_code=403, detail="权限不足，需要管理员角色")
        return await func(*args, **kwargs)
    return wrapper
