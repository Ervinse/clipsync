"""数据库层容错：上传出错时磁盘与会话行保持一致、行锁竞态（另一个连接同时改库）、小数秒截断、极端时区、清理脚本的用户快照"""
import os
import threading
import uuid
from datetime import datetime, timedelta

import pymysql
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.timeutil import to_naive_utc, utcnow
from app.models import UploadSession, UserRole
from scripts import cleanup_expired
from tests.helpers import STORAGE_ROOT, add_invite, new_text, upload, init_upload, post_chunk


async def _count_sessions(session):
    return (await session.execute(select(func.count()).select_from(UploadSession))).scalar()


def _sync_connection():
    """独立的同步连接：模拟「另一个终端」在请求处理中途直接改库"""
    return pymysql.connect(
        host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
        password=settings.DB_PASSWORD, database=settings.DB_NAME, autocommit=True,
    )


# ---------- 上传：出错时磁盘与会话行保持一致 ----------

def test_complete_db_error_after_merge_removes_merged_file_and_allows_retry(client, make_user, db, monkeypatch):
    user = make_user()
    upload_id = init_upload(client, user, 100).json()["upload_id"]
    assert post_chunk(client, user, upload_id, 0, b"x" * 100).status_code == 200

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
            init_upload(client, user, 100)
    assert db(_count_sessions) == 0

    monkeypatch.undo()
    assert init_upload(client, user, 100).status_code == 200


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
        init_upload(client, user, 100)
    monkeypatch.undo()

    assert seen["dir_existed_at_failure"], "没有走到「目录已建好、提交失败」这一步，测试没有意义"
    assert db(_count_sessions) == 0
    assert list(tmp_root.iterdir()) == []


# ---------- 并发：请求被行锁挡住时，另一个连接改库 ----------

def _race_with_row_lock(lock_sql, lock_params, change_sql, change_params, request):
    """
    让 request（返回响应的无参函数，在线程里发出）被行锁挡住，再从另一个连接改库并提交，放行后返回响应。
    模拟「请求处理到一半，另一个终端同时改了同一行」的竞态，确定地复现，不靠运气。
    """
    conn = _sync_connection()
    outcome = {}

    def _call():
        try:
            outcome["response"] = request()
        except BaseException as exc:  # noqa: BLE001 - 带回主线程再抛出
            outcome["error"] = exc

    try:
        conn.begin()
        with conn.cursor() as cur:
            cur.execute(lock_sql, lock_params)
            thread = threading.Thread(target=_call)
            thread.start()
            thread.join(1.0)
            assert thread.is_alive(), "请求没有被行锁挡住，测试没有意义"
            cur.execute(change_sql, change_params)
        conn.commit()
        thread.join(15)
        assert not thread.is_alive(), "放开行锁后请求仍未返回"
    finally:
        conn.close()
    if "error" in outcome:
        raise outcome["error"]
    return outcome["response"]


def test_upload_init_judges_quota_read_after_taking_the_lock(client, make_user):
    """加锁后才读配额：管理员恰好同时调低配额时，本次 init 按新配额判断"""
    user = make_user()
    resp = _race_with_row_lock(
        "SELECT id FROM users WHERE id = %s FOR UPDATE", (user.id,),
        "UPDATE users SET quota_bytes = 5 WHERE id = %s", (user.id,),
        lambda: init_upload(client, user, 100),
    )
    assert resp.status_code == 413


def test_delete_invite_code_waits_for_registration_and_keeps_used_code(client, db, make_user):
    """注册正持有邀请码行锁时删除该码：等注册提交后再判断，已使用的码保留作审计记录（409）"""
    admin, member = make_user(UserRole.ADMIN), make_user()
    invite_id, _ = add_invite(db, "RACE-RACE-RACE", admin.id)
    resp = _race_with_row_lock(
        "SELECT id FROM invite_codes WHERE id = %s FOR UPDATE", (invite_id,),
        "UPDATE invite_codes SET used_by = %s, used_at = NOW() WHERE id = %s", (member.id, invite_id),
        lambda: client.delete(f"/api/admin/invite-codes/{invite_id}", headers=admin.headers),
    )
    assert resp.status_code == 409
    codes = client.get("/api/admin/invite-batches", headers=admin.headers).json()["items"][0]["codes"]
    assert [c["id"] for c in codes] == [invite_id]


