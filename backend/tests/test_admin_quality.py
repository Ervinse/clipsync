"""管理后台：查询合并（N+1 改写）后的结果正确性、邀请码删除约束、有效访问码统计"""
from datetime import timedelta

from sqlalchemy import update

from app.models import AccessCode, InviteCode, UserRole
from app.core.timeutil import utcnow
from tests.helpers import upload


def _add_invite(db, code, created_by, used_by=None, used=False):
    async def _create(s):
        s.add(InviteCode(
            code=code,
            created_by=created_by,
            used_by=used_by,
            used_at=utcnow() if used else None,
            created_at=utcnow(),
        ))
    db(_create)


def test_used_invite_code_cannot_be_deleted(client, db, make_user):
    admin = make_user(UserRole.ADMIN)
    member = make_user()
    _add_invite(db, "USEDCODE0001", admin.id, used_by=member.id, used=True)
    _add_invite(db, "FRESHCODE001", admin.id)

    items = {i["code"]: i for i in client.get("/api/admin/invite-codes", headers=admin.headers).json()["items"]}

    resp = client.delete(f"/api/admin/invite-codes/{items['USEDCODE0001']['id']}", headers=admin.headers)
    assert resp.status_code == 409
    assert client.delete(f"/api/admin/invite-codes/{items['FRESHCODE001']['id']}", headers=admin.headers).status_code == 204


def test_invite_code_list_includes_usernames(client, db, make_user):
    admin = make_user(UserRole.ADMIN)
    member = make_user()
    _add_invite(db, "USEDCODE0002", admin.id, used_by=member.id, used=True)
    _add_invite(db, "FRESHCODE002", admin.id)

    items = {i["code"]: i for i in client.get("/api/admin/invite-codes", headers=admin.headers).json()["items"]}
    assert items["USEDCODE0002"]["created_by_username"] == admin.username
    assert items["USEDCODE0002"]["used_by_username"] == member.username
    assert items["FRESHCODE002"]["used_by_username"] is None


def test_user_list_file_stats(client, make_user):
    admin = make_user(UserRole.ADMIN)
    owner, empty = make_user(), make_user()
    assert upload(client, owner, b"a" * 10).status_code == 200
    assert upload(client, owner, b"b" * 5).status_code == 200

    users = {u["id"]: u for u in client.get("/api/admin/users", headers=admin.headers).json()["items"]}
    assert (users[owner.id]["used_bytes"], users[owner.id]["file_count"]) == (15, 2)
    assert (users[empty.id]["used_bytes"], users[empty.id]["file_count"]) == (0, 0)

    detail = client.get(f"/api/admin/users/{owner.id}", headers=admin.headers).json()
    assert (detail["used_bytes"], detail["file_count"]) == (15, 2)


def test_stats_active_access_codes_excludes_expired(client, db, make_user):
    admin = make_user(UserRole.ADMIN)
    user = make_user()
    codes = [
        client.post("/api/access-codes", json={"target_type": "text"}, headers=user.headers).json()["id"]
        for _ in range(3)
    ]

    async def _expire_one_revoke_one(s):
        await s.execute(update(AccessCode).where(AccessCode.id == codes[0])
                        .values(expires_at=utcnow() - timedelta(minutes=1)))
        await s.execute(update(AccessCode).where(AccessCode.id == codes[1]).values(is_revoked=True))
    db(_expire_one_revoke_one)

    stats = client.get("/api/admin/stats", headers=admin.headers).json()
    assert stats["total_access_codes"] == 3
    assert stats["active_access_codes"] == 1
