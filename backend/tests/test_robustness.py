"""边界与容错：WebSocket 失败连接的关闭、upload_id 写法、分片 IO 错误与目录并发删除、多个超管与超管用户名规则、
孤立代理字符的校验错误响应、文本上限与 Nginx 请求体上限的关系"""
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
from scripts.create_superadmin import find_existing_superadmin, username_error


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


@pytest.mark.parametrize("name", ["admin", "Admin_01", "a.b-c", "x" * 64])
def test_superadmin_username_accepts_registration_charset(name):
    assert username_error(name) is None


@pytest.mark.parametrize("name", ["ab", "x" * 65, "admin@home", "has space", "中文名字", "a/b"])
def test_superadmin_username_rejects_what_registration_rejects(name):
    """含 @ 的用户名会让「用户名@访问码」无法拆分，超管用户名与注册接口遵守同一条规则"""
    assert username_error(name)


# ---------- 校验错误响应 ----------

def test_lone_surrogate_in_body_is_422_not_500(client, make_user):
    """JSON 里的孤立代理字符（"\\ud800"）无法编码成 UTF-8：校验错误的响应不能回传原始输入，否则变 500"""
    user = make_user()
    headers = {**user.headers, "Content-Type": "application/json"}
    for path, body in (
        ("/api/texts", '{"title":"\\ud800","content":"x"}'),
        ("/api/clipboard", '{"content":"\\ud800"}'),
        ("/api/files/upload/init", '{"original_name":"\\ud800.txt","total_size":5,"chunk_size":5}'),
    ):
        method = client.put if path == "/api/clipboard" else client.post
        resp = method(path, content=body, headers=headers)
        assert resp.status_code == 422, (path, resp.status_code)

    # 免登录入口同样不能 500
    resp = client.post(
        "/api/access/login", content='{"full_code":"\\ud800@abcd"}', headers={"Content-Type": "application/json"}
    )
    assert resp.status_code == 422


def test_validation_error_does_not_echo_input(client):
    """422 详情只含 type / loc / msg，不把客户端提交的内容（如密码）原样返回"""
    bad = client.post("/api/auth/register", json={"username": "ab", "password": "pw-secret-123", "invite_code": "x"})
    assert bad.status_code == 422
    for item in bad.json()["detail"]:
        assert set(item) == {"type", "loc", "msg"}
    assert "pw-secret-123" not in bad.text


# ---------- 剪贴板文本上限 ----------

def test_clipboard_limit_is_below_nginx_body_limit():
    conf = Path(__file__).resolve().parents[2] / "deployment" / "docker" / "nginx-common.conf"
    if not conf.exists():
        pytest.skip("没有部署目录（如在镜像内运行）")
    match = re.search(r"^client_max_body_size\s+(\d+)m;", conf.read_text(encoding="utf-8"), re.M)
    assert match, "nginx-common.conf 里没找到 client_max_body_size"
    # 超过 Nginx 上限的请求到不了后端（用户只看到 Nginx 的英文 413 页）。请求体是 JSON：
    # 换行、制表符、引号、反斜杠转义后占 2 字节，所以上限的 2 倍加上 JSON 外壳也要小于 Nginx 的上限
    assert MAX_CONTENT_BYTES * 2 + 1024 < int(match.group(1)) * 1024 * 1024


def test_chunk_size_must_fit_under_nginx_body_limit():
    """CHUNK_SIZE 填大了，上传会在 Nginx 被 413 拒绝：启动时就报清楚的错"""
    from pydantic import ValidationError
    from app.config import MAX_CHUNK_SIZE, Settings

    assert Settings(CHUNK_SIZE=MAX_CHUNK_SIZE).CHUNK_SIZE == MAX_CHUNK_SIZE
    for bad in (MAX_CHUNK_SIZE + 1, 10 * 1024 * 1024, 0, -1):
        with pytest.raises(ValidationError, match="CHUNK_SIZE"):
            Settings(CHUNK_SIZE=bad)
    conf = Path(__file__).resolve().parents[2] / "deployment" / "docker" / "nginx-common.conf"
    if conf.exists():
        match = re.search(r"^client_max_body_size\s+(\d+)m;", conf.read_text(encoding="utf-8"), re.M)
        assert MAX_CHUNK_SIZE < int(match.group(1)) * 1024 * 1024


