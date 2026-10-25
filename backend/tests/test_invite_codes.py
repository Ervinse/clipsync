"""邀请码：按批次生成（带备注）、新格式、注册时输入规范化、批量修改有效期、批次备注与整批删除"""
import re
from datetime import timedelta

import pytest

from app.core.invite_code import generate_invite_code, normalize_invite_code
from app.core.timeutil import utcnow
from app.models import UserRole
from tests.helpers import add_invite

CODE_PATTERN = re.compile(r"^[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{4}(-[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{4}){2}$")


def _future(days=7):
    return (utcnow() + timedelta(days=days)).isoformat() + "Z"


def _create(client, user, **body):
    return client.post("/api/admin/invite-batches", json=body, headers=user.headers)


def _register(client, username, code):
    return client.post(
        "/api/auth/register",
        json={"username": username, "password": "password123", "invite_code": code},
    )


def _add_invite(db, code, created_by, used=False, expires_at=None, batch_id=None):
    """写库加一个邀请码，返回邀请码 id"""
    invite_id, _ = add_invite(
        db, code, created_by, batch_id=batch_id,
        used_at=utcnow() if used else None, expires_at=expires_at,
    )
    return invite_id


def _batches(client, admin):
    return client.get("/api/admin/invite-batches", headers=admin.headers).json()


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


# ---------- 按批次生成 ----------

def test_batch_create_returns_distinct_codes_sharing_expiry(client, make_user):
    admin = make_user(UserRole.ADMIN)
    resp = _create(client, admin, count=5, expires_at=_future(), note="  五月新同事  ")
    assert resp.status_code == 200
    batch = resp.json()
    assert batch["note"] == "五月新同事"
    assert batch["created_by_username"] == admin.username
    codes = batch["codes"]
    assert len(codes) == 5
    assert len({c["code"] for c in codes}) == 5
    assert all(CODE_PATTERN.match(c["code"]) for c in codes)
    assert len({c["expires_at"] for c in codes}) == 1
    listed = _batches(client, admin)
    assert listed["total"] == 1
    assert [c["id"] for c in listed["items"][0]["codes"]] == [c["id"] for c in codes]


def test_create_defaults_to_one_code_in_its_own_batch(client, make_user):
    admin = make_user(UserRole.ADMIN)
    resp = _create(client, admin)
    assert resp.status_code == 200
    batch = resp.json()
    assert batch["note"] == ""
    assert len(batch["codes"]) == 1
    assert batch["codes"][0]["expires_at"] is None
    # 每次生成都是新的一批，按创建时间倒序
    second = _create(client, admin, note="第二批").json()
    assert [b["id"] for b in _batches(client, admin)["items"]] == [second["id"], batch["id"]]


@pytest.mark.parametrize("count", [0, 21, -1])
def test_batch_create_rejects_out_of_range_count(client, make_user, count):
    admin = make_user(UserRole.ADMIN)
    assert _create(client, admin, count=count).status_code == 422
    assert _batches(client, admin)["total"] == 0


def test_batch_create_rejects_too_long_note(client, make_user):
    admin = make_user(UserRole.ADMIN)
    assert _create(client, admin, note="字" * 101).status_code == 422
    assert _create(client, admin, note="字" * 100).status_code == 200
    assert _batches(client, admin)["total"] == 1


def test_batch_create_rejects_past_expiry_without_creating(client, make_user):
    admin = make_user(UserRole.ADMIN)
    past = (utcnow() - timedelta(minutes=1)).isoformat() + "Z"
    assert _create(client, admin, count=3, expires_at=past).status_code == 400
    assert _batches(client, admin)["total"] == 0


def test_regular_user_cannot_manage_invites(client, db, make_user):
    admin, user = make_user(UserRole.ADMIN), make_user()
    invite_id, batch_id = add_invite(db, "AAAA-BBBB-CCCC", admin.id)
    assert _create(client, user, count=2).status_code == 403
    assert client.get("/api/admin/invite-batches", headers=user.headers).status_code == 403
    resp = client.patch("/api/admin/invite-codes/expiry", json={"ids": [invite_id], "expires_at": None}, headers=user.headers)
    assert resp.status_code == 403
    assert client.patch(f"/api/admin/invite-batches/{batch_id}", json={"note": "x"}, headers=user.headers).status_code == 403
    assert client.delete(f"/api/admin/invite-batches/{batch_id}", headers=user.headers).status_code == 403
    assert client.delete(f"/api/admin/invite-codes/{invite_id}", headers=user.headers).status_code == 403
    assert _batches(client, admin)["items"][0]["note"] == ""


# ---------- 注册时输入规范化 ----------

def test_register_accepts_lowercase_without_dashes(client, make_user):
    admin = make_user(UserRole.ADMIN)
    code = _create(client, admin).json()["codes"][0]["code"]
    loose = code.replace("-", "").lower()
    assert _register(client, "alice", f"  {loose} ").status_code == 201
    # 用过之后，换种写法也不能再用
    assert _register(client, "bob", code).status_code == 400


