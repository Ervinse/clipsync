"""剪贴板模型：当前文本 + 历史版本"""
from datetime import datetime

from sqlalchemy import BigInteger, String, Integer, ForeignKey, DateTime, func
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class Clipboard(Base):
    # 表名 clipboard，一人一条，user_id 即主键
    __tablename__ = "clipboard"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), primary_key=True)
    # MEDIUMTEXT（16MB）：容量大于 schemas/clipboard.py 的应用层上限（4MB），TEXT 只有 64KB 装不下
    content: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    # 每次内容变化加 1（保存相同内容不加），用于保存冲突检测；没有记录时视为 0
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    # 快速访问码（小写存储），NULL 表示没有设置
    access_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    access_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ClipboardHistory(Base):
    __tablename__ = "clipboard_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    content: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
