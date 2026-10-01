"""时间工具：统一 UTC。数据库 DateTime 列为 naive，约定一律存 naive UTC。"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    """当前 UTC 时间（naive），可直接与数据库 DateTime 列比较"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_naive_utc(value: datetime | None) -> datetime | None:
    """带时区的时间转为 naive UTC；naive 时间视为已是 UTC"""
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)
