"""时间工具：统一 UTC。数据库 DateTime 列为 naive，约定一律存 naive UTC，精度到秒。"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    """
    当前 UTC 时间（naive，精度到秒），可直接与数据库 DateTime 列比较。
    DATETIME(0) 列会把小数秒四舍五入，这里先截掉，接口响应和推送里的时间与之后读到的一致。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def to_naive_utc(value: datetime | None) -> datetime | None:
    """
    带时区的时间转为 naive UTC；naive 时间视为已是 UTC；小数秒截掉（原因同 utcnow：
    9999-12-31 23:59:59.6 会被 MySQL 进位到 10000 年而报错）。
    换算后超出 datetime 能表示的范围（如 9999-12-31T23:59:59-05:00）时抛 ValueError，由调用方转成 400。
    """
    if value is None:
        return None
    if value.tzinfo is not None:
        try:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        except OverflowError:
            raise ValueError("时间超出可表示的范围")
    return value.replace(microsecond=0)
