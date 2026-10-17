"""站点显示开关 show_github_link：默认显示、超管可改、随 /auth/me 下发给所有登录用户、管理员只读"""
from app.models import Setting, UserRole


def _me(client, user):
    resp = client.get("/api/auth/me", headers=user.headers)
    assert resp.status_code == 200
    return resp.json()


def test_github_link_shown_by_default(client, make_user):
    user, admin = make_user(), make_user(UserRole.ADMIN)
    assert _me(client, user)["show_github_link"] is True
    resp = client.get("/api/admin/settings", headers=admin.headers)
    assert resp.status_code == 200 and resp.json()["show_github_link"] is True


def test_superadmin_toggle_reaches_plain_user_via_me(client, make_user):
    superadmin, user = make_user(UserRole.SUPERADMIN), make_user()
    for shown in [False, True, False]:
        resp = client.patch("/api/admin/settings", json={"show_github_link": shown}, headers=superadmin.headers)
        assert resp.status_code == 200 and resp.json()["show_github_link"] is shown
        # 普通用户读不了后台设置接口，开关值靠 /auth/me 拿到
        assert _me(client, user)["show_github_link"] is shown


def test_patch_other_settings_keeps_github_link_value(client, make_user):
    superadmin, user = make_user(UserRole.SUPERADMIN), make_user()
    client.patch("/api/admin/settings", json={"show_github_link": False}, headers=superadmin.headers)
    resp = client.patch("/api/admin/settings", json={"registration_enabled": False}, headers=superadmin.headers)
    assert resp.status_code == 200
    assert resp.json()["show_github_link"] is False
    assert _me(client, user)["show_github_link"] is False


def test_admin_cannot_change_github_link(client, make_user):
    admin, user = make_user(UserRole.ADMIN), make_user()
    resp = client.patch("/api/admin/settings", json={"show_github_link": False}, headers=admin.headers)
    assert resp.status_code == 403
    assert _me(client, user)["show_github_link"] is True


def test_plain_user_cannot_read_or_change_settings_endpoint(client, make_user):
    user = make_user()
    assert client.get("/api/admin/settings", headers=user.headers).status_code == 403
    resp = client.patch("/api/admin/settings", json={"show_github_link": False}, headers=user.headers)
    assert resp.status_code == 403


def test_dirty_github_link_value_does_not_break_me(client, db, make_user):
    user = make_user()

    async def _seed(s):
        s.add(Setting(key="show_github_link", value="???"))
    db(_seed)

    # 库里的值不是 true 时按关闭处理，接口不会 500
    assert _me(client, user)["show_github_link"] is False
