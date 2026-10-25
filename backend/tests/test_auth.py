"""认证：注册开关、邀请码、JWT 校验、禁用用户、弱密钥"""
import pytest
from jose import jwt
from pydantic import ValidationError

from app.config import Settings, settings
from app.models import User, UserRole
from app.core.timeutil import utcnow
from datetime import timedelta
from sqlalchemy import select
from tests.helpers import add_invite


def _make_invite(db, creator_id, code="INVITE123", **kwargs):
    add_invite(db, code, creator_id, **kwargs)
    return code


def _register(client, username, invite, password="password123"):
    return client.post(
        "/api/auth/register",
        json={"username": username, "password": password, "invite_code": invite},
    )


def test_register_with_valid_invite(client, db, make_user):
    admin = make_user(UserRole.ADMIN)
    code = _make_invite(db, admin.id)
    resp = _register(client, "alice", code)
    assert resp.status_code == 201
    # 同一邀请码不能再用
    assert _register(client, "bob", code).status_code == 400


def test_register_blocked_when_registration_disabled(client, db, make_user):
    superadmin = make_user(UserRole.SUPERADMIN)
    code = _make_invite(db, superadmin.id)
    r = client.patch("/api/admin/settings", json={"registration_enabled": False}, headers=superadmin.headers)
    assert r.status_code == 200
    # 安全红线：关闭注册后，持有有效邀请码也不能注册
    assert _register(client, "alice", code).status_code == 403


def test_register_rejects_expired_invite(client, db, make_user):
    admin = make_user(UserRole.ADMIN)
    code = _make_invite(db, admin.id, expires_at=utcnow() - timedelta(minutes=1))
    assert _register(client, "alice", code).status_code == 400


def test_register_does_not_reveal_whether_username_exists(client, make_user):
    """没有有效邀请码时，已存在与不存在的用户名得到完全相同的回应，不能借注册接口探测用户名"""
    make_user(username="taken")
    taken = _register(client, "taken", "no-such-invite")
    fresh = _register(client, "freshname", "no-such-invite")
    assert taken.status_code == fresh.status_code == 400
    assert taken.json() == fresh.json()


def test_register_with_taken_username_keeps_invite_usable(client, db, make_user):
    """邀请码有效但用户名被占用：明确提示用户名已被注册，且邀请码不被消耗，换个用户名还能用"""
    admin = make_user(UserRole.ADMIN)
    make_user(username="taken")
    code = _make_invite(db, admin.id)
    clash = _register(client, "taken", code)
    assert clash.status_code == 400 and "用户名" in clash.json()["detail"]
    assert _register(client, "another", code).status_code == 201


def test_register_always_creates_plain_user(client, db, make_user):
    admin = make_user(UserRole.ADMIN)
    code = _make_invite(db, admin.id)
    resp = client.post(
        "/api/auth/register",
        json={"username": "mallory", "password": "password123", "invite_code": code, "role": "superadmin"},
    )
    assert resp.status_code == 201
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {resp.json()['access_token']}"})
    assert me.json()["role"] == "user"


def test_login_and_me_never_leak_password_hash(client, make_user):
    user = make_user()
    resp = client.post("/api/auth/login", json={"username": user.username, "password": "password123"})
    assert resp.status_code == 200
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {resp.json()['access_token']}"})
    assert "password_hash" not in me.text
    assert "password" not in me.json()


def test_login_error_is_identical_for_unknown_user(client, make_user):
    user = make_user()
    wrong_pw = client.post("/api/auth/login", json={"username": user.username, "password": "nope-nope"})
    no_user = client.post("/api/auth/login", json={"username": "ghost", "password": "nope-nope"})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json()


@pytest.mark.parametrize("path", ["/api/auth/me", "/api/clipboard", "/api/files", "/api/access-codes", "/api/admin/stats"])
def test_protected_endpoints_require_token(client, path):
    assert client.get(path).status_code == 401


def test_rejects_forged_and_malformed_tokens(client, make_user):
    user = make_user()
    cases = [
        jwt.encode({"sub": str(user.id)}, settings.JWT_SECRET, algorithm="HS256"),  # 无 exp
        jwt.encode({"sub": "abc", "exp": 9999999999}, settings.JWT_SECRET, algorithm="HS256"),  # sub 非整数
        jwt.encode({"sub": str(user.id), "exp": 9999999999}, "another-secret-" * 4, algorithm="HS256"),  # 错误密钥
        "not.a.jwt",
    ]
    for token in cases:
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401, token


def test_disabled_user_token_stops_working(client, make_user):
    user = make_user(active=False)
    resp = client.get("/api/auth/me", headers=user.headers)
    assert resp.status_code == 403
    # 前端靠这个响应头识别「账号被禁用」并登出
    assert resp.headers.get("x-auth-error") == "disabled"


def test_permission_denied_403_has_no_disabled_header(client, make_user):
    user = make_user()
    resp = client.get("/api/admin/stats", headers=user.headers)
    assert resp.status_code == 403
    assert "x-auth-error" not in resp.headers


def test_weak_jwt_secret_refused():
    for weak in ["short", "change_this_to_a_long_random_string_in_production"]:
        with pytest.raises(ValidationError):
            Settings(JWT_SECRET=weak)
