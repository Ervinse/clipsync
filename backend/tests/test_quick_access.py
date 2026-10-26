"""快速访问码：设置规则、凭「用户名@访问码」进入、权限边界、立即失效、输错锁定、限流"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update
from starlette.websockets import WebSocketDisconnect

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


def test_success_does_not_clear_earlier_failures(client, make_user):
    """知道某个有效访问码的人，不能靠「输错几次、输对一次」循环绕过锁定去猜别的码"""
    user = make_user()
    set_code(client, user, "clipboard", code="right")
    for _ in range(MAX_FAILURES - 1):
        assert quick_login(client, f"{user.username}@wrong1").status_code == 404
    assert quick_login(client, f"{user.username}@right").status_code == 200  # 输对只退还这一次
    assert quick_login(client, f"{user.username}@wrong1").status_code == 404  # 累计第 10 次错，触发锁定
    assert quick_login(client, f"{user.username}@right").status_code == 429


def test_concurrent_guesses_cannot_exceed_the_limit(client, make_user, monkeypatch):
    """比对访问码要回库（有 await）：并发进来的猜测在计数前不能溜过锁定检查，总共只放行 MAX_FAILURES 次"""
    import asyncio
    import httpx
    from app.api import access as access_api
    from app.main import app

    user = make_user()
    set_code(client, user, "clipboard", code="right")
    real = access_api.code_is_active

    async def slow(db, owner_id, code):
        await asyncio.sleep(0.05)
        return await real(db, owner_id, code)
    monkeypatch.setattr(access_api, "code_is_active", slow)

    async def burst():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
            responses = await asyncio.gather(*(
                ac.post("/api/access/login", json={"full_code": f"{user.username}@wrong1"})
                for _ in range(MAX_FAILURES + 2)
            ))
        return sorted(r.status_code for r in responses)

    assert client.portal.call(burst) == [404] * MAX_FAILURES + [429] * 2


def test_unknown_and_wrong_code_cost_the_same_lookups(client, make_user, monkeypatch):
    """用户名不存在时也照常查库比对，失败路径的耗时看不出用户名是否存在"""
    from app.api import access as access_api

    user = make_user()
    set_code(client, user, "clipboard", code="right")
    real, calls = access_api.code_is_active, []

    async def spy(db, owner_id, code):
        calls.append(owner_id)
        return await real(db, owner_id, code)
    monkeypatch.setattr(access_api, "code_is_active", spy)

    assert quick_login(client, "nobody-here@wrong1").status_code == 404
    assert quick_login(client, f"{user.username}@wrong1").status_code == 404
    assert calls == [0, user.id]  # 不存在的用户名用 id 0（不属于任何用户）查一遍


def test_failure_tracker_counts_only_recent_failures():
    """窗口之外的失败作废：偶尔输错的人不会越攒越多；窗口内累计到上限才锁定"""
    from app.core.quick_access import FailureTracker, LOCK_SECONDS

    now = [1000.0]
    tracker = FailureTracker(clock=lambda: now[0])
    for _ in range(MAX_FAILURES - 1):
        assert tracker.begin_attempt("u1")
    now[0] += LOCK_SECONDS + 1
    assert tracker.begin_attempt("u1")      # 之前的失败已过窗口，这是重新计数的第 1 次
    for _ in range(MAX_FAILURES - 2):
        assert tracker.begin_attempt("u1")
    assert tracker.begin_attempt("u1")      # 窗口内第 10 次：本次放行比对，随后锁定
    assert not tracker.begin_attempt("u1")
    now[0] += LOCK_SECONDS + 1
    assert tracker.begin_attempt("u1")      # 锁定结束后重新计数


def test_failure_tracker_has_a_hard_size_limit(monkeypatch):
    """随机用户名灌满记录时，淘汰最久没动静的记录，内存有硬上限，且正在锁定的记录优先保留"""
    from app.core import quick_access
    from app.core.quick_access import FailureTracker

    monkeypatch.setattr(quick_access, "_TRACK_LIMIT", 5)
    tracker = FailureTracker()
    for _ in range(MAX_FAILURES):
        tracker.begin_attempt("locked")
    for i in range(50):
        tracker.begin_attempt(f"n:random{i}")
    assert len(tracker._entries) <= 5
    assert not tracker.begin_attempt("locked")


def test_quick_login_is_rate_limited_per_ip(client):
    statuses = [quick_login(client, f"user{i}x@code1").status_code for i in range(31)]
    assert statuses[:30] == [404] * 30
    assert statuses[30] == 429


# ---------- 补充：已签发的凭证随访问码失效、越权访问 ----------

def test_token_issued_before_expiry_stops_working_after_it(client, db, make_user):
    """先换到凭证，访问码随后过期：已拿到的凭证立即返回 401，不用等凭证自己的 2 小时到期"""
    user = make_user()
    text_id = new_text(client, user)["id"]
    set_code(client, user, "text", text_id, code="soon")
    headers = quick_headers(client, f"{user.username}@soon")
    assert client.get("/api/access/items", headers=headers).status_code == 200

    async def _expire(s):
        await s.execute(update(Text).where(Text.id == text_id).values(access_expires_at=utcnow() - timedelta(seconds=1)))
    db(_expire)
    assert client.get("/api/access/items", headers=headers).status_code == 401
    assert client.get(f"/api/access/texts/{text_id}", headers=headers).status_code == 401


def test_cleared_code_blocks_every_quick_endpoint(client, make_user):
    """所有快速访问接口共用同一个校验：码被清除后，剪切板、文本、下载都返回 401"""
    user = make_user()
    client.put("/api/clipboard", json={"content": "clip"}, headers=user.headers)
    text_id = new_text(client, user)["id"]
    file_id = upload(client, user, b"data").json()["id"]
    set_code(client, user, "clipboard")
    set_code(client, user, "text", text_id)
    set_code(client, user, "file", file_id)
    headers = quick_headers(client, f"{user.username}@mycode")
    for target, tid in (("clipboard", None), ("text", text_id), ("file", file_id)):
        set_code(client, user, target, tid, code=None)
    for path in ["/api/access/clipboard", f"/api/access/texts/{text_id}", f"/api/access/files/{file_id}/download"]:
        assert client.get(path, headers=headers).status_code == 401, path


def test_quick_download_cannot_reach_other_users_file_with_same_code(client, make_user):
    """两个用户用了同一个访问码：凭 A 的完整访问码拿不到 B 的文件"""
    alice, bob = make_user(), make_user()
    a_file = upload(client, alice, b"alice-data").json()["id"]
    b_file = upload(client, bob, b"BOB-SECRET").json()["id"]
    set_code(client, alice, "file", a_file, code="shared")
    set_code(client, bob, "file", b_file, code="shared")
    headers = quick_headers(client, f"{alice.username}@shared")
    assert client.get(f"/api/access/files/{a_file}/download", headers=headers).content == b"alice-data"
    resp = client.get(f"/api/access/files/{b_file}/download", headers=headers)
    assert resp.status_code == 404 and b"BOB-SECRET" not in resp.content


def test_quick_edit_text_succeeds_and_persists(client, make_user):
    user = make_user()
    text = new_text(client, user, "v1")
    set_code(client, user, "text", text["id"])
    headers = quick_headers(client, f"{user.username}@mycode")
    resp = client.put(f"/api/access/texts/{text['id']}", json={"content": "edited", "base_version": text["version"]}, headers=headers)
    assert resp.status_code == 200 and resp.json()["content"] == "edited"
    assert client.get(f"/api/texts/{text['id']}", headers=user.headers).json()["content"] == "edited"


def test_clipboard_code_points_at_current_text(client, make_user):
    """云剪切板的访问码不存快照：属主改了内容，快速访问页看到的随之变化"""
    user = make_user()
    client.put("/api/clipboard", json={"content": "first"}, headers=user.headers)
    set_code(client, user, "clipboard")
    headers = quick_headers(client, f"{user.username}@mycode")
    assert client.get("/api/access/clipboard", headers=headers).json()["content"] == "first"
    client.put("/api/clipboard", json={"content": "second"}, headers=user.headers)
    assert client.get("/api/access/clipboard", headers=headers).json()["content"] == "second"
    assert client.get("/api/access/items", headers=headers).json()["clipboard"]["content"] == "second"


def test_ws_registered_after_owner_disabled_is_closed(client, db, make_user, monkeypatch):
    """握手校验通过、登记连接之前用户被禁用（此时断开动作看不到这条连接）：登记后再确认一次，随即以 1008 关闭"""
    from app.api import ws as ws_api

    user = make_user(active=False)

    async def _stale_auth(_websocket):
        return ws_api._Peer(user_id=user.id)  # 模拟握手时用户还是启用的
    monkeypatch.setattr(ws_api, "_authenticate", _stale_auth)
    with pytest.raises(WebSocketDisconnect) as exc:
        with _ws(client, user.token) as ws:
            ws.receive_text()
    assert exc.value.code == 1008


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
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == 1008


def test_quick_ws_closed_on_ping_after_code_expired(client, db, make_user):
    user = make_user()
    set_code(client, user, "clipboard")
    with _ws(client, _quick_token(client, f"{user.username}@mycode")) as ws:
        async def _expire(s):
            await s.execute(update(Clipboard).where(Clipboard.user_id == user.id)
                            .values(access_expires_at=utcnow() - timedelta(seconds=1)))
        db(_expire)  # 不经过接口（如定时清理），只能靠心跳发现
        ws.send_text('{"type":"ping"}')
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == 1008


def test_quick_ws_rejected_with_invalid_code(client, make_user):
    user = make_user()
    set_code(client, user, "clipboard")
    token = _quick_token(client, f"{user.username}@mycode")
    set_code(client, user, "clipboard", code=None)
    with pytest.raises(WebSocketDisconnect) as exc:
        with _ws(client, token) as ws:
            ws.receive_text()
    assert exc.value.code == 1008


def test_quick_ws_closed_when_owner_disabled(client, make_user):
    from app.models import UserRole
    superadmin, user = make_user(UserRole.SUPERADMIN), make_user()
    set_code(client, user, "clipboard")
    with _ws(client, _quick_token(client, f"{user.username}@mycode")) as ws:
        client.patch(f"/api/admin/users/{user.id}/status", json={"is_active": False}, headers=superadmin.headers)
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == 1008


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
