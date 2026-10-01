"""系统设置读取：数据库 settings 表优先，缺省回落 .env 默认值"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Setting


async def _get_value(db: AsyncSession, key: str) -> str | None:
    result = await db.execute(select(Setting.value).where(Setting.key == key))
    return result.scalar_one_or_none()


async def get_registration_enabled(db: AsyncSession) -> bool:
    """是否开放注册（未配置时默认开放，仍需有效邀请码）"""
    value = await _get_value(db, "registration_enabled")
    return value is None or value.lower() == "true"


async def get_default_quota_bytes(db: AsyncSession) -> int:
    """新用户默认配额"""
    value = await _get_value(db, "default_quota_bytes")
    try:
        return int(value) if value is not None else settings.DEFAULT_QUOTA_BYTES
    except ValueError:
        return settings.DEFAULT_QUOTA_BYTES
