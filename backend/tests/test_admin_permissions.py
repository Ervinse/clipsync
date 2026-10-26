"""管理员与超管的权限边界：admin 管理普通用户与系统设置；改角色、删除用户、查看他人文本只有 superadmin"""
import pytest

from app.models import UserRole
from tests.helpers import new_text, ws_connect, set_clipboard


# ---------- admin 管理普通用户 ----------

def test_admin_can_change_quota_and_status_of_plain_user(client, make_user):
    admin, user = make_user(UserRole.ADMIN), make_user()
    resp = client.patch(f"/api/admin/users/{user.id}/quota", json={"quota_bytes": 1024}, headers=admin.headers)
    assert resp.status_code == 200 and resp.json()["quota_bytes"] == 1024
    resp = client.patch(f"/api/admin/users/{user.id}/status", json={"is_active": False}, headers=admin.headers)
    assert resp.status_code == 200 and resp.json()["is_active"] is False
    # 被禁用后接口立即拒绝
    assert client.get("/api/auth/me", headers=user.headers).status_code == 403


@pytest.mark.parametrize("target_role", [UserRole.ADMIN, UserRole.SUPERADMIN])
def test_admin_cannot_manage_other_admins_or_superadmins(client, make_user, target_role):
    admin, target = make_user(UserRole.ADMIN), make_user(target_role)
    quota = client.patch(f"/api/admin/users/{target.id}/quota", json={"quota_bytes": 1}, headers=admin.headers)
    assert quota.status_code == 403
    status = client.patch(f"/api/admin/users/{target.id}/status", json={"is_active": False}, headers=admin.headers)
    assert status.status_code == 403
    assert client.get("/api/auth/me", headers=target.headers).status_code == 200


def test_admin_cannot_change_own_quota(client, make_user):
    admin = make_user(UserRole.ADMIN)
    resp = client.patch(f"/api/admin/users/{admin.id}/quota", json={"quota_bytes": 1}, headers=admin.headers)
    assert resp.status_code == 403


def test_superadmin_can_change_admin_quota(client, make_user):
    superadmin, admin = make_user(UserRole.SUPERADMIN), make_user(UserRole.ADMIN)
    resp = client.patch(f"/api/admin/users/{admin.id}/quota", json={"quota_bytes": 2048}, headers=superadmin.headers)
    assert resp.status_code == 200 and resp.json()["quota_bytes"] == 2048


def test_admin_can_update_settings(client, make_user):
    admin = make_user(UserRole.ADMIN)
    resp = client.patch("/api/admin/settings", json={"registration_enabled": False}, headers=admin.headers)
    assert resp.status_code == 200 and resp.json()["registration_enabled"] is False


def test_admin_cannot_delete_users(client, make_user):
    admin, user = make_user(UserRole.ADMIN), make_user()
    assert client.delete(f"/api/admin/users/{user.id}", headers=admin.headers).status_code == 403
    assert client.get("/api/auth/me", headers=user.headers).status_code == 200


# ---------- 改角色（仅 superadmin） ----------

def test_superadmin_promotes_and_demotes(client, make_user):
    superadmin, user = make_user(UserRole.SUPERADMIN), make_user()
    resp = client.patch(f"/api/admin/users/{user.id}/role", json={"role": "admin"}, headers=superadmin.headers)
    assert resp.status_code == 200 and resp.json()["role"] == "admin"
    assert client.get("/api/admin/stats", headers=user.headers).status_code == 200

    resp = client.patch(f"/api/admin/users/{user.id}/role", json={"role": "user"}, headers=superadmin.headers)
    assert resp.status_code == 200 and resp.json()["role"] == "user"
    # 降级后已有的 token 立即失去后台权限（每次请求回库读角色）
    assert client.get("/api/admin/stats", headers=user.headers).status_code == 403


def test_role_change_notifies_target(client, make_user):
    superadmin, user = make_user(UserRole.SUPERADMIN), make_user()
    with ws_connect(client, user.token) as ws:
        resp = client.patch(f"/api/admin/users/{user.id}/role", json={"role": "admin"}, headers=superadmin.headers)
        assert resp.status_code == 200
        assert ws.receive_json() == {"type": "role_updated", "data": {"role": "admin"}}


