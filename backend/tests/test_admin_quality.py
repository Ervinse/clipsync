"""管理后台：用户 / 邀请码 / 文件列表与统计的结果正确性、邀请码删除约束"""
from app.models import UserRole
from app.core.timeutil import utcnow
from tests.helpers import upload, add_invite


def _add_invite(db, code, created_by, used_by=None, used=False):
    return add_invite(db, code, created_by, used_by=used_by, used_at=utcnow() if used else None)


def _codes(client, admin):
    """批次列表展开成 {code: 码}，码上附带所属批次的创建者用户名"""
    batches = client.get("/api/admin/invite-batches", headers=admin.headers).json()["items"]
    return {
        c["code"]: {**c, "created_by_username": b["created_by_username"]}
        for b in batches for c in b["codes"]
    }


def test_used_invite_code_cannot_be_deleted(client, db, make_user):
    admin = make_user(UserRole.ADMIN)
    member = make_user()
    _add_invite(db, "USEDCODE0001", admin.id, used_by=member.id, used=True)
    _add_invite(db, "FRESHCODE001", admin.id)

    items = _codes(client, admin)

    resp = client.delete(f"/api/admin/invite-codes/{items['USEDCODE0001']['id']}", headers=admin.headers)
    assert resp.status_code == 409
    assert client.delete(f"/api/admin/invite-codes/{items['FRESHCODE001']['id']}", headers=admin.headers).status_code == 204


def test_invite_code_list_includes_usernames(client, db, make_user):
    admin = make_user(UserRole.ADMIN)
    member = make_user()
    _add_invite(db, "USEDCODE0002", admin.id, used_by=member.id, used=True)
    _add_invite(db, "FRESHCODE002", admin.id)

    items = _codes(client, admin)
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
