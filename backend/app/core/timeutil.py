"""时间工具：统一 UTC。数据库 DateTime 列为 naive，约定一律存 naive UTC。"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    """当前 UTC 时间（naive），可直接与数据库 DateTime 列比较"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_naive_utc(value: datetime | None) -> datetime | None:
    """
    带时区的时间转为 naive UTC；naive 时间视为已是 UTC。
    换算后超出 datetime 能表示的范围（如 9999-12-31T23:59:59-05:00）时抛 ValueError，由调用方转成 400。
    """
    if value is None or value.tzinfo is None:
        return value
    try:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    except OverflowError:
        raise ValueError("时间超出可表示的范围")
