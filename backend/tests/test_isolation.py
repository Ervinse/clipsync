"""数据隔离与三级角色边界（IDOR）"""
import pytest

from app.models import UserRole
from tests.helpers import upload, set_code, new_text, set_clipboard


def test_clipboard_isolated_between_users(client, make_user):
    alice, bob = make_user(), make_user()
    set_clipboard(client, alice, "alice secret")
    assert client.get("/api/clipboard", headers=bob.headers).json()["content"] == ""


def test_clipboard_accepts_text_larger_than_64kb(client, make_user):
    # content 列为 MEDIUMTEXT：超过 TEXT 上限（64KB）的文本也要能完整存取，归档到历史时同样不截断
    user = make_user()
    big = "x" * (70 * 1024)
    set_clipboard(client, user, big)
    assert client.get("/api/clipboard", headers=user.headers).json()["content"] == big
    set_clipboard(client, user, "next")
    # 归档后完整保存：列表里超过 64KB 的内容只给开头，全文按 id 取
    [item] = client.get("/api/clipboard/history", headers=user.headers).json()["items"]
    assert item["content"] is None and item["size"] == len(big) and item["preview"] == "x" * 200
    assert client.get(f"/api/clipboard/history/{item['id']}", headers=user.headers).json()["content"] == big


def test_history_ids_of_other_user_are_not_accessible(client, make_user):
    alice, bob = make_user(), make_user()
    set_clipboard(client, alice, "v1")
    set_clipboard(client, alice, "v2")
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
    set_clipboard(client, victim, "PRIVATE-TEXT")
    resp = client.get(f"/api/admin/users/{victim.id}", headers=admin.headers)
    assert resp.status_code == 200
    assert "PRIVATE-TEXT" not in resp.text
    assert "password_hash" not in resp.text


def test_plain_user_cannot_reach_admin(client, make_user):
    user = make_user()
    for path in ["/api/admin/stats", "/api/admin/users", "/api/admin/files", "/api/admin/invite-batches", "/api/admin/settings"]:
        assert client.get(path, headers=user.headers).status_code == 403, path


@pytest.mark.parametrize("method,path,body", [
    ("delete", "/api/admin/users/{id}", None),
    ("patch", "/api/admin/users/{id}/role", {"role": "admin"}),
    ("get", "/api/admin/users/{id}/clipboard", None),
    ("get", "/api/admin/users/{id}/clipboard/history", None),
    ("get", "/api/admin/users/{id}/clipboard/history/1", None),
    ("get", "/api/admin/users/{id}/texts", None),
    ("get", "/api/admin/users/{id}/texts/1", None),
    ("patch", "/api/admin/deployments/{id}", {"note": "x"}),
])
def test_admin_cannot_call_superadmin_endpoints(client, make_user, method, path, body):
    admin = make_user(UserRole.ADMIN)
    target = make_user()
    kwargs = {"headers": admin.headers}
    if body is not None:
        kwargs["json"] = body
    resp = getattr(client, method)(path.format(id=target.id), **kwargs)
    assert resp.status_code == 403


def test_admin_user_list_has_no_content_or_password_hash(client, make_user):
    admin, victim = make_user(UserRole.ADMIN), make_user()
    set_clipboard(client, victim, "PRIVATE-TEXT")
    new_text(client, victim, "PRIVATE-NOTE")
    resp = client.get("/api/admin/users", headers=admin.headers)
    assert resp.status_code == 200
    assert "PRIVATE" not in resp.text and "password_hash" not in resp.text


def test_file_list_is_empty_for_other_users(client, make_user):
    owner, other = make_user(), make_user()
    upload(client, owner, b"data")
    assert client.get("/api/files", headers=owner.headers).json()["total"] == 1
    listing = client.get("/api/files", headers=other.headers).json()
    assert listing["total"] == 0 and listing["items"] == []


@pytest.mark.parametrize("role", [UserRole.SUPERADMIN, UserRole.ADMIN, UserRole.USER])
def test_others_cannot_read_write_or_delete_content_by_id(client, make_user, role):
    """超管对他人内容只有只读入口（/api/admin/...）；经本人接口按 id 读、改、删、恢复一律 404，内容不变"""
    owner, other = make_user(), make_user(role)
    text = new_text(client, owner, "OWNER-TEXT")
    set_clipboard(client, owner, "v1")
    set_clipboard(client, owner, "v2")
    history_id = client.get("/api/clipboard/history", headers=owner.headers).json()["items"][0]["id"]
    file_id = upload(client, owner, b"file-body").json()["id"]
    h = other.headers

    assert client.get(f"/api/texts/{text['id']}", headers=h).status_code == 404
    assert client.put(f"/api/texts/{text['id']}", json={"content": "HACKED"}, headers=h).status_code == 404
    assert client.delete(f"/api/texts/{text['id']}", headers=h).status_code == 404
    assert client.post(f"/api/clipboard/history/{history_id}/restore", headers=h).status_code == 404
    assert client.delete(f"/api/clipboard/history/{history_id}", headers=h).status_code == 404
    for target, tid in (("text", text["id"]), ("file", file_id)):
        resp = client.put("/api/access-codes", json={"target_type": target, "target_id": tid, "code": "stolen"}, headers=h)
        assert resp.status_code == 404, target

    assert client.get(f"/api/texts/{text['id']}", headers=owner.headers).json()["content"] == "OWNER-TEXT"
    assert client.get("/api/clipboard", headers=owner.headers).json()["content"] == "v2"
    assert client.get("/api/clipboard/history", headers=owner.headers).json()["total"] == 1
    assert client.get("/api/access-codes", headers=owner.headers).json()["total"] == 0


@pytest.mark.parametrize("role", [UserRole.SUPERADMIN, UserRole.ADMIN, UserRole.USER])
def test_others_cannot_touch_someone_elses_upload_session(client, make_user, role):
    owner, other = make_user(), make_user(role)
    info = client.post(
        "/api/files/upload/init",
        json={"original_name": "a.bin", "total_size": 4, "chunk_size": 4},
        headers=owner.headers,
    ).json()
    uid = info["upload_id"]
    chunk = client.post("/api/files/upload/chunk", data={"upload_id": uid, "chunk_index": "0"},
                        files={"chunk_data": ("blob", b"evil")}, headers=other.headers)
    assert chunk.status_code == 404
    assert client.post("/api/files/upload/complete", json={"upload_id": uid}, headers=other.headers).status_code == 404
    assert client.delete(f"/api/files/upload/{uid}", headers=other.headers).status_code == 404

    # 属主的会话没有受影响，仍能正常完成
    ok = client.post("/api/files/upload/chunk", data={"upload_id": uid, "chunk_index": "0"},
                     files={"chunk_data": ("blob", b"good")}, headers=owner.headers)
    assert ok.status_code == 200
    done = client.post("/api/files/upload/complete", json={"upload_id": uid}, headers=owner.headers)
    assert done.status_code == 200
    assert client.get(f"/api/files/{done.json()['id']}/download", headers=owner.headers).content == b"good"
