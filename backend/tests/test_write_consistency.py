"""写入一致性：无变化的保存、取消与完成上传同时发生、提交后通知失败、限流提示、备注 / 标题去空格、
列表排序、新建超管的配额、WebSocket 意外异常记日志、报错文案"""
import logging
import time
import types

import pytest
from sqlalchemy import delete as sql_delete, update

from app.api import files as files_api
from app.core import quick_access
from app.models import File, Setting, UploadSession, User, UserRole
from app.core.timeutil import utcnow
from datetime import timedelta
from tests.helpers import new_text, set_code, upload, quick_headers


def _ws(client, token):
    return client.websocket_connect("/ws", subprotocols=["clipsync.v1", f"bearer.{token}"])


# ---------- 文本：没有变化的保存不加版本号、不广播 ----------

def test_saving_unchanged_text_keeps_version_and_does_not_broadcast(client, make_user):
    user = make_user()
    text = new_text(client, user, "正文", title="标题")
    url = f"/api/texts/{text['id']}"
    with _ws(client, user.token) as ws:
        for body in ({}, {"content": "正文"}, {"title": "标题", "content": "正文", "base_version": 1}):
            resp = client.put(url, json=body, headers=user.headers)
            assert resp.status_code == 200 and resp.json()["version"] == 1 and resp.json()["content"] == "正文"
        # 另一台设备带旧版本号保存不会被误判为冲突
        assert client.put(url, json={"content": "新", "base_version": 1}, headers=user.headers).json()["version"] == 2
        # 没有广播过无变化的保存：第一条收到的是真正修改的那次
        assert ws.receive_json() == {"type": "texts_changed", "data": {"id": text["id"]}}
    assert client.get(url, headers=user.headers).json()["version"] == 2


def test_unchanged_save_still_checks_version(client, make_user):
    user = make_user()
    text = new_text(client, user, "v1")
    client.put(f"/api/texts/{text['id']}", json={"content": "v2"}, headers=user.headers)
    stale = client.put(f"/api/texts/{text['id']}", json={"content": "v2", "base_version": 1}, headers=user.headers)
    assert stale.status_code == 409


# ---------- 备注、标题：先去首尾空格再校验长度 ----------

def test_title_with_surrounding_spaces_at_the_limit_is_accepted(client, make_user):
    user = make_user()
    padded = f"  {'字' * 100}  "
    created = client.post("/api/texts", json={"title": padded, "content": "x"}, headers=user.headers)
    assert created.status_code == 201 and created.json()["title"] == "字" * 100
    updated = client.put(f"/api/texts/{created.json()['id']}", json={"title": padded + " "}, headers=user.headers)
    assert updated.status_code == 200
    too_long = client.post("/api/texts", json={"title": "字" * 101}, headers=user.headers)
    assert too_long.status_code == 422


def test_notes_with_surrounding_spaces_at_the_limit_are_accepted(client, db, make_user):
    from app.models import Deployment

    admin, superadmin = make_user(UserRole.ADMIN), make_user(UserRole.SUPERADMIN)
    batch = client.post("/api/admin/invite-batches", json={"note": f" {'字' * 100} "}, headers=admin.headers)
    assert batch.status_code == 200 and batch.json()["note"] == "字" * 100
    patched = client.patch(f"/api/admin/invite-batches/{batch.json()['id']}", json={"note": f"  {'字' * 100}  "},
                           headers=admin.headers)
    assert patched.status_code == 200

    async def _add(s):
        record = Deployment(app_version="1.0.0", commit_sha="a" * 12, branch="master", deployed_at=utcnow(), note="")
        s.add(record)
        await s.flush()
        return record.id
    record_id = db(_add)
    resp = client.patch(f"/api/admin/deployments/{record_id}", json={"note": f" {'字' * 200} "}, headers=superadmin.headers)
    assert resp.status_code == 200 and resp.json()["note"] == "字" * 200


