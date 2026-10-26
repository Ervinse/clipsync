"""文本栏目：增删改查、归属隔离、数量与大小上限、冲突检测；云剪切板的版本号"""
import pytest

from app.api import texts as texts_module
from tests.helpers import new_text


def test_text_crud(client, make_user):
    user = make_user()
    created = new_text(client, user, "hello", title="  标题  ")
    assert created["title"] == "标题" and created["version"] == 1 and created["access_code"] is None

    resp = client.put(f"/api/texts/{created['id']}", json={"title": "新标题", "content": "world"}, headers=user.headers)
    assert resp.status_code == 200 and resp.json()["version"] == 2

    listing = client.get("/api/texts", headers=user.headers).json()
    assert listing["total"] == 1 and listing["max_texts"] == 200
    assert listing["items"][0]["content"] == "world" and listing["items"][0]["title"] == "新标题"

    assert client.delete(f"/api/texts/{created['id']}", headers=user.headers).status_code == 204
    assert client.get(f"/api/texts/{created['id']}", headers=user.headers).status_code == 404


def test_update_keeps_omitted_fields(client, make_user):
    user = make_user()
    text_id = new_text(client, user, "正文", title="标题")["id"]

    only_title = client.put(f"/api/texts/{text_id}", json={"title": "新标题"}, headers=user.headers).json()
    assert only_title["title"] == "新标题" and only_title["content"] == "正文"

    only_content = client.put(f"/api/texts/{text_id}", json={"content": "新正文"}, headers=user.headers).json()
    assert only_content["title"] == "新标题" and only_content["content"] == "新正文"

    cleared = client.put(f"/api/texts/{text_id}", json={"title": "", "content": ""}, headers=user.headers).json()
    assert cleared["title"] == "" and cleared["content"] == ""


def test_title_optional_and_limited(client, make_user):
    user = make_user()
    assert client.post("/api/texts", json={"content": "x"}, headers=user.headers).json()["title"] == ""
    assert client.post("/api/texts", json={"title": "长" * 101, "content": "x"}, headers=user.headers).status_code == 422


def test_texts_isolated_between_users(client, make_user):
    owner, other = make_user(), make_user()
    text_id = new_text(client, owner, "private")["id"]
    assert client.get("/api/texts", headers=other.headers).json()["total"] == 0
    assert client.get(f"/api/texts/{text_id}", headers=other.headers).status_code == 404
    assert client.put(f"/api/texts/{text_id}", json={"content": "x"}, headers=other.headers).status_code == 404
    assert client.delete(f"/api/texts/{text_id}", headers=other.headers).status_code == 404
    assert client.get(f"/api/texts/{text_id}", headers=owner.headers).json()["content"] == "private"


def test_text_count_limit(client, make_user, monkeypatch):
    monkeypatch.setattr(texts_module, "MAX_TEXTS_PER_USER", 2)
    user = make_user()
    new_text(client, user)
    new_text(client, user)
    resp = client.post("/api/texts", json={"content": "3"}, headers=user.headers)
    assert resp.status_code == 400 and "2" in resp.json()["detail"]


def test_text_size_limit(client, make_user):
    user = make_user()
    big = "a" * (4 * 1024 * 1024 + 1)
    assert client.post("/api/texts", json={"content": big}, headers=user.headers).status_code == 422


def test_text_conflict_detection(client, make_user):
    user = make_user()
    text = new_text(client, user, "v1")
    ok = client.put(f"/api/texts/{text['id']}", json={"content": "a", "base_version": 1}, headers=user.headers)
    assert ok.status_code == 200
    stale = client.put(f"/api/texts/{text['id']}", json={"content": "b", "base_version": 1}, headers=user.headers)
    assert stale.status_code == 409
    # 不带 base_version 直接覆盖（「仍然覆盖」）
    forced = client.put(f"/api/texts/{text['id']}", json={"content": "c"}, headers=user.headers)
    assert forced.status_code == 200 and forced.json()["version"] == 3


def test_text_events_broadcast(client, make_user):
    user = make_user()
    with client.websocket_connect("/ws", subprotocols=["clipsync.v1", f"bearer.{user.token}"]) as ws:
        text = new_text(client, user, "SECRET")
        msg = ws.receive_json()
        assert msg == {"type": "texts_changed", "data": {"id": text["id"]}}
        client.delete(f"/api/texts/{text['id']}", headers=user.headers)
        assert ws.receive_json()["type"] == "texts_changed"


def test_delete_user_removes_texts(client, db, make_user):
    from sqlalchemy import select, func
    from app.models import Text, UserRole
    superadmin, victim = make_user(UserRole.SUPERADMIN), make_user()
    new_text(client, victim, "x")
    assert client.delete(f"/api/admin/users/{victim.id}", headers=superadmin.headers).status_code == 204

    async def _count(s):
        return (await s.execute(select(func.count()).select_from(Text).where(Text.user_id == victim.id))).scalar()
    assert db(_count) == 0


# ---------- 云剪切板的版本号与冲突检测 ----------

def test_clipboard_version_and_conflict(client, make_user):
    user = make_user()
    assert client.get("/api/clipboard", headers=user.headers).json()["version"] == 0
    first = client.put("/api/clipboard", json={"content": "a", "base_version": 0}, headers=user.headers)
    assert first.status_code == 200 and first.json()["version"] == 1
    stale = client.put("/api/clipboard", json={"content": "b", "base_version": 0}, headers=user.headers)
    assert stale.status_code == 409
    assert client.get("/api/clipboard", headers=user.headers).json()["content"] == "a"


@pytest.mark.parametrize("with_code_first", [True, False])
def test_clipboard_code_before_any_content(client, make_user, with_code_first):
    # 还没有剪切板记录时也能先设访问码；随后第一次保存仍从版本 0 开始
    from tests.helpers import set_code
    user = make_user()
    if with_code_first:
        set_code(client, user, "clipboard")
    resp = client.put("/api/clipboard", json={"content": "first", "base_version": 0}, headers=user.headers)
    assert resp.status_code == 200 and resp.json()["version"] == 1
    assert resp.json()["access_code"] == ("mycode" if with_code_first else None)
