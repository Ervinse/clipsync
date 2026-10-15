"""文件相关表模型：文件元数据与上传会话"""
from datetime import datetime
from sqlalchemy import BigInteger, String, Integer, ForeignKey, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from ..database import Base


class File(Base):
    """文件元数据表"""
    __tablename__ = "files"
    # 按「属主 + 访问码」查快速访问内容
    __table_args__ = (Index("ix_files_user_access_code", "user_id", "access_code"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(255), nullable=False)  # UUID，防穿越
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    # 快速访问码（小写存储），NULL 表示没有设置
    access_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    access_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class UploadSession(Base):
    """分片上传临时会话表"""
    __tablename__ = "upload_sessions"

    upload_id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    total_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_chunks: Mapped[int] = mapped_column(Integer, nullable=False)
    received_chunks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
