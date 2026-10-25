"""测试夹具：独立测试库 clipsync_test + 临时存储目录

每次测试会话：DROP 并重建 clipsync_test，用 alembic upgrade head 建表（同时验证迁移与模型一致）。
开发库不受影响。必须在导入 app 之前改写环境变量（环境变量优先于 .env）。
"""
import asyncio
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

TEST_DB_NAME = "clipsync_test"
BACKEND_DIR = Path(__file__).resolve().parent.parent

os.environ["DB_NAME"] = TEST_DB_NAME
os.environ["JWT_SECRET"] = secrets.token_hex(32)
STORAGE_ROOT = Path(tempfile.mkdtemp(prefix="clipsync-test-"))
os.environ["STORAGE_DIR"] = str(STORAGE_ROOT)

from app.config import settings  # noqa: E402

assert settings.DB_NAME == TEST_DB_NAME, "测试必须连接独立测试库"


async def _recreate_database():
    import aiomysql

    conn = await aiomysql.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
    )
    async with conn.cursor() as cur:
        await cur.execute(f"DROP DATABASE IF EXISTS `{TEST_DB_NAME}`")
        await cur.execute(
            # 排序规则与部署环境一致：docker compose 由 MYSQL_DATABASE 自动建库，用 MySQL 8.4 的服务器默认规则
            f"CREATE DATABASE `{TEST_DB_NAME}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
        )
    conn.close()


asyncio.run(_recreate_database())
subprocess.run(
    [sys.executable, "-m", "alembic", "upgrade", "head"],
    cwd=BACKEND_DIR,
    env=os.environ.copy(),
    check=True,
    capture_output=True,
)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.main import app  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402
from app.models import User, UserRole  # noqa: E402
from app.core.security import hash_password, create_access_token  # noqa: E402
from app.core.timeutil import utcnow  # noqa: E402
from app.rate_limit import limiter  # noqa: E402
from app.core.quick_access import failures  # noqa: E402

_TABLES = [
    "texts", "upload_sessions", "files", "clipboard_history",
    "clipboard", "invite_codes", "invite_batches", "settings", "users",
]

# 测试用户统一密码；预先算好哈希，避免每个用户都跑一次 bcrypt
TEST_PASSWORD = "password123"
_TEST_PASSWORD_HASH = hash_password(TEST_PASSWORD)


@pytest.fixture(scope="session")
def client():
    # 整个会话共用一个事件循环（TestClient 的 portal），DB 连接池才不会跨循环
    with TestClient(app) as c:
        yield c
    shutil.rmtree(STORAGE_ROOT, ignore_errors=True)


def run_db(client, fn):
    """在 TestClient 的事件循环里执行 async fn(db)"""
    async def _wrapper():
        async with AsyncSessionLocal() as db:
            result = await fn(db)
            await db.commit()
            return result
    return client.portal.call(_wrapper)


@pytest.fixture(autouse=True)
def clean_state(client):
    async def _truncate(db):
        await db.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for table in _TABLES:
            await db.execute(text(f"TRUNCATE TABLE `{table}`"))
        await db.execute(text("SET FOREIGN_KEY_CHECKS = 1"))

    run_db(client, _truncate)
    limiter.reset()
    failures.clear()
    for child in STORAGE_ROOT.iterdir():
        shutil.rmtree(child, ignore_errors=True)
    yield


@pytest.fixture
def db(client):
    return lambda fn: run_db(client, fn)


@pytest.fixture
def make_user(client):
    counter = {"n": 0}

    def _make(role=UserRole.USER, active=True, quota=settings.DEFAULT_QUOTA_BYTES, username=None):
        counter["n"] += 1
        name = username or f"{role.value}{counter['n']}"

        async def _create(db):
            user = User(
                username=name,
                password_hash=_TEST_PASSWORD_HASH,
                role=role,
                quota_bytes=quota,
                is_active=active,
                created_at=utcnow(),
            )
            db.add(user)
            await db.flush()
            return user.id

        user_id = run_db(client, _create)
        token = create_access_token({"sub": str(user_id)})
        return SimpleNamespace(
            id=user_id,
            username=name,
            token=token,
            headers={"Authorization": f"Bearer {token}"},
        )

    return _make
