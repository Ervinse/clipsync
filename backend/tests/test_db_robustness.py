"""数据库层容错：上传出错时磁盘与会话行保持一致、访问码创建与文件删除并发、极端时区、统计口径、清理脚本的用户快照、排序规则与部署一致"""
import os
import uuid
from datetime import datetime, timedelta

import pymysql
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import access as access_module
from app.config import settings
from app.core.timeutil import to_naive_utc, utcnow
from app.models import AccessCode, UploadSession, User, UserRole
from scripts import cleanup_expired
from tests.helpers import STORAGE_ROOT, upload


def _init(client, user, total_size=100):
    return client.post(
        "/api/files/upload/init",
        json={"original_name": "f.bin", "total_size": total_size, "chunk_size": 1024},
        headers=user.headers,
    )


def _put_chunk(client, user, upload_id, data=b"x" * 100):
    return client.post(
        "/api/files/upload/chunk",
        data={"upload_id": upload_id, "chunk_index": "0"},
        files={"chunk_data": ("blob", data)},
        headers=user.headers,
    )


async def _count_sessions(session):
    return (await session.execute(select(func.count()).select_from(UploadSession))).scalar()


async def _count_access_codes(session):
    return (await session.execute(select(func.count()).select_from(AccessCode))).scalar()


def _sync_connection():
    """独立的同步连接：模拟「另一个终端」在请求处理中途直接改库"""
    return pymysql.connect(
        host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
        password=settings.DB_PASSWORD, database=settings.DB_NAME, autocommit=True,
    )


# ---------- 上传：出错时磁盘与会话行保持一致 ----------

def test_complete_db_error_after_merge_removes_merged_file_and_allows_retry(client, make_user, db, monkeypatch):
    user = make_user()
    upload_id = _init(client, user).json()["upload_id"]
    assert _put_chunk(client, user, upload_id).status_code == 200

    async def boom(*args, **kwargs):
        raise RuntimeError("simulated: deadlock / lost connection")

    monkeypatch.setattr("app.api.files._reserved_bytes", boom)
    with pytest.raises(RuntimeError):
        client.post("/api/files/upload/complete", json={"upload_id": upload_id}, headers=user.headers)

    # 合并出的文件已删除，会话行和分片还在
    user_dir = STORAGE_ROOT / str(user.id)
    assert not user_dir.exists() or list(user_dir.iterdir()) == []
    assert db(_count_sessions) == 1
    assert (STORAGE_ROOT / "tmp" / upload_id / "0").exists()

    # 数据库恢复后重试 complete 成功，磁盘上只有一份文件
    monkeypatch.undo()
    resp = client.post("/api/files/upload/complete", json={"upload_id": upload_id}, headers=user.headers)
    assert resp.status_code == 200
    assert len(list(user_dir.iterdir())) == 1


def test_init_mkdir_failure_leaves_no_session_row(client, make_user, db, monkeypatch):
    # 建临时目录失败（磁盘满、权限问题）时，不能留下客户端拿不到 upload_id 的会话行
    user = make_user()

    def boom(_upload_id):
        raise OSError("simulated: no space left on device")

    monkeypatch.setattr("app.api.files.ensure_upload_temp_dir", boom)
    for _ in range(settings.MAX_UPLOAD_SESSIONS_PER_USER + 1):
        with pytest.raises(OSError):
            _init(client, user)
    assert db(_count_sessions) == 0

    monkeypatch.undo()
    assert _init(client, user).status_code == 200


def test_init_commit_failure_removes_temp_dir(client, make_user, db, monkeypatch):
    # 先建目录、再写会话行之后，提交失败（数据库死锁、连接断开等）时要把刚建的目录删掉，不留孤儿目录
    user = make_user()
    tmp_root = STORAGE_ROOT / "tmp"
    real_commit = AsyncSession.commit
    seen = {"dir_existed_at_failure": False}

    async def commit_fails_once_dir_exists(self):
        # init 里只有最后一次提交发生在临时目录创建之后：让这一次失败
        if tmp_root.exists() and any(tmp_root.iterdir()):
            seen["dir_existed_at_failure"] = True
            raise RuntimeError("simulated: commit failed")
        return await real_commit(self)

    monkeypatch.setattr(AsyncSession, "commit", commit_fails_once_dir_exists)
    with pytest.raises(RuntimeError):
        _init(client, user)
    monkeypatch.undo()

    assert seen["dir_existed_at_failure"], "没有走到「目录已建好、提交失败」这一步，测试没有意义"
    assert db(_count_sessions) == 0
    assert list(tmp_root.iterdir()) == []


# ---------- 访问码：与文件删除并发、极端时区 ----------

