"""认证：注册开关、邀请码、JWT 校验、禁用用户、弱密钥"""
import pytest
from jose import jwt
from pydantic import ValidationError

from app.config import Settings, settings
from app.models import InviteCode, User, UserRole
from app.core.timeutil import utcnow
from datetime import timedelta
from sqlalchemy import select


def _make_invite(db, creator_id, code="INVITE123", **kwargs):
    async def _create(s):
        s.add(InviteCode(code=code, created_by=creator_id, created_at=utcnow(), **kwargs))
    db(_create)
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