# ---------- 文件列表：同一秒上传的文件顺序稳定 ----------

def test_file_list_is_newest_first_within_the_same_second(client, db, make_user):
    user = make_user()
    ids = [upload(client, user, b"x", name=f"f{i}.txt").json()["id"] for i in range(4)]
    same_second = utcnow().replace(microsecond=0)

    async def _flatten(s):
        await s.execute(update(File).where(File.user_id == user.id).values(created_at=same_second))
    db(_flatten)
    listed = [f["id"] for f in client.get("/api/files", headers=user.headers).json()["items"]]
    assert listed == sorted(ids, reverse=True)


# ---------- 取消与完成上传同时发生：只能一边成功 ----------

def test_complete_gives_up_when_upload_is_cancelled_during_merge(client, db, make_user, monkeypatch):
    user = make_user()
    info = client.post(
        "/api/files/upload/init",
        json={"original_name": "a.bin", "total_size": 4, "chunk_size": 4},
        headers=user.headers,
    ).json()
    uid = info["upload_id"]
    assert client.post("/api/files/upload/chunk", data={"upload_id": uid, "chunk_index": "0"},
                       files={"chunk_data": ("blob", b"data")}, headers=user.headers).status_code == 200

    real_merge = files_api._merge_chunks

    def merge_then_session_vanishes(*args, **kwargs):
        size = real_merge(*args, **kwargs)

        async def _cancel(s):
            await s.execute(sql_delete(UploadSession).where(UploadSession.upload_id == uid))
        db(_cancel)  # 合并途中另一个请求取消了上传 / 定时清理删掉了会话
        return size
    monkeypatch.setattr(files_api, "_merge_chunks", merge_then_session_vanishes)

    with _ws(client, user.token) as ws:
        resp = client.post("/api/files/upload/complete", json={"upload_id": uid}, headers=user.headers)
        assert resp.status_code == 404
        ws.send_text('{"type":"ping"}')
        assert ws.receive_json() == {"type": "pong"}  # 没有 file_added 推送
    assert client.get("/api/files", headers=user.headers).json()["total"] == 0
    assert not files_api.get_upload_temp_dir(uid).exists()
    from tests.helpers import STORAGE_ROOT
    user_dir = STORAGE_ROOT / str(user.id)
    assert not user_dir.exists() or list(user_dir.iterdir()) == []  # 合并出的文件已删除


def test_expired_session_with_out_of_range_chunk_is_404_not_400(client, db, make_user):
    user = make_user()
    uid = client.post(
        "/api/files/upload/init",
        json={"original_name": "a.bin", "total_size": 4, "chunk_size": 4},
        headers=user.headers,
    ).json()["upload_id"]

    async def _age(s):
        await s.execute(update(UploadSession).where(UploadSession.upload_id == uid)
                        .values(created_at=utcnow() - timedelta(days=30)))
    db(_age)
    resp = client.post("/api/files/upload/chunk", data={"upload_id": uid, "chunk_index": "99"},
                       files={"chunk_data": ("blob", b"data")}, headers=user.headers)
    assert resp.status_code == 404 and "过期" in resp.json()["detail"]


# ---------- 提交之后通知快速访问页失败：接口仍然成功 ----------

def test_notify_failure_after_commit_does_not_turn_into_500(client, make_user, monkeypatch):
    user = make_user()
    text = new_text(client, user, "v1")
    set_code(client, user, "text", text["id"])
    headers = quick_headers(client, f"{user.username}@mycode")

    # 只替换 quick_access 模块里的校验：notify_quick_viewers 回库确认访问码时用它；
    # ws.py 握手与心跳用的是自己导入的引用，不受影响
    async def broken(*args, **kwargs):
        raise RuntimeError("simulated: lost connection while checking the code")
    monkeypatch.setattr(quick_access, "quick_access_is_valid", broken)

    token = headers["Authorization"].split()[1]
    with client.websocket_connect("/ws", subprotocols=["clipsync.v1", f"bearer.{token}"]) as ws:
        # 先走一次心跳：收到 pong 说明服务端已登记这条快速访问连接，之后的通知才会回库查询
        ws.send_text('{"type":"ping"}')
        assert ws.receive_json() == {"type": "pong"}
        resp = client.put(f"/api/texts/{text['id']}", json={"content": "v2", "base_version": 1}, headers=user.headers)
        assert resp.status_code == 200 and resp.json()["version"] == 2
        assert client.delete(f"/api/texts/{text['id']}", headers=user.headers).status_code == 204