@pytest.mark.parametrize("kind", ["history", "text", "file"])
def test_second_of_two_concurrent_deletes_gets_404(client, make_user, kind):
    """同一条历史 / 文本 / 文件被同时删除：先提交的成功，后到的返回 404（不是 204，也不重复广播）"""
    user = make_user()
    if kind == "history":
        client.put("/api/clipboard", json={"content": "a"}, headers=user.headers)
        client.put("/api/clipboard", json={"content": "b"}, headers=user.headers)
        row_id = client.get("/api/clipboard/history", headers=user.headers).json()["items"][0]["id"]
        url, table = f"/api/clipboard/history/{row_id}", "clipboard_history"
    elif kind == "text":
        row_id = new_text(client, user)["id"]
        url, table = f"/api/texts/{row_id}", "texts"
    else:
        row_id = upload(client, user, b"data").json()["id"]
        url, table = f"/api/files/{row_id}", "files"
    resp = _race_with_row_lock(
        f"SELECT id FROM {table} WHERE id = %s FOR UPDATE", (row_id,),
        f"DELETE FROM {table} WHERE id = %s", (row_id,),
        lambda: client.delete(url, headers=user.headers),
    )
    assert resp.status_code == 404


# ---------- 时间精度：小数秒入库前截掉 ----------

def test_utcnow_and_to_naive_utc_drop_fractional_seconds():
    assert utcnow().microsecond == 0
    assert to_naive_utc(datetime(2030, 1, 1, 0, 0, 0, 600000)) == datetime(2030, 1, 1, 0, 0, 0)
    assert to_naive_utc(datetime.fromisoformat("2030-01-01T08:00:00.999+08:00")) == datetime(2030, 1, 1, 0, 0, 0)


def test_invite_expiry_with_fractional_seconds_is_truncated_not_rounded_up(client, make_user):
    """9999-12-31 23:59:59.6 被 MySQL 四舍五入进位到 10000 年会报错（500）：小数秒入库前截掉"""
    admin = make_user(UserRole.ADMIN)
    far = client.post("/api/admin/invite-batches", json={"expires_at": "9999-12-31T23:59:59.6"}, headers=admin.headers)
    assert far.status_code == 200
    assert far.json()["codes"][0]["expires_at"].startswith("9999-12-31T23:59:59")
    soon = client.post("/api/admin/invite-batches", json={"expires_at": "2030-01-01T00:00:00.6Z"}, headers=admin.headers)
    assert soon.status_code == 200
    assert soon.json()["codes"][0]["expires_at"].startswith("2030-01-01T00:00:00")


# ---------- 极端时区 ----------

@pytest.mark.parametrize("value", ["9999-12-31T23:59:59-05:00", "0001-01-01T00:00:00+05:00"])
def test_out_of_range_expiry_is_400_not_500(client, make_user, value):
    user, admin = make_user(), make_user(UserRole.ADMIN)
    body = {"target_type": "clipboard", "code": "mycode", "expires_at": value}
    assert client.put("/api/access-codes", json=body, headers=user.headers).status_code == 400
    resp = client.post("/api/admin/invite-batches", json={"expires_at": value}, headers=admin.headers)
    assert resp.status_code == 400


def test_to_naive_utc_converts_and_rejects_overflow():
    assert to_naive_utc(datetime.fromisoformat("2030-01-01T08:00:00+08:00")) == datetime(2030, 1, 1, 0, 0, 0)
    assert to_naive_utc(None) is None
    naive = datetime(2030, 1, 1, 8, 0, 0)
    assert to_naive_utc(naive) == naive
    with pytest.raises(ValueError):
        to_naive_utc(datetime.fromisoformat("9999-12-31T23:59:59-05:00"))


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