def test_register_with_legacy_code_still_works(client, db, make_user):
    admin = make_user(UserRole.ADMIN)
    _add_invite(db, "aB3xK9mQ2pLs7Wd4", admin.id)
    assert _register(client, "carol", "aB3xK9mQ2pLs7Wd4").status_code == 201


def test_used_code_shows_user_in_its_batch(client, make_user):
    admin = make_user(UserRole.ADMIN)
    codes = _create(client, admin, count=2, note="测试").json()["codes"]
    assert _register(client, "erin", codes[0]["code"]).status_code == 201
    listed = {c["code"]: c for c in _batches(client, admin)["items"][0]["codes"]}
    assert listed[codes[0]["code"]]["used_by_username"] == "erin"
    assert listed[codes[0]["code"]]["used_at"] is not None
    assert listed[codes[1]["code"]]["used_by"] is None


# ---------- 批量修改有效期 ----------

def _patch_expiry(client, user, ids, expires_at):
    return client.patch(
        "/api/admin/invite-codes/expiry",
        json={"ids": ids, "expires_at": expires_at},
        headers=user.headers,
    )


def _expiries(client, admin):
    return {c["id"]: c["expires_at"] for b in _batches(client, admin)["items"] for c in b["codes"]}


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


# ---------- 批次备注 ----------

def _patch_note(client, user, batch_id, note):
    return client.patch(f"/api/admin/invite-batches/{batch_id}", json={"note": note}, headers=user.headers)


def test_update_batch_note(client, make_user):
    admin = make_user(UserRole.ADMIN)
    batch = _create(client, admin, count=2).json()
    resp = _patch_note(client, admin, batch["id"], "  给设计组  ")
    assert resp.status_code == 200
    assert resp.json()["note"] == "给设计组"
    assert len(resp.json()["codes"]) == 2
    # 同样的备注再存一次、清空备注都可以
    assert _patch_note(client, admin, batch["id"], "给设计组").status_code == 200
    assert _patch_note(client, admin, batch["id"], "").json()["note"] == ""
    assert _patch_note(client, admin, batch["id"], "字" * 101).status_code == 422
    assert _patch_note(client, admin, 999999, "x").status_code == 404


def test_note_editable_after_all_codes_used(client, db, make_user):
    admin = make_user(UserRole.ADMIN)
    _, batch_id = add_invite(db, "HHHH-HHHH-HHHH", admin.id, used_at=utcnow())
    assert _patch_note(client, admin, batch_id, "已用完").json()["note"] == "已用完"


# ---------- 删除 ----------

def _delete_batch(client, user, batch_id):
    return client.delete(f"/api/admin/invite-batches/{batch_id}", headers=user.headers)


def test_delete_batch_removes_only_unused_codes(client, db, make_user):
    admin, member = make_user(UserRole.ADMIN), make_user()
    used_id, batch_id = add_invite(db, "JJJJ-JJJJ-JJJJ", admin.id, note="混合", used_by=member.id, used_at=utcnow())
    _add_invite(db, "KKKK-KKKK-KKKK", admin.id, batch_id=batch_id)
    _add_invite(db, "MMMM-MMMM-MMMM", admin.id, batch_id=batch_id, expires_at=utcnow() - timedelta(days=1))

    resp = _delete_batch(client, admin, batch_id)
    assert resp.status_code == 200
    assert resp.json() == {"deleted": 2, "batch_deleted": False}
    # 已使用的码与批次、备注保留
    batch = _batches(client, admin)["items"][0]
    assert batch["note"] == "混合"
    assert [c["id"] for c in batch["codes"]] == [used_id]
    assert _register(client, "frank", "KKKK-KKKK-KKKK").status_code == 400

    # 再删一次没有可删的码，批次仍保留
    assert _delete_batch(client, admin, batch_id).json() == {"deleted": 0, "batch_deleted": False}


def test_delete_batch_without_used_codes_removes_batch(client, make_user):
    admin = make_user(UserRole.ADMIN)
    batch = _create(client, admin, count=3).json()
    assert _delete_batch(client, admin, batch["id"]).json() == {"deleted": 3, "batch_deleted": True}
    assert _batches(client, admin)["total"] == 0
    assert _delete_batch(client, admin, batch["id"]).status_code == 404


def test_deleting_last_code_removes_empty_batch(client, make_user):
    admin = make_user(UserRole.ADMIN)
    batch = _create(client, admin, count=2).json()
    first, second = (c["id"] for c in batch["codes"])
    assert client.delete(f"/api/admin/invite-codes/{first}", headers=admin.headers).status_code == 204
    assert _batches(client, admin)["total"] == 1
    assert client.delete(f"/api/admin/invite-codes/{second}", headers=admin.headers).status_code == 204
    assert _batches(client, admin)["total"] == 0
