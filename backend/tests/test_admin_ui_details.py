"""管理后台文件列表排序次键"""
from app.models import UserRole
from tests.helpers import upload


def test_admin_files_order_stable_within_same_second(client, make_user):
    admin, user = make_user(UserRole.ADMIN), make_user()
    ids = [upload(client, user, b"x", name=f"f{i}.txt").json()["id"] for i in range(3)]
    # created_at 精度只到秒，多条可能相同；按 id 兜底后最新在前
    resp = client.get("/api/admin/files", headers=admin.headers)
    assert resp.status_code == 200
    assert [f["id"] for f in resp.json()["items"]] == sorted(ids, reverse=True)