def test_api_responses_carry_a_restrictive_csp(client, make_user):
    """接口响应不是页面：不允许加载任何资源、不允许被嵌入（成功与失败的响应都带）"""
    user = make_user()
    expected = "default-src 'none'; frame-ancestors 'none'"
    assert client.get("/api/auth/me", headers=user.headers).headers["content-security-policy"] == expected
    assert client.get("/api/auth/me").headers["content-security-policy"] == expected


# ---------- 部署配置：Nginx 内容安全策略 ----------

DOCKER_DIR = Path(__file__).resolve().parents[2] / "deployment" / "docker"


def _nginx_locations():
    """nginx-common.conf 里每个 location 块：{开头那一行: 块内容}"""
    conf = DOCKER_DIR / "nginx-common.conf"
    if not conf.exists():
        pytest.skip("没有部署目录（如在镜像内运行）")
    text = conf.read_text(encoding="utf-8")
    blocks = re.findall(r"^(location [^\n{]+)\{(.*?)^\}", text, re.M | re.S)
    assert len(blocks) >= 5, "没有解析出 location 块"
    return {head.strip(): body for head, body in blocks}


def test_every_static_location_repeats_all_security_headers():
    """Nginx 的 add_header 在子 location 里会覆盖外层的、不继承：每个自己写了 add_header 的静态 location 都要写全"""
    required = ["X-Frame-Options", "X-Content-Type-Options", "Referrer-Policy", "Content-Security-Policy"]
    checked = 0
    for head, body in _nginx_locations().items():
        if "add_header" not in body:
            continue
        checked += 1
        for header in required:
            assert header in body, f"{head} 缺少 {header}"
    assert checked >= 4  # /、/index.html、/assets/、ACME 验证路径


def test_nginx_csp_blocks_inline_scripts_and_embedding():
    text = (DOCKER_DIR / "nginx-common.conf").read_text(encoding="utf-8") if DOCKER_DIR.exists() else ""
    if not text:
        pytest.skip("没有部署目录（如在镜像内运行）")
    csp = re.search(r'^set \$csp "([^"]+)";', text, re.M)
    assert csp, "没有找到 set $csp"
    policy = csp.group(1)
    assert "default-src 'self'" in policy and "frame-ancestors 'none'" in policy and "object-src 'none'" in policy
    script_src = re.search(r"script-src ([^;]+);", policy).group(1)
    assert script_src.strip() == "'self'", "script-src 不能放行内联脚本"
    assert "ws:" in policy and "wss:" in policy  # 部分浏览器的 'self' 不含同源 WebSocket


def test_index_html_has_no_inline_script():
    """CSP 的 script-src 'self' 会挡掉内联脚本：index.html 里只能有带 src 的脚本"""
    index = Path(__file__).resolve().parents[2] / "frontend" / "index.html"
    if not index.exists():
        pytest.skip("没有前端目录（如在镜像内运行）")
    for tag in re.findall(r"<script\b([^>]*)>(.*?)</script>", index.read_text(encoding="utf-8"), re.S):
        attrs, body = tag
        assert "src=" in attrs and not body.strip(), f"index.html 有内联脚本：{attrs} {body[:40]}"
    assert (index.parent / "public" / "theme-init.js").exists()


def test_backend_uvicorn_commands_agree_and_limit_ws_frame_size():
    """Dockerfile 的默认 CMD 与 compose 的 command 对代理头、WebSocket 帧大小的设置一致"""
    dockerfile = DOCKER_DIR / "Dockerfile.backend"
    compose = DOCKER_DIR / "docker-compose.yml"
    if not dockerfile.exists():
        pytest.skip("没有部署目录（如在镜像内运行）")
    for name, text in (("Dockerfile.backend", dockerfile.read_text(encoding="utf-8")),
                       ("docker-compose.yml", compose.read_text(encoding="utf-8"))):
        assert "--forwarded-allow-ips" in text and "172.28.0.0/16" in text, name
        assert "--ws-max-size 4096" in text or '"--ws-max-size", "4096"' in text, name


def test_escape_heavy_text_at_the_limit_fits_in_one_request(client, make_user):
    """全是换行的文本在上限处：JSON 里每个换行占 2 字节，请求体约 8MB，仍低于 Nginx 的 10MB"""
    user = make_user()
    body = "\n" * MAX_CONTENT_BYTES
    resp = client.put("/api/clipboard", json={"content": body}, headers=user.headers)
    assert resp.status_code == 200
    assert len(resp.request.content) < 10 * 1024 * 1024
    too_big = client.put("/api/clipboard", json={"content": body + "x"}, headers=user.headers)
    assert too_big.status_code == 422 and "4MB" in too_big.text