def test_create_file_code_returns_404_when_file_deleted_midway(client, make_user, db, monkeypatch):
    user = make_user()
    file_id = upload(client, user, b"x" * 100).json()["id"]
    real_generate = access_module.generate_access_code
    deleted = {"done": False}

    def delete_file_then_generate():
        # 归属检查已通过、INSERT 尚未执行：另一个终端此刻删除了这个文件
        if not deleted["done"]:
            deleted["done"] = True
            conn = _sync_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM files WHERE id = %s", (file_id,))
            finally:
                conn.close()
        return real_generate()

    monkeypatch.setattr(access_module, "generate_access_code", delete_file_then_generate)
    resp = client.post("/api/access-codes", json={"target_type": "file", "file_id": file_id}, headers=user.headers)
    assert resp.status_code == 404
    assert db(_count_access_codes) == 0


@pytest.mark.parametrize("value", ["9999-12-31T23:59:59-05:00", "0001-01-01T00:00:00+05:00"])
def test_out_of_range_expiry_is_400_not_500(client, make_user, value):
    user, admin = make_user(), make_user(UserRole.ADMIN)
    body = {"target_type": "text", "expires_at": value}
    assert client.post("/api/access-codes", json=body, headers=user.headers).status_code == 400
    resp = client.post("/api/admin/invite-codes", json={"expires_at": value}, headers=admin.headers)
    assert resp.status_code == 400


def test_to_naive_utc_converts_and_rejects_overflow():
    assert to_naive_utc(datetime.fromisoformat("2030-01-01T08:00:00+08:00")) == datetime(2030, 1, 1, 0, 0, 0)
    assert to_naive_utc(None) is None
    naive = datetime(2030, 1, 1, 8, 0, 0)
    assert to_naive_utc(naive) == naive
    with pytest.raises(ValueError):
        to_naive_utc(datetime.fromisoformat("9999-12-31T23:59:59-05:00"))


# ---------- 统计口径 ----------

def test_stats_active_access_codes_excludes_disabled_owner(client, db, make_user):
    # 免登录访问时属主被禁用的码已失效，统计里的「有效访问码」要用同一口径
    admin, active_user, disabled_user = make_user(UserRole.ADMIN), make_user(), make_user()
    for owner in (active_user, disabled_user):
        assert client.post("/api/access-codes", json={"target_type": "text"}, headers=owner.headers).status_code == 200

    async def _disable(session):
        await session.execute(update(User).where(User.id == disabled_user.id).values(is_active=False))

    db(_disable)
    stats = client.get("/api/admin/stats", headers=admin.headers).json()
    assert stats["total_access_codes"] == 2
    assert stats["active_access_codes"] == 1


# ---------- 清理脚本：孤儿用户目录 ----------

def test_orphan_scan_keeps_user_registered_during_scan(client, monkeypatch):
    # 孤儿扫描开头取一份用户名单，清理临时目录期间新注册并上传的用户不在名单里：
    # 删用户目录前必须再确认一次，不能把他的文件当孤儿删掉
    gone_dir = STORAGE_ROOT / "999999"          # 用户已不存在：真正的孤儿
    gone_dir.mkdir(parents=True)
    (gone_dir / "leftover").write_bytes(b"x")

    stale_tmp = STORAGE_ROOT / "tmp" / str(uuid.uuid4())   # 过期且无会话记录的孤儿临时目录
    stale_tmp.mkdir(parents=True)
    old = (utcnow() - timedelta(hours=72)).timestamp()
    os.utime(stale_tmp, (old, old))

    real_cleanup = cleanup_expired.cleanup_upload_temp
    created = {}

    def cleanup_then_register_user(upload_id):
        real_cleanup(upload_id)
        # 此刻（名单已取、临时目录清理中）有新用户注册，并完成了第一次上传
        conn = _sync_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO users (username, password_hash, role, quota_bytes, is_active, created_at) "
                    "VALUES (%s, 'x', 'USER', 1048576, 1, NOW())",
                    (f"late-{uuid.uuid4().hex[:8]}",),
                )
                created["id"] = cur.lastrowid
        finally:
            conn.close()
        new_dir = STORAGE_ROOT / str(created["id"])
        new_dir.mkdir(parents=True)
        (new_dir / "first-upload").write_bytes(b"data")

    monkeypatch.setattr(cleanup_expired, "cleanup_upload_temp", cleanup_then_register_user)
    cutoff = utcnow() - timedelta(hours=settings.UPLOAD_SESSION_TTL_HOURS)
    client.portal.call(cleanup_expired.scan_orphans, cutoff)

    assert not stale_tmp.exists()
    assert not gone_dir.exists()
    assert (STORAGE_ROOT / str(created["id"]) / "first-upload").read_bytes() == b"data"
