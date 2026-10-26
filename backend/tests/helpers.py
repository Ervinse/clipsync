"""测试辅助函数（无副作用，可被测试文件安全导入；不要从 conftest 导入，conftest 会被重复执行）"""
from pathlib import Path

from app.config import settings
from app.core.timeutil import utcnow
from app.models import InviteBatch, InviteCode

# 与应用实际使用的存储目录保持一致（由 conftest 在导入 app 前写入环境变量）
STORAGE_ROOT = Path(settings.STORAGE_DIR).resolve()


def init_upload(client, user, total_size, chunk_size=1024, name="f.bin"):
    """初始化分片上传，返回响应（不断言状态码）"""
    return client.post(
        "/api/files/upload/init",
        json={"original_name": name, "total_size": total_size, "chunk_size": chunk_size},
        headers=user.headers,
    )


def start_upload(client, user, total_size, chunk_size=1024, name="f.bin"):
    """初始化分片上传并断言成功，返回 {upload_id, total_chunks, chunk_size}"""
    resp = init_upload(client, user, total_size, chunk_size=chunk_size, name=name)
    assert resp.status_code == 200, resp.text
    return resp.json()


def post_chunk(client, user, upload_id, index, data: bytes):
    """上传一个分片，返回响应（不断言状态码）"""
    return client.post(
        "/api/files/upload/chunk",
        data={"upload_id": upload_id, "chunk_index": str(index)},
        files={"chunk_data": ("blob", data)},
        headers=user.headers,
    )


def upload(client, user, content: bytes, name="note.txt", chunk_size=1024):
    """完整走一遍三步上传，返回 complete 的响应"""
    resp = client.post(
        "/api/files/upload/init",
        json={"original_name": name, "total_size": len(content), "chunk_size": chunk_size},
        headers=user.headers,
    )
    assert resp.status_code == 200, resp.text
    info = resp.json()
    size = info["chunk_size"]
    for i in range(info["total_chunks"]):
        r = client.post(
            "/api/files/upload/chunk",
            data={"upload_id": info["upload_id"], "chunk_index": str(i)},
            files={"chunk_data": ("blob", content[i * size:(i + 1) * size])},
            headers=user.headers,
        )
        assert r.status_code == 200, r.text
    return client.post(
        "/api/files/upload/complete",
        json={"upload_id": info["upload_id"]},
        headers=user.headers,
    )


def set_clipboard(client, user, text):
    """保存云剪切板当前文本并断言成功"""
    assert client.put("/api/clipboard", json={"content": text}, headers=user.headers).status_code == 200


def ws_connect(client, token):
    """用登录凭证或快速访问凭证连 /ws（凭证走子协议，见 api/ws.py）"""
    return client.websocket_connect("/ws", subprotocols=["clipsync.v1", f"bearer.{token}"])


def set_code(client, user, target_type, target_id=None, code="mycode", expires_at=None, expect=200):
    """给内容设置访问码（code=None 为清除），返回响应 JSON"""
    resp = client.put(
        "/api/access-codes",
        json={"target_type": target_type, "target_id": target_id, "code": code, "expires_at": expires_at},
        headers=user.headers,
    )
    assert resp.status_code == expect, resp.text
    return resp.json()


def new_text(client, user, content="hello", title=""):
    resp = client.post("/api/texts", json={"title": title, "content": content}, headers=user.headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def add_invite(db, code, created_by, batch_id=None, note="", **kwargs):
    """直接写库加一个邀请码，返回 (invite_id, batch_id)；不传 batch_id 时新建一个只含这个码的批次。
    kwargs 直接传给 InviteCode（used_by / used_at / expires_at）"""
    async def _create(s):
        bid = batch_id
        if bid is None:
            batch = InviteBatch(note=note, created_by=created_by, created_at=utcnow())
            s.add(batch)
            await s.flush()
            bid = batch.id
        invite = InviteCode(batch_id=bid, code=code, created_by=created_by, created_at=utcnow(), **kwargs)
        s.add(invite)
        await s.flush()
        return invite.id, bid
    return db(_create)


def quick_login(client, full_code):
    """凭「用户名@访问码」换取快速访问凭证，返回响应（不断言状态码）"""
    return client.post("/api/access/login", json={"full_code": full_code})


def quick_headers(client, full_code):
    resp = quick_login(client, full_code)
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}
