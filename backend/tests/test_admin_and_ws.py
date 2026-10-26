"""删除用户的完整清理 + WebSocket 认证与断开"""
import pytest
from sqlalchemy import select, func
from starlette.websockets import WebSocketDisconnect

from app.models import (
    User, UserRole, File, Clipboard, ClipboardHistory, Text, InviteBatch, InviteCode,
)
from app.core.timeutil import utcnow
from tests.helpers import upload, STORAGE_ROOT, set_code, new_text, add_invite, ws_connect


def test_delete_user_removes_all_data(client, db, make_user):
    superadmin = make_user(UserRole.SUPERADMIN)
    victim = make_user()

    add_invite(db, "USEDCODE", superadmin.id, used_by=victim.id, used_at=utcnow())

    upload(client, victim, b"file-data")
    client.put("/api/clipboard", json={"content": "a"}, headers=victim.headers)
    client.put("/api/clipboard", json={"content": "b"}, headers=victim.headers)
    set_code(client, victim, "clipboard")
    set_code(client, victim, "text", new_text(client, victim)["id"])

    resp = client.delete(f"/api/admin/users/{victim.id}", headers=superadmin.headers)
    assert resp.status_code == 204

    async def _counts(s):
        out = {}
        for model, col in [(User, User.id), (File, File.user_id), (Clipboard, Clipboard.user_id),
                           (ClipboardHistory, ClipboardHistory.user_id), (Text, Text.user_id)]:
            out[model.__name__] = (await s.execute(select(func.count()).select_from(model).where(col == victim.id))).scalar()
        return out
    assert all(v == 0 for v in db(_counts).values())
    assert not (STORAGE_ROOT / str(victim.id)).exists()

    # 使用者被删后，这张邀请码不能被重新使用
    reuse = client.post("/api/auth/register",
                        json={"username": "newbie", "password": "password123", "invite_code": "USEDCODE"})
    assert reuse.status_code == 400


def test_deleted_user_loses_token_and_websocket(client, make_user):
    """删除用户后：旧 token 立即 401，已连着的 WebSocket 被服务端关闭（1008），也不能再登录或重连"""
    superadmin, victim = make_user(UserRole.SUPERADMIN), make_user()
    assert client.get("/api/auth/me", headers=victim.headers).status_code == 200
    with ws_connect(client, victim.token) as ws:
        assert client.delete(f"/api/admin/users/{victim.id}", headers=superadmin.headers).status_code == 204
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == 1008
    assert client.get("/api/auth/me", headers=victim.headers).status_code == 401
    assert client.post("/api/auth/login", json={"username": victim.username, "password": "password123"}).status_code == 401
    with pytest.raises(WebSocketDisconnect):
        with ws_connect(client, victim.token) as ws:
            ws.receive_text()


def test_delete_admin_handles_their_invite_batches(client, db, make_user):
    """被删管理员的批次：码全未使用的批次整批删除；含已使用码的批次转记到执行删除的超管名下，备注保留"""
    superadmin, admin, member = make_user(UserRole.SUPERADMIN), make_user(UserRole.ADMIN), make_user()
    _, unused_batch = add_invite(db, "UNUSED01", admin.id, note="没用过")
    _, mixed_batch = add_invite(db, "USED0001", admin.id, note="用过一个", used_by=member.id, used_at=utcnow())
    add_invite(db, "UNUSED02", admin.id, batch_id=mixed_batch)

    assert client.delete(f"/api/admin/users/{admin.id}", headers=superadmin.headers).status_code == 204

    async def _rows(s):
        batches = (await s.execute(select(InviteBatch))).scalars().all()
        codes = (await s.execute(select(InviteCode))).scalars().all()
        return [(b.id, b.created_by, b.note) for b in batches], [(c.code, c.batch_id, c.created_by) for c in codes]
    batches, codes = db(_rows)
    assert batches == [(mixed_batch, superadmin.id, "用过一个")]
    assert codes == [("USED0001", mixed_batch, superadmin.id)]
    assert unused_batch != mixed_batch


def test_superadmin_cannot_delete_or_disable_self(client, make_user):
    superadmin = make_user(UserRole.SUPERADMIN)
    assert client.delete(f"/api/admin/users/{superadmin.id}", headers=superadmin.headers).status_code == 400
    assert client.patch(f"/api/admin/users/{superadmin.id}/status", json={"is_active": False},
                        headers=superadmin.headers).status_code == 400


def test_ws_accepts_valid_token_via_subprotocol(client, make_user):
    user = make_user()
    with ws_connect(client, user.token) as ws:
        assert ws.accepted_subprotocol == "clipsync.v1"
        ws.send_text('{"type":"ping"}')
        assert ws.receive_json() == {"type": "pong"}


@pytest.mark.parametrize("protocols", [None, ["clipsync.v1"], ["clipsync.v1", "bearer.garbage"]])
def test_ws_rejects_missing_or_bad_token(client, protocols):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", subprotocols=protocols) as ws:
            ws.receive_text()


def test_ws_token_in_query_no_longer_accepted(client, make_user):
    user = make_user()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws?token={user.token}") as ws:
            ws.receive_text()


def test_ws_rejects_disabled_user(client, make_user):
    user = make_user(active=False)
    with pytest.raises(WebSocketDisconnect):
        with ws_connect(client, user.token) as ws:
            ws.receive_text()


def test_ws_receives_only_own_events(client, make_user):
    alice, bob = make_user(), make_user()
    with ws_connect(client, alice.token) as ws:
        client.put("/api/clipboard", json={"content": "bob text"}, headers=bob.headers)
        client.put("/api/clipboard", json={"content": "alice text"}, headers=alice.headers)
        msg = ws.receive_json()
        assert msg["type"] == "clipboard_updated"
        # 推送只带信号，不带正文
        assert "alice text" not in str(msg)


def test_ws_closed_when_user_disabled(client, make_user):
    superadmin = make_user(UserRole.SUPERADMIN)
    user = make_user()
    with ws_connect(client, user.token) as ws:
        resp = client.patch(f"/api/admin/users/{user.id}/status", json={"is_active": False},
                            headers=superadmin.headers)
        assert resp.status_code == 200
        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()


def test_security_headers_present(client):
    resp = client.get("/")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