# ---------- 限流提示是中文 detail ----------

def test_rate_limit_response_has_chinese_detail(client, make_user):
    user = make_user()
    body = {"username": user.username, "password": "wrong-password"}
    for _ in range(10):
        client.post("/api/auth/login", json=body)
    resp = client.post("/api/auth/login", json=body)
    assert resp.status_code == 429
    assert resp.json() == {"detail": "操作过于频繁，请稍后再试"}


# ---------- 报错文案：不存在与无权统一 ----------

def test_not_found_messages_are_consistent(client, make_user):
    owner, other = make_user(), make_user()
    superadmin = make_user(UserRole.SUPERADMIN)
    file_id = upload(client, owner, b"data").json()["id"]
    assert client.get(f"/api/files/{file_id}/download", headers=other.headers).json()["detail"] == "文件不存在或无权访问"
    assert client.delete(f"/api/files/{file_id}", headers=other.headers).json()["detail"] == "文件不存在或无权访问"
    # 超管只读接口：不存在就是不存在，不带「无权访问」
    assert client.get(f"/api/admin/users/{owner.id}/texts/999999", headers=superadmin.headers).json()["detail"] == "文本不存在"
    assert client.get(f"/api/admin/users/{owner.id}/clipboard/history/999999",
                      headers=superadmin.headers).json()["detail"] == "历史记录不存在"
    # 上传会话：几处 404 用同一句
    messages = {
        client.delete("/api/files/upload/" + "0" * 8 + "-0000-0000-0000-" + "0" * 12, headers=owner.headers).json()["detail"],
        client.post("/api/files/upload/complete", json={"upload_id": "1" * 8 + "-1111-1111-1111-" + "1" * 12},
                    headers=owner.headers).json()["detail"],
    }
    assert messages == {files_api.SESSION_GONE_DETAIL}


# ---------- WebSocket：意外异常记日志 ----------

def test_ws_unexpected_error_is_logged(client, make_user, monkeypatch, caplog):
    from app.api import ws as ws_api

    def boom(_text):
        raise RuntimeError("simulated: unexpected failure")
    monkeypatch.setattr(ws_api, "json", types.SimpleNamespace(loads=boom))
    user = make_user()
    with caplog.at_level(logging.ERROR):
        with _ws(client, user.token) as ws:
            ws.send_text('{"type":"ping"}')
            # 要在连接还开着时等：退出 with 会取消服务端任务，可能赶不上记日志
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not any(
                "WebSocket 连接异常" in r.getMessage() for r in caplog.records
            ):
                time.sleep(0.05)
    assert any("WebSocket 连接异常" in r.getMessage() for r in caplog.records)


# ---------- 新建超管：默认配额与注册一致 ----------

def test_created_superadmin_gets_the_default_quota_setting(client, db, monkeypatch):
    from scripts import create_superadmin as script

    async def _set(s):
        s.add(Setting(key="default_quota_bytes", value="12345"))
    db(_set)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "newroot")
    monkeypatch.setattr(script.getpass, "getpass", lambda _prompt="": "password123")
    client.portal.call(script.create_superadmin)

    async def _quota(s):
        from sqlalchemy import select
        return (await s.execute(select(User.quota_bytes).where(User.username == "newroot"))).scalar_one()
    assert db(_quota) == 12345
