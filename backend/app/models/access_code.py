"""快速访问码表模型"""
from datetime import datetime
import enum
from sqlalchemy import BigInteger, String, Boolean, ForeignKey, DateTime, Enum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from ..database import Base


class AccessCodeTargetType(str, enum.Enum):
    """访问码目标类型"""
    TEXT = "text"
    FILE = "file"


class AccessCode(Base):
    """快速访问码表"""
    __tablename__ = "access_codes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    target_type: Mapped[AccessCodeTargetType] = mapped_column(Enum(AccessCodeTargetType), nullable=False)
    file_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("files.id", ondelete="CASCADE"), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
