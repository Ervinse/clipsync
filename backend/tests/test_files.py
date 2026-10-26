"""文件系统安全：路径穿越、分片伪造、配额绕过、下载头注入、下载类型、文件名清洗"""
import uuid

import pytest

from app.config import settings
from app.core import storage
from tests.helpers import upload, STORAGE_ROOT


def _init(client, user, total_size, chunk_size=1024, name="f.bin"):
    return client.post(
        "/api/files/upload/init",
        json={"original_name": name, "total_size": total_size, "chunk_size": chunk_size},
        headers=user.headers,
    )


def _chunk(client, user, upload_id, index, data):
    return client.post(
        "/api/files/upload/chunk",
        data={"upload_id": upload_id, "chunk_index": str(index)},
        files={"chunk_data": ("blob", data)},
        headers=user.headers,
    )


def test_upload_roundtrip_stores_under_uuid(client, make_user):
    user = make_user()
    resp = upload(client, user, b"x" * 3000, name="../../evil.txt")
    assert resp.status_code == 200
    stored = list((STORAGE_ROOT / str(user.id)).iterdir())
    assert len(stored) == 1
    uuid.UUID(stored[0].name)  # 磁盘名是 UUID，而不是用户给的名字
    assert not any(p.name == "evil.txt" for p in STORAGE_ROOT.rglob("*"))


@pytest.mark.parametrize("bad", ["../../etc/passwd", "..", "a/b", "not-a-uuid"])
def test_storage_rejects_non_uuid_names(bad):
    with pytest.raises(ValueError):
        storage.get_file_path(1, bad)
    with pytest.raises(ValueError):
        storage.get_upload_temp_dir(bad)


def test_cannot_write_into_other_users_upload(client, make_user):
    alice, bob = make_user(), make_user()
    upload_id = _init(client, alice, 100).json()["upload_id"]
    assert _chunk(client, bob, upload_id, 0, b"x" * 10).status_code == 404
    assert client.post("/api/files/upload/complete", json={"upload_id": upload_id}, headers=bob.headers).status_code == 404


def test_forged_upload_id_rejected(client, make_user):
    user = make_user()
    forged = ("../" * 12)[:36]
    assert _chunk(client, user, forged, 0, b"x").status_code == 404


def test_chunk_index_out_of_range(client, make_user):
    user = make_user()
    upload_id = _init(client, user, 100, chunk_size=100).json()["upload_id"]
    assert _chunk(client, user, upload_id, 1, b"x").status_code == 400
    assert _chunk(client, user, upload_id, -1, b"x").status_code == 422


def test_oversized_chunk_rejected(client, make_user):
    user = make_user()
    upload_id = _init(client, user, 100, chunk_size=10).json()["upload_id"]
    assert _chunk(client, user, upload_id, 0, b"x" * 50).status_code == 413
    assert not any((STORAGE_ROOT / "tmp" / upload_id).iterdir())


def test_chunk_size_is_capped_by_server(client, make_user):
    user = make_user(quota=10 * settings.CHUNK_SIZE)
    info = _init(client, user, 3 * settings.CHUNK_SIZE, chunk_size=100 * settings.CHUNK_SIZE).json()
    assert info["chunk_size"] == settings.CHUNK_SIZE


def test_declared_size_mismatch_rejected(client, make_user):
    user = make_user()
    upload_id = _init(client, user, 20, chunk_size=10).json()["upload_id"]
    assert _chunk(client, user, upload_id, 0, b"x" * 10).status_code == 200
    # 分片大小按索引校验：最后一片应为 10 字节，5 字节当场拒绝，不落盘
    assert _chunk(client, user, upload_id, 1, b"x" * 5).status_code == 400
    resp = client.post("/api/files/upload/complete", json={"upload_id": upload_id}, headers=user.headers)
    assert resp.status_code == 400
    assert client.get("/api/files", headers=user.headers).json()["total"] == 0
    # 重传正确大小的分片后可以正常完成
    assert _chunk(client, user, upload_id, 1, b"x" * 10).status_code == 200
    resp = client.post("/api/files/upload/complete", json={"upload_id": upload_id}, headers=user.headers)
    assert resp.status_code == 200
    assert resp.json()["size"] == 20


