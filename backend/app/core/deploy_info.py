"""部署信息：镜像构建信息 + 运行的版本号 + 进程启动时间 + 部署记录登记

- 提交号、分支、构建时间：build-release.ps1 打包时写成 BUILD_INFO 文件，随源码复制进镜像（Dockerfile 里只有
  COPY . .），镜像造好后不会再变；
  正式版本晋级不重新构建，所以版本号不在镜像里
- 版本号：运行时由 compose 把 .env 的 CLIPSYNC_TAG 传进来（settings.APP_VERSION）
- 开发环境没有 BUILD_INFO，各项为空
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Deployment
from .timeutil import utcnow

logger = logging.getLogger(__name__)

# 后端根目录下（容器里是 /app/BUILD_INFO）
BUILD_INFO_PATH = Path(__file__).resolve().parents[2] / "BUILD_INFO"

# 进程启动时间：计算已运行时长
STARTED_AT = utcnow()


@dataclass(frozen=True)
class BuildInfo:
    app_version: str
    commit_sha: str
    branch: str
    built_at: datetime | None


def read_build_file(path: Path = BUILD_INFO_PATH) -> dict[str, str]:
    """读 key=value 格式的 BUILD_INFO；文件不存在或读不了时返回空字典"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    values = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            values[key.strip()] = value.strip()
    return values


def parse_built_at(value: str) -> datetime | None:
    """BUILD_INFO 的 built= 是 UTC 时间（2026-11-12T08:30:00Z），转成 naive UTC；格式不对返回 None"""
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


def load_build_info(path: Path = BUILD_INFO_PATH) -> BuildInfo:
    values = read_build_file(path)
    # 截到数据库列宽，避免登记时写入失败
    return BuildInfo(
        app_version=settings.APP_VERSION.strip()[:128],
        commit_sha=values.get("commit", "")[:40],
        branch=values.get("branch", "")[:255],
        built_at=parse_built_at(values.get("built", "")),
    )


# 启动时读一次：镜像内容与环境变量在进程运行期间不会变
CURRENT_BUILD = load_build_info()


def current_build() -> BuildInfo:
    return CURRENT_BUILD


def is_same_build(deployment: Deployment, build: BuildInfo) -> bool:
    return (
        deployment.app_version == build.app_version
        and deployment.commit_sha == build.commit_sha
        and deployment.branch == build.branch
        and deployment.built_at == build.built_at
    )


async def latest_deployment(db: AsyncSession) -> Deployment | None:
    result = await db.execute(select(Deployment).order_by(Deployment.id.desc()).limit(1))
    return result.scalar_one_or_none()


async def current_deployment(db: AsyncSession, build: BuildInfo) -> Deployment | None:
    """最近一条记录就是正在运行的版本时返回它；登记失败过等情况下返回 None"""
    latest = await latest_deployment(db)
    if latest is not None and is_same_build(latest, build):
        return latest
    return None


async def record_deployment(db: AsyncSession, build: BuildInfo) -> Deployment:
    """
    后端启动时调用：运行的版本与最近一条记录不同才新增（含回滚到旧版本），同一版本重启不新增。
    单 worker 部署，启动时只有一个进程在登记，不需要处理并发
    """
    latest = await latest_deployment(db)
    if latest is not None and is_same_build(latest, build):
        return latest
    deployment = Deployment(
        app_version=build.app_version,
        commit_sha=build.commit_sha,
        branch=build.branch,
        built_at=build.built_at,
        deployed_at=utcnow(),
        note="",
    )
    db.add(deployment)
    await db.commit()
    logger.info(
        "登记新部署 version=%s commit=%s branch=%s",
        build.app_version, build.commit_sha, build.branch,
    )
    return deployment
