"""边界与容错：WebSocket 失败连接的关闭、upload_id 写法、分片 IO 错误与目录并发删除、多个超管、文本上限与 Nginx 请求体上限的关系"""
import asyncio
import re
import time
from pathlib import Path

import pytest

from app.api.files import _save_chunk
from app.core import ws_manager as ws_module
from app.core.ws_manager import ConnectionManager
from app.models import UserRole
from app.schemas.clipboard import MAX_CONTENT_BYTES
from scripts.create_superadmin import find_existing_superadmin


class _FakeSocket:
    """只实现 ConnectionManager 用到的 send_text / close"""

    def __init__(self, send_error=None, hang_on_close=False):
        self.send_error = send_error
        self.hang_on_close = hang_on_close
        self.sent = []
        self.closed_with = None

    async def send_text(self, text):
        if self.send_error:
            raise self.send_error
        self.sent.append(text)

    async def close(self, code=1000):
        if self.hang_on_close:
            await asyncio.sleep(60)
        self.closed_with = code


def _init_upload(client, user, total_size=100):
    resp = client.post(
        "/api/files/upload/init",
        json={"original_name": "f.bin", "total_size": total_size, "chunk_size": 1024},
        headers=user.headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["upload_id"]


def _post_chunk(client, user, upload_id, index, data):
    return client.post(
        "/api/files/upload/chunk",
        data={"upload_id": upload_id, "chunk_index": str(index)},
        files={"chunk_data": ("blob", data)},
        headers=user.headers,
    )


# ---------- WebSocket ----------

def test_broadcast_closes_connection_that_failed_to_send():
    # 只摘掉不关闭的话，接收循环仍在回心跳，客户端以为连接正常、不会重连，之后再也收不到推送
    manager = ConnectionManager()
    live = _FakeSocket()
    dead = _FakeSocket(send_error=RuntimeError("broken pipe"))
    manager.register(1, live)
    manager.register(1, dead)

    asyncio.run(manager.broadcast_to_user(1, {"type": "clipboard_updated", "data": {}}))

    assert len(live.sent) == 1 and live.closed_with is None
    assert dead.closed_with is not None
    assert manager.active_connections[1] == {live}


def test_slow_close_does_not_block_disconnect_user(monkeypatch):
    monkeypatch.setattr(ws_module, "SEND_TIMEOUT_SECONDS", 0.05)
    manager = ConnectionManager()
    stuck = _FakeSocket(hang_on_close=True)
    manager.register(1, stuck)

    started = time.monotonic()
    asyncio.run(manager.disconnect_user(1))

    assert time.monotonic() - started < 2
    assert 1 not in manager.active_connections


# ---------- 分片上传 ----------

def test_non_canonical_upload_id_is_404_everywhere(client, make_user):
    # 数据库排序规则不区分大小写，大写写法能查到会话行，必须在入口按「会话不存在」拦下
    user = make_user()
    upload_id = _init_upload(client, user)
    upper = upload_id.upper()
    assert upper != upload_id

    assert _post_chunk(client, user, upper, 0, b"x" * 100).status_code == 404
    resp = client.post("/api/files/upload/complete", json={"upload_id": upper}, headers=user.headers)
    assert resp.status_code == 404
    assert client.delete(f"/api/files/upload/{upper}", headers=user.headers).status_code == 404

    # 原会话不受影响
    assert _post_chunk(client, user, upload_id, 0, b"x" * 100).status_code == 200
    resp = client.post("/api/files/upload/complete", json={"upload_id": upload_id}, headers=user.headers)
    assert resp.status_code == 200


def test_chunk_is_404_when_temp_dir_vanishes_after_write(client, make_user, monkeypatch):
    user = make_user()
    upload_id = _init_upload(client, user)

    def vanished(_temp_dir):
        raise FileNotFoundError

    monkeypatch.setattr("app.api.files._count_chunks", vanished)
    assert _post_chunk(client, user, upload_id, 0, b"x" * 100).status_code == 404


def test_save_chunk_removes_partial_file_on_io_error(tmp_path):
    class _Source:
        calls = 0

        def read(self, _size):
            self.calls += 1
            if self.calls == 1:
                return b"x" * 10
            raise OSError(28, "No space left on device")

    partial = tmp_path / "0.part"
    with pytest.raises(OSError):
        _save_chunk(_Source(), partial, 1000)
    assert not partial.exists()


# ---------- 创建超管脚本 ----------

def test_find_existing_superadmin_with_several_superadmins(client, make_user, db):
    async def _find(session):
        user = await find_existing_superadmin(session)
        return user.id if user else None

    assert db(_find) is None
    first = make_user(UserRole.SUPERADMIN)
    make_user(UserRole.SUPERADMIN)
    assert db(_find) == first.id


# ---------- 剪贴板文本上限 ----------

def test_clipboard_limit_is_below_nginx_body_limit():
    conf = Path(__file__).resolve().parents[2] / "deployment" / "docker" / "nginx-common.conf"
    if not conf.exists():
        pytest.skip("没有部署目录（如在镜像内运行）")
    match = re.search(r"^client_max_body_size\s+(\d+)m;", conf.read_text(encoding="utf-8"), re.M)
    assert match, "nginx-common.conf 里没找到 client_max_body_size"
    # 超过 Nginx 上限的请求到不了后端；请求体还含 JSON 外壳与转义，文本上限必须明显更小
    assert MAX_CONTENT_BYTES < int(match.group(1)) * 1024 * 1024