def test_pending_uploads_count_toward_quota(client, make_user):
    user = make_user(quota=2000)
    assert _init(client, user, 1500).status_code == 200
    # 第一个会话未完成，但已占用配额
    assert _init(client, user, 1000).status_code == 413


def test_upload_session_count_limited(client, make_user):
    user = make_user()
    for _ in range(settings.MAX_UPLOAD_SESSIONS_PER_USER):
        assert _init(client, user, 10).status_code == 200
    assert _init(client, user, 10).status_code == 429


def test_quota_enforced(client, make_user):
    user = make_user(quota=100)
    assert _init(client, user, 101).status_code == 413


def test_content_disposition_header_injection(client, make_user):
    user = make_user()
    name = 'a".txt\r\nX-Evil: 1'
    file_id = upload(client, user, b"data", name=name).json()["id"]
    resp = client.get(f"/api/files/{file_id}/download", headers=user.headers)
    assert resp.status_code == 200
    assert "x-evil" not in {k.lower() for k in resp.headers.keys()}
    disposition = resp.headers["content-disposition"]
    assert "\r" not in disposition and "\n" not in disposition
    assert "filename*=UTF-8''" in disposition
    assert resp.headers["x-content-type-options"] == "nosniff"


def test_unicode_filename_download(client, make_user):
    user = make_user()
    file_id = upload(client, user, b"data", name="报告 2024.pdf").json()["id"]
    disposition = client.get(f"/api/files/{file_id}/download", headers=user.headers).headers["content-disposition"]
    assert disposition.isascii()


@pytest.mark.parametrize("name", ["page.html", "image.svg", "note.txt", "noext"])
def test_download_is_always_an_octet_stream(client, make_user, name):
    """用户能上传 .html / .svg：下载一律按二进制流下发，浏览器不会把它当页面解析；列表里的 mime_type 照常显示"""
    user = make_user()
    uploaded = upload(client, user, b"<script>alert(1)</script>", name=name).json()
    resp = client.get(f"/api/files/{uploaded['id']}/download", headers=user.headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/octet-stream"
    assert resp.headers["content-disposition"].startswith("attachment;")
    assert resp.headers["x-content-type-options"] == "nosniff"
    listed = client.get("/api/files", headers=user.headers).json()["items"][0]
    assert listed["mime_type"] == uploaded["mime_type"]


def test_filename_drops_direction_and_zero_width_characters(client, make_user):
    """方向控制符能把 invoice<U+202E>fdp.exe 显示成 invoiceexe.pdf，零宽字符能让两个文件名看起来一样：入库前删掉"""
    user = make_user()
    assert upload(client, user, b"data", name="invoice‮fdp.exe").json()["original_name"] == "invoicefdp.exe"
    assert upload(client, user, b"data", name="re​port﻿.pdf").json()["original_name"] == "report.pdf"


def test_sanitize_filename_keeps_legitimate_characters():
    from app.core.http_utils import sanitize_filename
    assert sanitize_filename("报告 2024.pdf") == "报告 2024.pdf"
    assert sanitize_filename("👨‍👩‍👧.png") == "👨‍👩‍👧.png"  # emoji 组合序列用的零宽连接符保留
    assert sanitize_filename("می‌خواهم.txt") == "می‌خواهم.txt"            # 波斯语用的零宽非连接符保留
    assert sanitize_filename("a\x85b c d.txt") == "a_b_c_d.txt"
    assert sanitize_filename("‮​") == "file"
    assert "/" not in sanitize_filename("../../evil.txt") and "\\" not in sanitize_filename("..\\evil.txt")
