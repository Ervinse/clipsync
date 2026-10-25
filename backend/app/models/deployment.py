"""部署记录表模型：每部署一个新版本记一条，超管可写备注"""
from datetime import datetime
from sqlalchemy import BigInteger, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from ..database import Base


class Deployment(Base):
    """
    后端启动时登记：运行的版本与最近一条记录不同（版本号、提交号、分支、构建时间任一不同）才新增，
    同一版本重启不新增。deployed_at 是这个版本第一次启动的时间
    """
    __tablename__ = "deployments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    app_version: Mapped[str] = mapped_column(String(128), nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    branch: Mapped[str] = mapped_column(String(255), nullable=False)
    built_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deployed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    note: Mapped[str] = mapped_column(String(200), nullable=False, default="")
