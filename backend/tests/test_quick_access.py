"""快速访问码：设置规则、凭「用户名@访问码」进入、权限边界、立即失效、输错锁定、限流"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from app.models import User, Text, File, Clipboard
from app.core.timeutil import utcnow
from app.core.quick_access import MAX_FAILURES
from tests.helpers import upload, set_code, new_text, quick_login, quick_headers


# ---------- 设置访问码 ----------

@pytest.mark.parametrize("bad", ["abc", "a" * 33, "has space", "中文码码", "a@b1", "semi;colon"])
def test_code_format_rejected(client, make_user, bad):
    user = make_user()
    set_code(client, user, "clipboard", code=bad, expect=422)


def test_code_is_case_insensitive_and_trimmed(client, make_user):
    user = make_user()
    assert set_code(client, user, "clipboard", code="  My.Code-1 ")["access_code"] == "my.code-1"
    assert quick_login(client, f"{user.username.upper()}@MY.CODE-1").status_code == 200


def test_cannot_set_code_on_others_content(client, make_user):
    owner, attacker = make_user(), make_user()
    text_id = new_text(client, owner)["id"]
    file_id = upload(client, owner, b"data").json()["id"]
    set_code(client, attacker, "text", text_id, expect=404)
    set_code(client, attacker, "file", file_id, expect=404)
    set_code(client, attacker, "text", None, expect=400)
    assert quick_login(client, f"{owner.username}@mycode").status_code == 404


def test_each_item_has_one_code_and_codes_can_repeat(client, make_user):
    user = make_user()
    t1, t2 = new_text(client, user, "one")["id"], new_text(client, user, "two")["id"]
    set_code(client, user, "text", t1, code="first")
    set_code(client, user, "text", t1, code="shared")   # 再设一次就是修改，旧码不再指向它
    set_code(client, user, "text", t2, code="shared")
    assert quick_login(client, f"{user.username}@first").status_code == 404
    items = client.get("/api/access/items", headers=quick_headers(client, f"{user.username}@shared")).json()
    assert sorted(t["id"] for t in items["texts"]) == sorted([t1, t2])


@pytest.mark.parametrize("expires", [
    "2000-01-01T00:00:00Z",
    (datetime.now(timezone.utc) + timedelta(hours=8761)).isoformat(),
    "9999-12-31T23:59:59-05:00",
])
def test_bad_expiry_rejected(client, make_user, expires):
    user = make_user()
    set_code(client, user, "clipboard", expires_at=expires, expect=400)


def test_expiry_within_one_year_accepted(client, make_user):
    user = make_user()
    expires = (datetime.now(timezone.utc) + timedelta(hours=8760)).isoformat()
    assert set_code(client, user, "clipboard", expires_at=expires)["access_expires_at"] is not None


def test_overview_groups_by_code(client, make_user):
    user, other = make_user(), make_user()
    t = new_text(client, user, "body text", title="")["id"]
    f = upload(client, user, b"x", name="a.txt").json()["id"]
    set_code(client, user, "clipboard", code="alpha")
    set_code(client, user, "text", t, code="alpha")
    set_code(client, user, "file", f, code="beta")
    set_code(client, other, "clipboard", code="alpha")

    data = client.get("/api/access-codes", headers=user.headers).json()
    assert data["username"] == user.username
    groups = {g["code"]: g["items"] for g in data["groups"]}
    assert set(groups) == {"alpha", "beta"}
    assert {i["target_type"] for i in groups["alpha"]} == {"clipboard", "text"}
    assert [i["label"] for i in groups["alpha"] if i["target_type"] == "text"] == ["body text"]
    assert groups["beta"][0]["label"] == "a.txt"


# ---------- 凭完整访问码进入 ----------

def test_quick_access_lists_only_items_with_that_code(client, make_user):
    user = make_user()
    client.put("/api/clipboard", json={"content": "clip"}, headers=user.headers)
    shared = new_text(client, user, "shared text", title="T")["id"]
    private = new_text(client, user, "private text")["id"]
    f_shared = upload(client, user, b"file-a", name="a.txt").json()["id"]
    upload(client, user, b"file-b", name="b.txt")
    set_code(client, user, "clipboard", code="work")
    set_code(client, user, "text", shared, code="work")
    set_code(client, user, "text", private, code="home")
    set_code(client, user, "file", f_shared, code="work")

    login = quick_login(client, f"{user.username}@work").json()
    assert login["owner_username"] == user.username and login["code"] == "work"
    assert login["expires_in"] == 7200
    items = client.get("/api/access/items", headers={"Authorization": f"Bearer {login['access_token']}"}).json()
    assert items["clipboard"]["content"] == "clip"
    assert [t["id"] for t in items["texts"]] == [shared]
    assert [f["id"] for f in items["files"]] == [f_shared]
    assert "private text" not in str(items)


def test_wrong_code_and_unknown_user_look_identical(client, make_user):
    user = make_user()
    set_code(client, user, "clipboard", code="right")
    wrong = quick_login(client, f"{user.username}@wrong1")
    unknown = quick_login(client, "nobody-here@right")
    assert wrong.status_code == unknown.status_code == 404
    assert wrong.json() == unknown.json()


@pytest.mark.parametrize("value", ["no-at-sign", "a@b@cdef", "@code1", "user@ab"])
def test_bad_full_code_format(client, value):
    assert quick_login(client, value).status_code == 400


def test_expired_code_cannot_enter(client, db, make_user):
    user = make_user()
    text_id = new_text(client, user)["id"]
    set_code(client, user, "text", text_id, code="soon")

    async def _expire(s):
        await s.execute(update(Text).where(Text.id == text_id).values(access_expires_at=utcnow() - timedelta(seconds=1)))
    db(_expire)
    assert quick_login(client, f"{user.username}@soon").status_code == 404


def test_disabled_owner_cannot_be_entered_and_token_dies(client, db, make_user):
    user = make_user()
    set_code(client, user, "clipboard", code="mycode")
    headers = quick_headers(client, f"{user.username}@mycode")

    async def _disable(s):
        await s.execute(update(User).where(User.id == user.id).values(is_active=False))
    db(_disable)
    assert client.get("/api/access/items", headers=headers).status_code == 401
    assert quick_login(client, f"{user.username}@mycode").status_code == 404


# ---------- 凭证边界：快速访问凭证与登录凭证不能混用 ----------

def test_quick_token_is_not_a_login_token(client, make_user):
    user = make_user()
    set_code(client, user, "clipboard")
    headers = quick_headers(client, f"{user.username}@mycode")
    for path in ["/api/auth/me", "/api/clipboard", "/api/texts", "/api/files", "/api/access-codes"]:
        assert client.get(path, headers=headers).status_code == 401, path
    with pytest.raises(Exception):
        with client.websocket_connect("/ws", subprotocols=["clipsync.v1", "bearer.x"]) as ws:
            ws.receive_text()


def test_login_token_is_not_a_quick_token(client, make_user):
    user = make_user()
    set_code(client, user, "clipboard")
    assert client.get("/api/access/items", headers=user.headers).status_code == 401
    assert client.get("/api/access/items").status_code == 401


# ---------- 立即失效 ----------

def test_clearing_or_changing_code_invalidates_token_immediately(client, make_user):
    user = make_user()
    text_id = new_text(client, user)["id"]
    set_code(client, user, "text", text_id, code="mycode")
    headers = quick_headers(client, f"{user.username}@mycode")
    assert client.get("/api/access/items", headers=headers).status_code == 200

    set_code(client, user, "text", text_id, code="newcode")
    assert client.get("/api/access/items", headers=headers).status_code == 401
    set_code(client, user, "text", text_id, code=None)
    assert quick_login(client, f"{user.username}@newcode").status_code == 404


def test_deleting_last_item_invalidates_token(client, make_user):
    user = make_user()
    file_id = upload(client, user, b"data").json()["id"]
    set_code(client, user, "file", file_id)
    headers = quick_headers(client, f"{user.username}@mycode")
    client.delete(f"/api/files/{file_id}", headers=user.headers)
    assert client.get("/api/access/items", headers=headers).status_code == 401


def test_token_survives_while_other_items_keep_the_code(client, make_user):
    user = make_user()
    a, b = new_text(client, user, "a")["id"], new_text(client, user, "b")["id"]
    set_code(client, user, "text", a)
    set_code(client, user, "text", b)
    headers = quick_headers(client, f"{user.username}@mycode")
    client.delete(f"/api/texts/{a}", headers=user.headers)
    items = client.get("/api/access/items", headers=headers).json()
    assert [t["id"] for t in items["texts"]] == [b]


# ---------- 能做的事：改文本、下载文件；不能做的事：新建、删除、上传、改访问码 ----------

def test_quick_edit_clipboard_goes_into_history(client, make_user):
    user = make_user()
    client.put("/api/clipboard", json={"content": "old"}, headers=user.headers)
    set_code(client, user, "clipboard")
    headers = quick_headers(client, f"{user.username}@mycode")

    current = client.get("/api/access/clipboard", headers=headers).json()
    assert current["content"] == "old"
    resp = client.put("/api/access/clipboard", json={"content": "new", "base_version": current["version"]}, headers=headers)
    assert resp.status_code == 200 and resp.json()["version"] == current["version"] + 1

    assert client.get("/api/clipboard", headers=user.headers).json()["content"] == "new"
    history = client.get("/api/clipboard/history", headers=user.headers).json()["items"]
    assert [h["content"] for h in history] == ["old"]
    # 访问码保留：改内容不会动访问码
    assert client.get("/api/clipboard", headers=user.headers).json()["access_code"] == "mycode"


def test_quick_edit_conflict_returns_409(client, make_user):
    user = make_user()
    text = new_text(client, user, "v1")
    set_code(client, user, "text", text["id"])
    headers = quick_headers(client, f"{user.username}@mycode")

    # 属主在登录端先改了一次
    client.put(f"/api/texts/{text['id']}", json={"content": "owner", "base_version": text["version"]}, headers=user.headers)
    stale = client.put(f"/api/access/texts/{text['id']}", json={"content": "visitor", "base_version": text["version"]}, headers=headers)
    assert stale.status_code == 409
    assert client.get(f"/api/texts/{text['id']}", headers=user.headers).json()["content"] == "owner"


def test_quick_cannot_touch_text_without_that_code(client, make_user):
    user, other = make_user(), make_user()
    coded = new_text(client, user, "coded")["id"]
    plain = new_text(client, user, "plain")["id"]
    others = new_text(client, other, "theirs")["id"]
    set_code(client, user, "text", coded)
    set_code(client, other, "text", others)
    headers = quick_headers(client, f"{user.username}@mycode")
    for text_id in (plain, others):
        assert client.get(f"/api/access/texts/{text_id}", headers=headers).status_code == 404
        assert client.put(f"/api/access/texts/{text_id}", json={"content": "x"}, headers=headers).status_code == 404
    assert client.get(f"/api/texts/{plain}", headers=user.headers).json()["content"] == "plain"


def test_quick_clipboard_requires_clipboard_code(client, make_user):
    user = make_user()
    client.put("/api/clipboard", json={"content": "secret"}, headers=user.headers)
    set_code(client, user, "text", new_text(client, user)["id"])
    headers = quick_headers(client, f"{user.username}@mycode")
    assert client.get("/api/access/items", headers=headers).json()["clipboard"] is None
    assert client.get("/api/access/clipboard", headers=headers).status_code == 404
    assert client.put("/api/access/clipboard", json={"content": "x"}, headers=headers).status_code == 404
    assert client.get("/api/clipboard", headers=user.headers).json()["content"] == "secret"


def test_quick_download_only_files_with_that_code(client, make_user):
    user = make_user()
    coded = upload(client, user, b"payload", name="p.bin").json()["id"]
    plain = upload(client, user, b"hidden").json()["id"]
    set_code(client, user, "file", coded)
    headers = quick_headers(client, f"{user.username}@mycode")
    resp = client.get(f"/api/access/files/{coded}/download", headers=headers)
    assert resp.status_code == 200 and resp.content == b"payload"
    assert client.get(f"/api/access/files/{plain}/download", headers=headers).status_code == 404


def test_quick_has_no_create_delete_upload_or_code_endpoints(client, make_user):
    user = make_user()
    text_id = new_text(client, user)["id"]
    file_id = upload(client, user, b"data").json()["id"]
    set_code(client, user, "text", text_id)
    set_code(client, user, "file", file_id)
    headers = quick_headers(client, f"{user.username}@mycode")
    assert client.post("/api/access/texts", json={"content": "x"}, headers=headers).status_code in (404, 405)
    assert client.delete(f"/api/access/texts/{text_id}", headers=headers).status_code in (404, 405)
    assert client.delete(f"/api/access/files/{file_id}", headers=headers).status_code in (404, 405)
    assert client.post("/api/access/files/upload/init", json={}, headers=headers).status_code in (404, 405)
    # 管理接口只认登录凭证
    assert client.put("/api/access-codes", json={"target_type": "text", "target_id": text_id, "code": None},
                      headers=headers).status_code == 401
    assert client.get(f"/api/texts/{text_id}", headers=user.headers).json()["access_code"] == "mycode"


def test_long_text_listed_with_preview_only(client, make_user):
    user = make_user()
    body = "长" * 30000  # 90000 字节，超过列表直接带全文的上限
    text_id = new_text(client, user, body)["id"]
    set_code(client, user, "text", text_id)
    headers = quick_headers(client, f"{user.username}@mycode")
    [item] = client.get("/api/access/items", headers=headers).json()["texts"]
    assert item["content"] is None and item["size"] == 90000 and item["preview"] == "长" * 200
    assert client.get(f"/api/access/texts/{text_id}", headers=headers).json()["content"] == body


# ---------- 输错锁定与限流 ----------

def test_lockout_after_repeated_failures(client, make_user):
    user, bystander = make_user(), make_user()
    set_code(client, user, "clipboard", code="right")
    set_code(client, bystander, "clipboard", code="right")
    for _ in range(MAX_FAILURES):
        assert quick_login(client, f"{user.username}@wrong1").status_code == 404
    # 锁定期间输对也不放行；其他用户名不受影响
    locked = quick_login(client, f"{user.username}@right")
    assert locked.status_code == 429 and "分钟" in locked.json()["detail"]
    assert quick_login(client, f"{bystander.username}@right").status_code == 200
    # 账号密码登录不受影响
    assert client.post("/api/auth/login", json={"username": user.username, "password": "password123"}).status_code == 200


def test_unknown_username_is_locked_the_same_way(client):
    for _ in range(MAX_FAILURES):
        assert quick_login(client, "ghost-user@whatever").status_code == 404
    assert quick_login(client, "ghost-user@whatever").status_code == 429


def test_lockout_covers_username_spellings_the_database_treats_as_equal(client, make_user):
    """数据库把大小写、重音、零宽字符不同的写法当作同一个用户名：换写法不能重新计数"""
    user = make_user(username="alice")
    set_code(client, user, "clipboard", code="right")
    for _ in range(MAX_FAILURES):
        assert quick_login(client, "alice@wrong1").status_code == 404
    for spelling in ("alice", "ALICE", "alicé", "ali​ce"):
        assert quick_login(client, f"{spelling}@right").status_code == 429, spelling


def test_failures_across_spellings_share_one_count(client, make_user):
    user = make_user(username="alice")
    set_code(client, user, "clipboard", code="right")
    spellings = ["alice", "ALICE", "alicé", "ali​ce", "Alice"]
    for i in range(MAX_FAILURES):
        assert quick_login(client, f"{spellings[i % len(spellings)]}@wrong1").status_code == 404
    assert quick_login(client, "alice@right").status_code == 429


def test_success_resets_failure_count(client, make_user):
    user = make_user()
    set_code(client, user, "clipboard", code="right")
    for _ in range(2):
        for _ in range(MAX_FAILURES - 1):
            quick_login(client, f"{user.username}@wrong1")
        assert quick_login(client, f"{user.username}@right").status_code == 200


def test_quick_login_is_rate_limited_per_ip(client):
    statuses = [quick_login(client, f"user{i}x@code1").status_code for i in range(31)]
    assert statuses[:30] == [404] * 30
    assert statuses[30] == 429


# ---------- 实时推送 ----------

def _ws(client, token):
    return client.websocket_connect("/ws", subprotocols=["clipsync.v1", f"bearer.{token}"])


def _quick_token(client, full_code):
    return quick_login(client, full_code).json()["access_token"]


def test_quick_ws_gets_signal_when_owner_edits(client, make_user):
    user = make_user()
    text = new_text(client, user, "v1")
    set_code(client, user, "text", text["id"])
    with _ws(client, _quick_token(client, f"{user.username}@mycode")) as ws:
        ws.send_text('{"type":"ping"}')
        assert ws.receive_json() == {"type": "pong"}
        client.put(f"/api/texts/{text['id']}", json={"content": "SECRET-V2"}, headers=user.headers)
        msg = ws.receive_json()
        assert msg == {"type": "access_items_changed", "data": {}}  # 只发信号，不带正文


def test_quick_ws_closed_when_code_cleared(client, make_user):
    user = make_user()
    set_code(client, user, "clipboard")
    with _ws(client, _quick_token(client, f"{user.username}@mycode")) as ws:
        set_code(client, user, "clipboard", code=None)
        with pytest.raises(Exception) as exc:
            ws.receive_text()
        assert getattr(exc.value, "code", 1008) == 1008


def test_quick_ws_closed_on_ping_after_code_expired(client, db, make_user):
    user = make_user()
    set_code(client, user, "clipboard")
    with _ws(client, _quick_token(client, f"{user.username}@mycode")) as ws:
        async def _expire(s):
            await s.execute(update(Clipboard).where(Clipboard.user_id == user.id)
                            .values(access_expires_at=utcnow() - timedelta(seconds=1)))
        db(_expire)  # 不经过接口（如定时清理），只能靠心跳发现
        ws.send_text('{"type":"ping"}')
        with pytest.raises(Exception):
            ws.receive_text()


def test_quick_ws_rejected_with_invalid_code(client, make_user):
    user = make_user()
    set_code(client, user, "clipboard")
    token = _quick_token(client, f"{user.username}@mycode")
    set_code(client, user, "clipboard", code=None)
    with pytest.raises(Exception):
        with _ws(client, token) as ws:
            ws.receive_text()


def test_quick_ws_closed_when_owner_disabled(client, make_user):
    from app.models import UserRole
    superadmin, user = make_user(UserRole.SUPERADMIN), make_user()
    set_code(client, user, "clipboard")
    with _ws(client, _quick_token(client, f"{user.username}@mycode")) as ws:
        client.patch(f"/api/admin/users/{user.id}/status", json={"is_active": False}, headers=superadmin.headers)
        with pytest.raises(Exception):
            ws.receive_text()


def test_quick_edit_notifies_owner_terminals(client, make_user):
    user = make_user()
    text = new_text(client, user, "v1")
    set_code(client, user, "text", text["id"])
    headers = quick_headers(client, f"{user.username}@mycode")
    with _ws(client, user.token) as ws:
        client.put(f"/api/access/texts/{text['id']}", json={"content": "v2"}, headers=headers)
        assert ws.receive_json() == {"type": "texts_changed", "data": {"id": text["id"]}}


def test_setting_code_broadcasts_access_codes_changed(client, make_user):
    user = make_user()
    with _ws(client, user.token) as ws:
        set_code(client, user, "clipboard")
        assert ws.receive_json()["type"] == "access_codes_changed"
        set_code(client, user, "clipboard", code=None)
        assert ws.receive_json()["type"] == "access_codes_changed"


# ---------- 清理脚本与统计 ----------

def test_cleanup_clears_expired_codes_but_keeps_content(client, db, make_user):
    from scripts import cleanup_expired
    user = make_user()
    text_id = new_text(client, user, "keep me")["id"]
    file_id = upload(client, user, b"data").json()["id"]
    set_code(client, user, "text", text_id, code="old1")
    set_code(client, user, "file", file_id, code="live")

    async def _expire(s):
        await s.execute(update(Text).where(Text.id == text_id).values(access_expires_at=utcnow() - timedelta(minutes=1)))
    db(_expire)
    client.portal.call(cleanup_expired.cleanup)

    text = client.get(f"/api/texts/{text_id}", headers=user.headers).json()
    assert text["content"] == "keep me" and text["access_code"] is None and text["access_expires_at"] is None
    assert client.get("/api/files", headers=user.headers).json()["items"][0]["access_code"] == "live"


def test_stats_count_distinct_codes(client, db, make_user):
    from app.models import UserRole
    admin, user, disabled = make_user(UserRole.ADMIN), make_user(), make_user()
    a, b = new_text(client, user, "a")["id"], new_text(client, user, "b")["id"]
    set_code(client, user, "text", a, code="same")
    set_code(client, user, "text", b, code="same")       # 同一个码挂两样内容，算一个
    set_code(client, user, "clipboard", code="other")
    f = upload(client, user, b"x").json()["id"]
    set_code(client, user, "file", f, code="gone")
    set_code(client, disabled, "clipboard", code="same")  # 不同属主的同名码算另一个

    async def _change(s):
        await s.execute(update(File).where(File.id == f).values(access_expires_at=utcnow() - timedelta(minutes=1)))
        await s.execute(update(User).where(User.id == disabled.id).values(is_active=False))
    db(_change)

    stats = client.get("/api/admin/stats", headers=admin.headers).json()
    assert stats["total_access_codes"] == 4
    assert stats["active_access_codes"] == 2
