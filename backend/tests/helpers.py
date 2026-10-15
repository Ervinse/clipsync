"""测试辅助函数（无副作用，可被测试文件安全导入；不要从 conftest 导入，conftest 会被重复执行）"""
from pathlib import Path

from app.config import settings

# 与应用实际使用的存储目录保持一致（由 conftest 在导入 app 前写入环境变量）
STORAGE_ROOT = Path(settings.STORAGE_DIR).resolve()


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


def quick_login(client, full_code):
    """凭「用户名@访问码」换取快速访问凭证，返回响应（不断言状态码）"""
    return client.post("/api/access/login", json={"full_code": full_code})


def quick_headers(client, full_code):
    resp = quick_login(client, full_code)
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}
