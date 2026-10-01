"""剪贴板模型：当前文本 + 历史版本"""
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, DateTime, func
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class Clipboard(Base):
    # 表名 clipboard，一人一条，user_id 即主键
    __tablename__ = "clipboard"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), primary_key=True)
    # MEDIUMTEXT（16MB）：与 schemas/clipboard.py 的 max_length 一致，TEXT 只有 64KB
    content: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class ClipboardHistory(Base):
    __tablename__ = "clipboard_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    content: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
