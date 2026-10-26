"""系统设置读取：数据库 settings 表优先；新用户默认配额没配置时回落 .env 的 DEFAULT_QUOTA_BYTES，
开放注册与显示 GitHub 链接两个开关没配置时视为开启"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Setting
from ..schemas.admin import MAX_QUOTA_BYTES


async def _get_value(db: AsyncSession, key: str) -> str | None:
    result = await db.execute(select(Setting.value).where(Setting.key == key))
    return result.scalar_one_or_none()


async def get_registration_enabled(db: AsyncSession) -> bool:
    """是否开放注册（未配置时默认开放，仍需有效邀请码）"""
    value = await _get_value(db, "registration_enabled")
    return value is None or value.lower() == "true"


async def get_show_github_link(db: AsyncSession) -> bool:
    """登录后侧栏是否显示项目的 GitHub 链接（未配置时默认显示）"""
    value = await _get_value(db, "show_github_link")
    return value is None or value.lower() == "true"


async def get_default_quota_bytes(db: AsyncSession) -> int:
    """新用户默认配额"""
    value = await _get_value(db, "default_quota_bytes")
    if value is None:
        return settings.DEFAULT_QUOTA_BYTES
    try:
        quota = int(value)
    except ValueError:
        return settings.DEFAULT_QUOTA_BYTES
    # 库里的脏值（负数或超过 1TB）回落默认值，避免注册时写入 users.quota_bytes 越界
    if quota < 0 or quota > MAX_QUOTA_BYTES:
        return settings.DEFAULT_QUOTA_BYTES
    return quota
