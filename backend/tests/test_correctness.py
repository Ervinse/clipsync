"""代码正确性回归：分片下限、并发 complete、历史去重与排序、配额上限、设置脏数据、超管互操作"""
import pytest

from app.api import files as files_api
from app.config import settings
from app.models import Setting, UserRole
from tests.helpers import upload


def _history(client, user):
    return client.get("/api/clipboard/history", headers=user.headers).json()["items"]


def _put(client, user, text):
    assert client.put("/api/clipboard", json={"content": text}, headers=user.headers).status_code == 200


# ---------- 分片上传 ----------

def test_tiny_chunk_size_is_raised_to_keep_chunk_count_bounded(client, make_user):
    user = make_user()
    resp = client.post(
        "/api/files/upload/init",
        json={"original_name": "a.bin", "total_size": 1024 * 1024, "chunk_size": 1},
        headers=user.headers,
    )
    assert resp.status_code == 200
    info = resp.json()
    assert info["total_chunks"] <= files_api.MAX_TOTAL_CHUNKS
    assert info["chunk_size"] * info["total_chunks"] >= 1024 * 1024


def test_concurrent_complete_same_upload_is_rejected(client, make_user):
    user = make_user()
    init = client.post(
        "/api/files/upload/init",
        json={"original_name": "a.txt", "total_size": 3, "chunk_size": 1024},
        headers=user.headers,
    ).json()
    files_api._completing.add(init["upload_id"])  # 模拟另一个 complete 正在合并
    try:
        resp = client.post("/api/files/upload/complete", json={"upload_id": init["upload_id"]}, headers=user.headers)
        assert resp.status_code == 409
    finally:
        files_api._completing.discard(init["upload_id"])


def test_complete_releases_lock_after_failure(client, make_user):
    user = make_user()
    init = client.post(
        "/api/files/upload/init",
        json={"original_name": "a.txt", "total_size": 3, "chunk_size": 1024},
        headers=user.headers,
    ).json()
    # 分片未上传，complete 返回 400，锁必须被释放
    resp = client.post("/api/files/upload/complete", json={"upload_id": init["upload_id"]}, headers=user.headers)
    assert resp.status_code == 400
    assert init["upload_id"] not in files_api._completing


# ---------- 剪贴板历史 ----------

def test_saving_same_content_does_not_duplicate_history(client, make_user):
    user = make_user()
    _put(client, user, "a")
    _put(client, user, "a")
    _put(client, user, "a")
    assert _history(client, user) == []


def test_restore_consumes_restored_history_entry(client, make_user):
    user = make_user()
    _put(client, user, "a")
    _put(client, user, "b")
    [entry] = _history(client, user)
    assert entry["content"] == "a"

    resp = client.post(f"/api/clipboard/history/{entry['id']}/restore", headers=user.headers)
    assert resp.status_code == 200 and resp.json()["content"] == "a"
    # "a" 被恢复后不再留在历史里，"b" 被归档
    assert [h["content"] for h in _history(client, user)] == ["b"]


def test_history_order_is_stable_within_same_second(client, make_user):
    user = make_user()
    for text in ["v1", "v2", "v3", "v4"]:
        _put(client, user, text)
    # created_at 精度只到秒，多条可能相同，按 id 兜底后顺序固定为最新在前
    assert [h["content"] for h in _history(client, user)] == ["v3", "v2", "v1"]


def test_history_keep_removes_oldest(client, make_user, monkeypatch):
    monkeypatch.setattr(settings, "HISTORY_KEEP", 2)
    user = make_user()
    for text in ["v1", "v2", "v3", "v4", "v5"]:
        _put(client, user, text)
    assert [h["content"] for h in _history(client, user)] == ["v4", "v3"]


# ---------- 配额与系统设置 ----------

def test_quota_has_upper_bound(client, make_user):
    superadmin, user = make_user(UserRole.SUPERADMIN), make_user()
    resp = client.patch(f"/api/admin/users/{user.id}/quota", json={"quota_bytes": 2 ** 62}, headers=superadmin.headers)
    assert resp.status_code == 422
    resp = client.patch("/api/admin/settings", json={"default_quota_bytes": 2 ** 62}, headers=superadmin.headers)
    assert resp.status_code == 422


@pytest.mark.parametrize("dirty", ["not-a-number", str(2 ** 62), "-5"])
def test_dirty_default_quota_falls_back_to_env_default(client, db, make_user, dirty):
    admin = make_user(UserRole.ADMIN)

    async def _seed(s):
        s.add(Setting(key="default_quota_bytes", value=dirty))
    db(_seed)

    resp = client.get("/api/admin/settings", headers=admin.headers)
    assert resp.status_code == 200
    assert resp.json()["default_quota_bytes"] == settings.DEFAULT_QUOTA_BYTES


def test_settings_patch_upserts_repeatedly(client, make_user):
    superadmin = make_user(UserRole.SUPERADMIN)
    for enabled in [False, True, False]:
        resp = client.patch("/api/admin/settings", json={"registration_enabled": enabled}, headers=superadmin.headers)
        assert resp.status_code == 200
        assert resp.json()["registration_enabled"] is enabled


# ---------- 超管之间不可互相禁用 / 删除 ----------

def test_superadmin_cannot_disable_or_delete_other_superadmin(client, make_user):
    a, b = make_user(UserRole.SUPERADMIN), make_user(UserRole.SUPERADMIN)
    resp = client.patch(f"/api/admin/users/{b.id}/status", json={"is_active": False}, headers=a.headers)
    assert resp.status_code == 403
    resp = client.delete(f"/api/admin/users/{b.id}", headers=a.headers)
    assert resp.status_code == 403
    # b 仍可正常使用
    assert client.get("/api/auth/me", headers=b.headers).status_code == 200


def test_superadmin_can_still_manage_admin(client, make_user):
    superadmin, admin = make_user(UserRole.SUPERADMIN), make_user(UserRole.ADMIN)
    resp = client.patch(f"/api/admin/users/{admin.id}/status", json={"is_active": False}, headers=superadmin.headers)
    assert resp.status_code == 200 and resp.json()["is_active"] is False


def test_upload_still_works_end_to_end(client, make_user):
    user = make_user()
    resp = upload(client, user, b"x" * 5000, chunk_size=1024)
    assert resp.status_code == 200 and resp.json()["size"] == 5000
