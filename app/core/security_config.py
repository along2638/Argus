"""安全参数配置 — 从 system_config 表读取，支持运行时修改。"""

from typing import Optional
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 默认值（从 Settings 或硬编码）
_DEFAULTS = {
    "login_rate_enabled": "true",
    "login_rate_max": str(5),
    "login_rate_window": str(60),
    "register_rate_enabled": "true",
    "register_rate_max": str(3),
    "register_rate_window": str(60),
    "jwt_expire_minutes": str(settings.JWT_EXPIRE_MINUTES),
    "password_min_length": str(8),
    "password_require_uppercase": "true",
    "password_require_lowercase": "true",
    "password_require_digit": "true",
    "password_require_special": "true",
    "session_timeout_minutes": str(60 * 24),
}

# 缓存
_cache: Optional[dict] = None


async def _load_from_db() -> dict:
    """从 system_config 表读取安全配置。"""
    try:
        from app.db import async_session
        from app.models.system_config import SystemConfig
        from sqlalchemy import select
        async with async_session() as session:
            result = await session.execute(
                select(SystemConfig).where(SystemConfig.config_key.in_(list(_DEFAULTS.keys())))
            )
            db_configs = {}
            for r in result.scalars().all():
                db_configs[r.config_key] = r.config_value
            return db_configs
    except Exception as e:
        logger.debug("security_config_db_fallback", error=str(e))
        return {}


async def get_security_config() -> dict:
    """获取安全配置（带缓存，5 分钟过期）。"""
    global _cache
    if _cache is not None:
        return _cache
    db_cfg = await _load_from_db()
    result = {}
    for key, default in _DEFAULTS.items():
        result[key] = db_cfg.get(key, default)
    _cache = result
    return result


async def get_security_value(key: str) -> str:
    """获取单个安全配置值。"""
    cfg = await get_security_config()
    return cfg.get(key, _DEFAULTS.get(key, ""))


def invalidate_security_cache():
    """清除缓存，下次读取时重新加载。"""
    global _cache
    _cache = None