def test_cannot_promote_to_superadmin(client, make_user):
    superadmin, user = make_user(UserRole.SUPERADMIN), make_user()
    resp = client.patch(f"/api/admin/users/{user.id}/role", json={"role": "superadmin"}, headers=superadmin.headers)
    assert resp.status_code == 422
    assert client.get("/api/admin/stats", headers=user.headers).status_code == 403


def test_cannot_change_own_or_other_superadmin_role(client, make_user):
    superadmin, other = make_user(UserRole.SUPERADMIN), make_user(UserRole.SUPERADMIN)
    own = client.patch(f"/api/admin/users/{superadmin.id}/role", json={"role": "user"}, headers=superadmin.headers)
    assert own.status_code == 400
    peer = client.patch(f"/api/admin/users/{other.id}/role", json={"role": "user"}, headers=superadmin.headers)
    assert peer.status_code == 403


def test_admin_cannot_change_roles(client, make_user):
    admin, user = make_user(UserRole.ADMIN), make_user()
    resp = client.patch(f"/api/admin/users/{user.id}/role", json={"role": "admin"}, headers=admin.headers)
    assert resp.status_code == 403
    assert client.get("/api/admin/stats", headers=user.headers).status_code == 403


def test_role_change_unknown_user_is_404(client, make_user):
    superadmin = make_user(UserRole.SUPERADMIN)
    resp = client.patch("/api/admin/users/999999/role", json={"role": "admin"}, headers=superadmin.headers)
    assert resp.status_code == 404


# ---------- 超管只读查看他人文本 ----------

def test_superadmin_reads_clipboard_and_history(client, make_user):
    superadmin, user = make_user(UserRole.SUPERADMIN), make_user()
    set_clipboard(client, user, "v1")
    set_clipboard(client, user, "v2")

    current = client.get(f"/api/admin/users/{user.id}/clipboard", headers=superadmin.headers)
    assert current.status_code == 200 and current.json()["content"] == "v2"

    history = client.get(f"/api/admin/users/{user.id}/clipboard/history", headers=superadmin.headers).json()
    assert history["total"] == 1 and history["items"][0]["content"] == "v1"
    history_id = history["items"][0]["id"]
    item = client.get(f"/api/admin/users/{user.id}/clipboard/history/{history_id}", headers=superadmin.headers)
    assert item.status_code == 200 and item.json()["content"] == "v1"


def test_superadmin_reads_empty_clipboard(client, make_user):
    superadmin, user = make_user(UserRole.SUPERADMIN), make_user()
    resp = client.get(f"/api/admin/users/{user.id}/clipboard", headers=superadmin.headers)
    assert resp.status_code == 200 and resp.json()["content"] == "" and resp.json()["version"] == 0


def test_superadmin_reads_texts(client, make_user):
    superadmin, user = make_user(UserRole.SUPERADMIN), make_user()
    text_id = new_text(client, user, content="PRIVATE", title="t")["id"]
    listing = client.get(f"/api/admin/users/{user.id}/texts", headers=superadmin.headers).json()
    assert listing["total"] == 1 and listing["items"][0]["content"] == "PRIVATE"
    full = client.get(f"/api/admin/users/{user.id}/texts/{text_id}", headers=superadmin.headers)
    assert full.status_code == 200 and full.json()["content"] == "PRIVATE"


def test_content_ids_are_scoped_to_the_given_user(client, make_user):
    """历史 / 文本 id 必须属于路径里的用户：拿 A 的 id 配 B 的路径一律 404"""
    superadmin, alice, bob = make_user(UserRole.SUPERADMIN), make_user(), make_user()
    text_id = new_text(client, alice)["id"]
    set_clipboard(client, alice, "v1")
    set_clipboard(client, alice, "v2")
    history_id = client.get("/api/clipboard/history", headers=alice.headers).json()["items"][0]["id"]

    h = superadmin.headers
    assert client.get(f"/api/admin/users/{bob.id}/texts/{text_id}", headers=h).status_code == 404
    assert client.get(f"/api/admin/users/{bob.id}/clipboard/history/{history_id}", headers=h).status_code == 404


def test_content_of_unknown_user_is_404(client, make_user):
    superadmin = make_user(UserRole.SUPERADMIN)
    for path in ["clipboard", "clipboard/history", "texts"]:
        assert client.get(f"/api/admin/users/999999/{path}", headers=superadmin.headers).status_code == 404


@pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.USER])
def test_non_superadmin_cannot_read_content(client, make_user, role):
    viewer, victim = make_user(role), make_user()
    text_id = new_text(client, victim, content="SECRET")["id"]
    set_clipboard(client, victim, "SECRET")
    set_clipboard(client, victim, "SECRET-V2")
    history_id = client.get("/api/clipboard/history", headers=victim.headers).json()["items"][0]["id"]
    for path in ["clipboard", "clipboard/history", f"clipboard/history/{history_id}", "texts", f"texts/{text_id}"]:
        resp = client.get(f"/api/admin/users/{victim.id}/{path}", headers=viewer.headers)
        assert resp.status_code == 403, path
        assert "SECRET" not in resp.text


def test_content_view_is_read_only(client, make_user):
    """查看接口没有写入方法：PUT / DELETE 都不存在"""
    superadmin, user = make_user(UserRole.SUPERADMIN), make_user()
    text_id = new_text(client, user, content="keep")["id"]
    h = superadmin.headers
    assert client.put(f"/api/admin/users/{user.id}/clipboard", json={"content": "x"}, headers=h).status_code == 405
    assert client.put(f"/api/admin/users/{user.id}/texts/{text_id}", json={"content": "x"}, headers=h).status_code == 405
    assert client.delete(f"/api/admin/users/{user.id}/texts/{text_id}", headers=h).status_code == 405
    assert client.get(f"/api/texts/{text_id}", headers=user.headers).json()["content"] == "keep"


def test_unknown_user_is_404_for_admin_actions(client, make_user):
    admin = make_user(UserRole.ADMIN)
    assert client.patch("/api/admin/users/999999/quota", json={"quota_bytes": 1}, headers=admin.headers).status_code == 404
    assert client.patch("/api/admin/users/999999/status", json={"is_active": False}, headers=admin.headers).status_code == 404
    assert client.get("/api/admin/users/999999", headers=admin.headers).status_code == 404
    superadmin = make_user(UserRole.SUPERADMIN)
    assert client.delete("/api/admin/users/999999", headers=superadmin.headers).status_code == 404


def test_admin_cannot_change_own_status(client, make_user):
    admin = make_user(UserRole.ADMIN)
    resp = client.patch(f"/api/admin/users/{admin.id}/status", json={"is_active": False}, headers=admin.headers)
    assert resp.status_code == 400
    assert client.get("/api/auth/me", headers=admin.headers).status_code == 200


@pytest.mark.parametrize("role", ["superadmin", "root", ""])
def test_role_change_rejects_values_other_than_user_and_admin(client, make_user, role):
    superadmin, user = make_user(UserRole.SUPERADMIN), make_user()
    resp = client.patch(f"/api/admin/users/{user.id}/role", json={"role": role}, headers=superadmin.headers)
    assert resp.status_code == 422
    assert client.get("/api/admin/stats", headers=user.headers).status_code == 403


def test_disabled_user_cannot_log_in(client, make_user):
    user = make_user(active=False)
    resp = client.post("/api/auth/login", json={"username": user.username, "password": "password123"})
    assert resp.status_code == 403


def test_superadmin_clipboard_and_history_views_are_audited(client, make_user, caplog):
    """超管查看他人剪切板与历史各写一条日志，只记操作者、对象和内容类别，不记正文"""
    superadmin, user = make_user(UserRole.SUPERADMIN), make_user()
    set_clipboard(client, user, "AUDIT-PRIVATE-1")
    set_clipboard(client, user, "AUDIT-PRIVATE-2")
    history_id = client.get("/api/clipboard/history", headers=user.headers).json()["items"][0]["id"]
    caplog.clear()
    client.get(f"/api/admin/users/{user.id}/clipboard", headers=superadmin.headers)
    client.get(f"/api/admin/users/{user.id}/clipboard/history", headers=superadmin.headers)
    client.get(f"/api/admin/users/{user.id}/clipboard/history/{history_id}", headers=superadmin.headers)
    messages = [r.getMessage() for r in caplog.records]
    prefix = f"超管查看用户内容 operator={superadmin.id} target={user.id}"
    for what in ("what=clipboard", "what=clipboard_history", f"what=clipboard_history:{history_id}"):
        assert any(m.startswith(prefix) and m.endswith(what) for m in messages), what
    assert not any("AUDIT-PRIVATE" in m for m in messages)
