"""阶段 5 后端回归：访问码有效期上限、管理后台文件列表排序次键"""
from datetime import datetime, timedelta, timezone

from app.models import UserRole
from tests.helpers import upload


def _create_text_code(client, user, expires_at):
    return client.post(
        "/api/access-codes",
        json={"target_type": "text", "expires_at": expires_at},
        headers=user.headers,
    )


def test_access_code_expiry_within_one_year_accepted(client, make_user):
    user = make_user()
    expires = (datetime.now(timezone.utc) + timedelta(hours=8760)).isoformat()
    assert _create_text_code(client, user, expires).status_code == 200


def test_access_code_expiry_over_one_year_rejected(client, make_user):
    user = make_user()
    expires = (datetime.now(timezone.utc) + timedelta(hours=8761)).isoformat()
    assert _create_text_code(client, user, expires).status_code == 400


def test_access_code_without_expiry_still_allowed(client, make_user):
    user = make_user()
    assert _create_text_code(client, user, None).status_code == 200


def test_admin_files_order_stable_within_same_second(client, make_user):
    admin, user = make_user(UserRole.ADMIN), make_user()
    ids = [upload(client, user, b"x", name=f"f{i}.txt").json()["id"] for i in range(3)]
    # created_at 精度只到秒，多条可能相同；按 id 兜底后最新在前
    resp = client.get("/api/admin/files", headers=admin.headers)
    assert resp.status_code == 200
    assert [f["id"] for f in resp.json()["items"]] == sorted(ids, reverse=True)
