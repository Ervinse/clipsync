"""邀请码：批量生成、新格式、注册时输入规范化、批量修改有效期"""
import re
from datetime import timedelta

import pytest

from app.core.invite_code import generate_invite_code, normalize_invite_code
from app.core.timeutil import utcnow
from app.models import InviteCode, UserRole

CODE_PATTERN = re.compile(r"^[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{4}(-[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{4}){2}$")


def _future(days=7):
    return (utcnow() + timedelta(days=days)).isoformat() + "Z"


def _create(client, user, **body):
    return client.post("/api/admin/invite-codes", json=body, headers=user.headers)


def _register(client, username, code):
    return client.post(
        "/api/auth/register",
        json={"username": username, "password": "password123", "invite_code": code},
    )


def _add_invite(db, code, created_by, used=False, expires_at=None):
    async def _create_row(s):
        invite = InviteCode(
            code=code,
            created_by=created_by,
            used_at=utcnow() if used else None,
            expires_at=expires_at,
            created_at=utcnow(),
        )
        s.add(invite)
        await s.flush()
        return invite.id
    return db(_create_row)


# ---------- 格式 ----------

def test_generated_code_format():
    for _ in range(200):
        assert CODE_PATTERN.match(generate_invite_code())


@pytest.mark.parametrize("raw", ["k7qm-3xpd-9rwt", " K7QM3XPD9RWT ", "k7qm 3xpd 9rwt", "K7QM-3XPD-9RWT"])
def test_normalize_accepts_loose_input(raw):
    assert normalize_invite_code(raw) == "K7QM-3XPD-9RWT"


def test_normalize_keeps_legacy_codes():
    # 早期的 16 位大小写混合码原样保留（只去首尾空格）
    assert normalize_invite_code(" aB3xK9mQ2pLs7Wd4 ") == "aB3xK9mQ2pLs7Wd4"


# ---------- 批量生成 ----------

def test_batch_create_returns_distinct_codes_sharing_expiry(client, make_user):
    admin = make_user(UserRole.ADMIN)
    resp = _create(client, admin, count=5, expires_at=_future())
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 5
    assert len({i["code"] for i in items}) == 5
    assert all(CODE_PATTERN.match(i["code"]) for i in items)
    assert len({i["expires_at"] for i in items}) == 1
    listed = client.get("/api/admin/invite-codes", headers=admin.headers).json()
    assert listed["total"] == 5


def test_create_defaults_to_one_code(client, make_user):
    admin = make_user(UserRole.ADMIN)
    resp = _create(client, admin)
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 1
    assert resp.json()["items"][0]["expires_at"] is None


@pytest.mark.parametrize("count", [0, 21, -1])
def test_batch_create_rejects_out_of_range_count(client, make_user, count):
    admin = make_user(UserRole.ADMIN)
    assert _create(client, admin, count=count).status_code == 422
    assert client.get("/api/admin/invite-codes", headers=admin.headers).json()["total"] == 0


def test_batch_create_rejects_past_expiry_without_creating(client, make_user):
    admin = make_user(UserRole.ADMIN)
    past = (utcnow() - timedelta(minutes=1)).isoformat() + "Z"
    assert _create(client, admin, count=3, expires_at=past).status_code == 400
    assert client.get("/api/admin/invite-codes", headers=admin.headers).json()["total"] == 0


def test_regular_user_cannot_create_or_update_invites(client, db, make_user):
    admin, user = make_user(UserRole.ADMIN), make_user()
    invite_id = _add_invite(db, "AAAA-BBBB-CCCC", admin.id)
    assert _create(client, user, count=2).status_code == 403
    resp = client.patch("/api/admin/invite-codes/expiry", json={"ids": [invite_id], "expires_at": None}, headers=user.headers)
    assert resp.status_code == 403


# ---------- 注册时输入规范化 ----------

def test_register_accepts_lowercase_without_dashes(client, make_user):
    admin = make_user(UserRole.ADMIN)
    code = _create(client, admin).json()["items"][0]["code"]
    loose = code.replace("-", "").lower()
    assert _register(client, "alice", f"  {loose} ").status_code == 201
    # 用过之后，换种写法也不能再用
    assert _register(client, "bob", code).status_code == 400


def test_register_with_legacy_code_still_works(client, db, make_user):
    admin = make_user(UserRole.ADMIN)
    _add_invite(db, "aB3xK9mQ2pLs7Wd4", admin.id)
    assert _register(client, "carol", "aB3xK9mQ2pLs7Wd4").status_code == 201


# ---------- 批量修改有效期 ----------

def _patch_expiry(client, user, ids, expires_at):
    return client.patch(
        "/api/admin/invite-codes/expiry",
        json={"ids": ids, "expires_at": expires_at},
        headers=user.headers,
    )


def _expiries(client, admin):
    items = client.get("/api/admin/invite-codes", headers=admin.headers).json()["items"]
    return {i["id"]: i["expires_at"] for i in items}


def test_update_expiry_for_multiple_codes(client, db, make_user):
    admin = make_user(UserRole.ADMIN)
    a = _add_invite(db, "AAAA-AAAA-AAAA", admin.id)
    b = _add_invite(db, "BBBB-BBBB-BBBB", admin.id)
    untouched = _add_invite(db, "CCCC-CCCC-CCCC", admin.id)

    resp = _patch_expiry(client, admin, [a, b], _future(30))
    assert resp.status_code == 200
    assert resp.json()["updated"] == 2
    expiries = _expiries(client, admin)
    assert expiries[a] == expiries[b] is not None
    assert expiries[untouched] is None

    # 改成永久有效
    assert _patch_expiry(client, admin, [a], None).status_code == 200
    assert _expiries(client, admin)[a] is None


def test_expired_unused_code_can_be_renewed_and_used(client, db, make_user):
    admin = make_user(UserRole.ADMIN)
    invite_id = _add_invite(db, "DDDD-DDDD-DDDD", admin.id, expires_at=utcnow() - timedelta(days=1))
    assert _register(client, "dave", "DDDD-DDDD-DDDD").status_code == 400
    assert _patch_expiry(client, admin, [invite_id], _future()).status_code == 200
    assert _register(client, "dave", "DDDD-DDDD-DDDD").status_code == 201


def test_update_expiry_rejects_batch_containing_used_code(client, db, make_user):
    admin = make_user(UserRole.ADMIN)
    fresh = _add_invite(db, "EEEE-EEEE-EEEE", admin.id)
    used = _add_invite(db, "FFFF-FFFF-FFFF", admin.id, used=True)
    assert _patch_expiry(client, admin, [fresh, used], _future()).status_code == 409
    # 整批不改
    assert _expiries(client, admin)[fresh] is None


def test_update_expiry_rejects_unknown_id_and_past_time(client, db, make_user):
    admin = make_user(UserRole.ADMIN)
    fresh = _add_invite(db, "GGGG-GGGG-GGGG", admin.id)
    assert _patch_expiry(client, admin, [fresh, 999999], _future()).status_code == 404
    past = (utcnow() - timedelta(minutes=1)).isoformat() + "Z"
    assert _patch_expiry(client, admin, [fresh], past).status_code == 400
    assert _patch_expiry(client, admin, [], _future()).status_code == 422
    assert _expiries(client, admin)[fresh] is None
