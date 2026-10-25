"""应用日志：app 下的 INFO 日志能输出；审计日志（超管查看 / 下载他人内容）与部署登记确实写出"""
import logging

from app.core.deploy_info import BuildInfo, record_deployment
from app.core.logging_setup import APP_LOGGER_NAME, setup_app_logging
from app.models import UserRole
from helpers import new_text, upload


def _app_messages(caplog):
    return [r.getMessage() for r in caplog.records if r.name.startswith(APP_LOGGER_NAME)]


def test_app_logger_outputs_info(client):
    # 导入 app.main 时已配置：不依赖根 logger（默认 WARNING、没有输出）
    logger = logging.getLogger(APP_LOGGER_NAME)
    assert logger.getEffectiveLevel() == logging.INFO
    assert logging.getLogger("app.api.admin").isEnabledFor(logging.INFO)
    assert any(getattr(h, "_clipsync_app_handler", False) for h in logger.handlers)


def test_setup_is_idempotent(client):
    setup_app_logging()
    setup_app_logging()
    handlers = [h for h in logging.getLogger(APP_LOGGER_NAME).handlers if getattr(h, "_clipsync_app_handler", False)]
    assert len(handlers) == 1


def test_superadmin_content_view_is_logged(client, make_user, caplog):
    superadmin, user = make_user(UserRole.SUPERADMIN), make_user()
    new_text(client, user, content="PRIVATE")
    caplog.clear()
    assert client.get(f"/api/admin/users/{user.id}/texts", headers=superadmin.headers).status_code == 200
    expected = f"超管查看用户内容 operator={superadmin.id} target={user.id}"
    assert any(m.startswith(expected) for m in _app_messages(caplog))
    # 日志只记操作者、对象和内容类别，不记文本本身
    assert not any("PRIVATE" in m for m in _app_messages(caplog))


def test_superadmin_download_is_logged(client, make_user, caplog):
    superadmin, user = make_user(UserRole.SUPERADMIN), make_user()
    file_id = upload(client, user, b"secret-bytes").json()["id"]
    caplog.clear()
    assert client.get(f"/api/files/{file_id}/download", headers=superadmin.headers).status_code == 200
    assert f"超管下载用户文件 operator={superadmin.id} target={user.id} file={file_id}" in _app_messages(caplog)


def test_owner_download_is_not_logged(client, make_user, caplog):
    user = make_user()
    file_id = upload(client, user, b"mine").json()["id"]
    caplog.clear()
    assert client.get(f"/api/files/{file_id}/download", headers=user.headers).status_code == 200
    assert not any(m.startswith("超管下载用户文件") for m in _app_messages(caplog))


def test_new_deployment_is_logged(db, caplog):
    build = BuildInfo(app_version="9.9.9", commit_sha="cccccccccccc", branch="master", built_at=None)

    async def _run(s):
        await record_deployment(s, build)

    caplog.clear()
    db(_run)
    assert "登记新部署 version=9.9.9 commit=cccccccccccc branch=master" in _app_messages(caplog)
