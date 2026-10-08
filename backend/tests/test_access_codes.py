"""免登录访问码：随机性、失效路径、限流、公开前缀"""
from datetime import timedelta

from sqlalchemy import update

from app.models import AccessCode, User
from app.core.timeutil import utcnow
from tests.helpers import upload


def _text_code(client, user, **body):
    resp = client.post("/api/access-codes", json={"target_type": "text", **body}, headers=user.headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_text_code_reads_live_clipboard(client, make_user):
    user = make_user()
    code = _text_code(client, user)
    assert len(code["code"]) >= 12
    client.put("/api/clipboard", json={"content": "v1"}, headers=user.headers)
    assert client.get(f"/api/access/{code['code']}").json()["content"] == "v1"
    client.put("/api/clipboard", json={"content": "v2"}, headers=user.headers)
    # 不存快照：始终是属主当前文本
    assert client.get(f"/api/access/{code['code']}").json()["content"] == "v2"


def test_codes_are_unique_and_random(client, make_user):
    user = make_user()
    codes = {_text_code(client, user)["code"] for _ in range(20)}
    assert len(codes) == 20


def test_access_url_points_to_frontend_page(client, make_user):
    """access_url 由后端按请求 scheme + host 拼出前端访问页链接，不指向 API"""
    user = make_user()
    text = _text_code(client, user)
    assert text["access_url"] == f"http://testserver/access/{text['code']}"

    file_id = upload(client, user, b"data").json()["id"]
    resp = client.post(
        "/api/access-codes", json={"target_type": "file", "file_id": file_id}, headers=user.headers
    )
    assert resp.status_code == 200, resp.text
    file_code = resp.json()
    assert file_code["access_url"] == f"http://testserver/access/{file_code['code']}?t=file"


def test_revoked_code_is_invalid(client, make_user):
    user = make_user()
    code = _text_code(client, user)
    client.delete(f"/api/access-codes/{code['id']}", headers=user.headers)
    assert client.get(f"/api/access/{code['code']}").status_code == 404


def test_expired_code_is_invalid(client, db, make_user):
    user = make_user()
    code = _text_code(client, user)

    async def _expire(s):
        await s.execute(update(AccessCode).where(AccessCode.id == code["id"]).values(expires_at=utcnow() - timedelta(seconds=1)))
    db(_expire)
    assert client.get(f"/api/access/{code['code']}").status_code == 404


def test_cannot_create_code_already_expired(client, make_user):
    user = make_user()
    resp = client.post(
        "/api/access-codes",
        json={"target_type": "text", "expires_at": "2000-01-01T00:00:00Z"},
        headers=user.headers,
    )
    assert resp.status_code == 400


def test_disabled_owner_code_is_invalid(client, db, make_user):
    user = make_user()
    code = _text_code(client, user)

    async def _disable(s):
        await s.execute(update(User).where(User.id == user.id).values(is_active=False))
    db(_disable)
    assert client.get(f"/api/access/{code['code']}").status_code == 404


def test_file_code_dies_with_source_file(client, make_user):
    user = make_user()
    file_id = upload(client, user, b"payload").json()["id"]
    code = client.post(
        "/api/access-codes", json={"target_type": "file", "file_id": file_id}, headers=user.headers
    ).json()["code"]
    assert client.get(f"/api/access/{code}/download").content == b"payload"
    client.delete(f"/api/files/{file_id}", headers=user.headers)
    assert client.get(f"/api/access/{code}/download").status_code == 404


def test_type_mismatch_and_unknown_codes_look_identical(client, make_user):
    user = make_user()
    code = _text_code(client, user)["code"]
    mismatch = client.get(f"/api/access/{code}/download")
    unknown = client.get("/api/access/doesnotexist/download")
    assert mismatch.status_code == unknown.status_code == 404
    assert mismatch.json() == unknown.json()


def test_public_handler_not_exposed_under_management_prefix(client, make_user):
    user = make_user()
    code = _text_code(client, user)["code"]
    # /api/access-codes/{code} 不是免登录入口：公开接口只挂在 /api/access 下
    assert client.get(f"/api/access-codes/{code}").status_code in (401, 404, 405)


def test_public_access_is_rate_limited(client):
    statuses = [client.get("/api/access/nonexistentcode").status_code for _ in range(31)]
    assert statuses[:30] == [404] * 30
    assert statuses[30] == 429
