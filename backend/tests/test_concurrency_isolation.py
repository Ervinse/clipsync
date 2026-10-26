"""分片上传的并发与一致性：

- 分片提交用显式 UPDATE + rowcount 校验：会话被并发删除时返回 404 并清理临时目录；
  重传已存在分片（received_chunks 不变）仍返回 200（MySQL 方言 FOUND_ROWS，匹配行数而非改动行数）。
- 写盘 / 原子替换期间临时目录被并发 rmtree：捕获 FileNotFoundError 统一按会话已结束处理（404）。

剪贴板写入、init_upload、删除用户在 REPEATABLE READ 下「先 commit 结束鉴权读视图再加行锁」的串行化，
依赖真实并行连接才能触发竞态，单事件循环的 TestClient 无法复现，由其他端到端用例覆盖正常路径。
"""
import shutil

from sqlalchemy import delete as sql_delete

from app.api import files as files_api
from app.models import UploadSession
from tests.helpers import start_upload, post_chunk


# ---------- 显式 UPDATE + rowcount ----------

def test_retransmit_same_chunk_still_succeeds(client, make_user):
    """重传已落盘的分片：received_chunks 不变，显式 UPDATE 靠 FOUND_ROWS 仍匹配 1 行，返回 200 不误判为 404。"""
    user = make_user()
    info = start_upload(client, user, 2048)
    uid = info["upload_id"]

    r1 = post_chunk(client, user, uid, 0, b"x" * 1024)
    assert r1.status_code == 200 and r1.json()["received_chunks"] == 1

    r2 = post_chunk(client, user, uid, 0, b"x" * 1024)
    assert r2.status_code == 200 and r2.json()["received_chunks"] == 1


def test_chunk_404_when_session_deleted_during_write(client, db, make_user, monkeypatch):
    """模拟写盘后、UPDATE 前会话被并发删除：rowcount==0 时返回 404 并清理临时目录。"""
    user = make_user()
    info = start_upload(client, user, 10)
    uid = info["upload_id"]

    orig = files_api._count_chunks

    def spy(temp_dir):
        n = orig(temp_dir)

        async def _del(s):
            await s.execute(sql_delete(UploadSession).where(UploadSession.upload_id == uid))

        db(_del)  # 在线程池里借 portal 回主循环删除会话行，制造 UPDATE 命中 0 行的竞态
        return n

    monkeypatch.setattr(files_api, "_count_chunks", spy)

    resp = post_chunk(client, user, uid, 0, b"x" * 10)
    assert resp.status_code == 404
    assert not files_api.get_upload_temp_dir(uid).exists()  # 临时目录已被清理，不留孤儿


# ---------- 临时目录被并发清理 ----------

def test_chunk_404_when_write_hits_missing_dir(client, make_user, monkeypatch):
    """写盘时临时目录已不存在：_save_chunk 抛 FileNotFoundError，按会话已结束返回 404。"""
    user = make_user()
    info = start_upload(client, user, 10)
    uid = info["upload_id"]

    def boom(*args, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(files_api, "_save_chunk", boom)

    resp = post_chunk(client, user, uid, 0, b"x" * 10)
    assert resp.status_code == 404


def test_chunk_404_when_tempdir_removed_before_replace(client, make_user, monkeypatch):
    """写完分片、原子替换前临时目录被 rmtree：partial_path.replace 抛 FileNotFoundError，返回 404。"""
    user = make_user()
    info = start_upload(client, user, 10)
    uid = info["upload_id"]

    orig = files_api._save_chunk

    def wrapper(src, partial_path, limit):
        written = orig(src, partial_path, limit)
        shutil.rmtree(files_api.get_upload_temp_dir(uid), ignore_errors=True)  # 并发清理
        return written

    monkeypatch.setattr(files_api, "_save_chunk", wrapper)

    resp = post_chunk(client, user, uid, 0, b"x" * 10)
    assert resp.status_code == 404
