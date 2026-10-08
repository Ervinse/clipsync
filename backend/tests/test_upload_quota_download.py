"""上传配额与文件下载：取消上传释放配额、reserved_bytes、下载时文件丢失、剪贴板按字节限长"""
import pytest
from pydantic import ValidationError

from app.schemas.clipboard import ClipboardUpdate, MAX_CONTENT_BYTES
from tests.helpers import upload, STORAGE_ROOT


def _init(client, user, total_size=2048, chunk_size=1024):
    return client.post(
        "/api/files/upload/init",
        json={"original_name": "a.bin", "total_size": total_size, "chunk_size": chunk_size},
        headers=user.headers,
    )


# ---------- 取消上传 + reserved_bytes ----------

def test_cancel_other_users_upload_returns_404(client, make_user):
    alice, bob = make_user(), make_user()
    uid = _init(client, alice).json()["upload_id"]
    assert client.delete(f"/api/files/upload/{uid}", headers=bob.headers).status_code == 404
    # alice 的会话不受影响，仍可取消
    assert client.delete(f"/api/files/upload/{uid}", headers=alice.headers).status_code == 204


def test_cancel_releases_quota_and_allows_init(client, make_user):
    user = make_user(quota=3000)
    resp = _init(client, user, total_size=2500)
    assert resp.status_code == 200
    uid = resp.json()["upload_id"]

    # 会话占着 2500 字节，再开一个会超配
    assert _init(client, user, total_size=2500).status_code == 413
    assert client.get("/api/auth/me", headers=user.headers).json()["reserved_bytes"] == 2500
    assert client.get("/api/files", headers=user.headers).json()["reserved_bytes"] == 2500

    assert client.delete(f"/api/files/upload/{uid}", headers=user.headers).status_code == 204
    assert client.get("/api/auth/me", headers=user.headers).json()["reserved_bytes"] == 0
    assert _init(client, user, total_size=2500).status_code == 200


def test_cancel_removes_temp_dir(client, make_user):
    user = make_user()
    uid = _init(client, user).json()["upload_id"]
    assert (STORAGE_ROOT / "tmp" / uid).is_dir()
    client.delete(f"/api/files/upload/{uid}", headers=user.headers)
    assert not (STORAGE_ROOT / "tmp" / uid).exists()


def test_cancel_unknown_upload_returns_404(client, make_user):
    user = make_user()
    fake = "00000000-0000-4000-8000-000000000000"
    assert client.delete(f"/api/files/upload/{fake}", headers=user.headers).status_code == 404


# ---------- 下载时磁盘文件丢失 ----------

def _upload_and_lose_disk_file(client, user):
    file_id = upload(client, user, b"hello").json()["id"]
    for path in (STORAGE_ROOT / str(user.id)).iterdir():
        path.unlink()
    return file_id


def test_owner_download_missing_file_returns_404(client, make_user):
    user = make_user()
    file_id = _upload_and_lose_disk_file(client, user)
    resp = client.get(f"/api/files/{file_id}/download", headers=user.headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "文件已丢失"


def test_public_download_missing_file_does_not_reveal_code_validity(client, make_user):
    user = make_user()
    file_id = _upload_and_lose_disk_file(client, user)
    code = client.post(
        "/api/access-codes", json={"target_type": "file", "file_id": file_id}, headers=user.headers
    ).json()["code"]
    resp = client.get(f"/api/access/{code}/download")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "访问码无效或已失效"


def test_download_still_works(client, make_user):
    user = make_user()
    file_id = upload(client, user, b"x" * 3000).json()["id"]
    resp = client.get(f"/api/files/{file_id}/download", headers=user.headers)
    assert resp.status_code == 200
    assert resp.content == b"x" * 3000
    assert resp.headers["content-length"] == "3000"


# ---------- 剪贴板按 UTF-8 字节限长 ----------

def test_clipboard_limit_counts_utf8_bytes():
    # 字符数远低于上限，但 UTF-8 字节数超限（每个汉字 3 字节）
    too_long = "中" * (MAX_CONTENT_BYTES // 3 + 1)
    assert len(too_long) < MAX_CONTENT_BYTES
    with pytest.raises(ValidationError):
        ClipboardUpdate(content=too_long)


def test_clipboard_limit_allows_exact_bytes():
    ClipboardUpdate(content="a" * MAX_CONTENT_BYTES)
