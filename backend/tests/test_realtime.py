"""实时同步：删除历史、访问码增删、管理员改配额都要推送信号（不带正文）"""
from app.models import UserRole


def _ws(client, token):
    return client.websocket_connect("/ws", subprotocols=["clipsync.v1", f"bearer.{token}"])


def test_delete_history_broadcasts_clipboard_updated(client, make_user):
    user = make_user()
    client.put("/api/clipboard", json={"content": "a"}, headers=user.headers)
    client.put("/api/clipboard", json={"content": "b"}, headers=user.headers)
    [entry] = client.get("/api/clipboard/history", headers=user.headers).json()["items"]

    with _ws(client, user.token) as ws:
        resp = client.delete(f"/api/clipboard/history/{entry['id']}", headers=user.headers)
        assert resp.status_code == 204
        msg = ws.receive_json()
        assert msg["type"] == "clipboard_updated"
        assert "a" not in str(msg["data"])  # 只发信号，不带正文


def test_access_code_create_and_revoke_broadcast(client, make_user):
    user = make_user()
    with _ws(client, user.token) as ws:
        resp = client.post("/api/access-codes", json={"target_type": "text"}, headers=user.headers)
        assert resp.status_code == 200
        assert ws.receive_json()["type"] == "access_codes_changed"

        resp = client.delete(f"/api/access-codes/{resp.json()['id']}", headers=user.headers)
        assert resp.status_code == 204
        assert ws.receive_json()["type"] == "access_codes_changed"


def test_quota_update_broadcasts_to_target_user(client, make_user):
    superadmin, user = make_user(UserRole.SUPERADMIN), make_user()
    with _ws(client, user.token) as ws:
        resp = client.patch(f"/api/admin/users/{user.id}/quota",
                            json={"quota_bytes": 1024 * 1024}, headers=superadmin.headers)
        assert resp.status_code == 200
        msg = ws.receive_json()
        assert msg == {"type": "quota_updated", "data": {"quota_bytes": 1024 * 1024}}
