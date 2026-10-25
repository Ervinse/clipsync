"""数据隔离与三级角色边界（IDOR）"""
import pytest

from app.models import UserRole
from tests.helpers import upload, set_code, new_text


def _set_clipboard(client, user, text):
    assert client.put("/api/clipboard", json={"content": text}, headers=user.headers).status_code == 200


def test_clipboard_isolated_between_users(client, make_user):
    alice, bob = make_user(), make_user()
    _set_clipboard(client, alice, "alice secret")
    assert client.get("/api/clipboard", headers=bob.headers).json()["content"] == ""


def test_clipboard_accepts_text_larger_than_64kb(client, make_user):
    # content 列为 MEDIUMTEXT：超过 TEXT 上限（64KB）的文本也要能完整存取，归档到历史时同样不截断
    user = make_user()
    big = "x" * (70 * 1024)
    _set_clipboard(client, user, big)
    assert client.get("/api/clipboard", headers=user.headers).json()["content"] == big
    _set_clipboard(client, user, "next")
    # 归档后完整保存：列表里超过 64KB 的内容只给开头，全文按 id 取
    [item] = client.get("/api/clipboard/history", headers=user.headers).json()["items"]
    assert item["content"] is None and item["size"] == len(big) and item["preview"] == "x" * 200
    assert client.get(f"/api/clipboard/history/{item['id']}", headers=user.headers).json()["content"] == big


def test_history_ids_of_other_user_are_not_accessible(client, make_user):
    alice, bob = make_user(), make_user()
    _set_clipboard(client, alice, "v1")
    _set_clipboard(client, alice, "v2")
    history_id = client.get("/api/clipboard/history", headers=alice.headers).json()["items"][0]["id"]

    assert client.get("/api/clipboard/history", headers=bob.headers).json()["total"] == 0
    assert client.post(f"/api/clipboard/history/{history_id}/restore", headers=bob.headers).status_code == 404
    assert client.delete(f"/api/clipboard/history/{history_id}", headers=bob.headers).status_code == 404
    assert client.get(f"/api/clipboard/history/{history_id}", headers=bob.headers).status_code == 404
    assert client.get(f"/api/clipboard/history/{history_id}").status_code == 401
    # Alice 的历史仍在
    assert client.get("/api/clipboard/history", headers=alice.headers).json()["total"] == 1


def test_file_download_only_owner_and_superadmin(client, make_user):
    owner = make_user()
    other = make_user()
    admin = make_user(UserRole.ADMIN)
    superadmin = make_user(UserRole.SUPERADMIN)
    file_id = upload(client, owner, b"top secret").json()["id"]

    url = f"/api/files/{file_id}/download"
    assert client.get(url, headers=owner.headers).content == b"top secret"
    assert client.get(url, headers=other.headers).status_code == 404
    # 安全红线：admin 绝不能下载他人文件
    assert client.get(url, headers=admin.headers).status_code == 404
    assert client.get(url, headers=superadmin.headers).content == b"top secret"


def test_file_delete_only_owner(client, make_user):
    owner = make_user()
    superadmin = make_user(UserRole.SUPERADMIN)
    file_id = upload(client, owner, b"data").json()["id"]
    assert client.delete(f"/api/files/{file_id}", headers=make_user().headers).status_code == 404
    assert client.delete(f"/api/files/{file_id}", headers=superadmin.headers).status_code == 404
    assert client.get("/api/files", headers=owner.headers).json()["total"] == 1


def test_access_code_overview_only_owner(client, make_user):
    owner, other = make_user(), make_user()
    set_code(client, owner, "text", new_text(client, owner)["id"])
    assert client.get("/api/access-codes", headers=other.headers).json()["total"] == 0
    assert client.get("/api/access-codes", headers=owner.headers).json()["total"] == 1


def test_admin_file_listing_is_metadata_only(client, make_user):
    owner = make_user()
    admin = make_user(UserRole.ADMIN)
    upload(client, owner, b"CONTENT-MARKER")
    resp = client.get("/api/admin/files", headers=admin.headers)
    assert resp.status_code == 200
    assert "CONTENT-MARKER" not in resp.text
    assert "stored_name" not in resp.text
    item = resp.json()["items"][0]
    assert "download_url" not in item


def test_admin_user_detail_has_no_clipboard_content(client, make_user):
    victim = make_user()
    admin = make_user(UserRole.ADMIN)
    _set_clipboard(client, victim, "PRIVATE-TEXT")
    resp = client.get(f"/api/admin/users/{victim.id}", headers=admin.headers)
    assert resp.status_code == 200
    assert "PRIVATE-TEXT" not in resp.text
    assert "password_hash" not in resp.text


def test_plain_user_cannot_reach_admin(client, make_user):
    user = make_user()
    for path in ["/api/admin/stats", "/api/admin/users", "/api/admin/files", "/api/admin/invite-batches", "/api/admin/settings"]:
        assert client.get(path, headers=user.headers).status_code == 403, path


@pytest.mark.parametrize("method,path,body", [
    ("patch", "/api/admin/users/{id}/quota", {"quota_bytes": 1}),
    ("patch", "/api/admin/users/{id}/status", {"is_active": False}),
    ("delete", "/api/admin/users/{id}", None),
    ("patch", "/api/admin/settings", {"registration_enabled": False}),
])
def test_admin_cannot_call_superadmin_endpoints(client, make_user, method, path, body):
    admin = make_user(UserRole.ADMIN)
    target = make_user()
    kwargs = {"headers": admin.headers}
    if body is not None:
        kwargs["json"] = body
    resp = getattr(client, method)(path.format(id=target.id), **kwargs)
    assert resp.status_code == 403
