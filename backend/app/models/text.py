"""文本栏目模型：每个用户可以有多条独立的文本（与「云剪切板」分开）"""
from datetime import datetime

from sqlalchemy import BigInteger, String, Integer, ForeignKey, DateTime, Index, func
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class Text(Base):
    __tablename__ = "texts"
    # (user_id, access_code)：按「属主 + 访问码」查快速访问内容；user_id 在最左，也满足外键对索引的要求
    __table_args__ = (Index("ix_texts_user_access_code", "user_id", "access_code"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    # 与云剪切板相同：应用层上限 8MB（schemas/clipboard.py），列容量 16MB
    content: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    # 每次保存加 1：保存时带上读到的版本号，不一致说明已在别处改过（冲突检测）
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    # 快速访问码（小写存储），NULL 表示没有设置
    access_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    access_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
