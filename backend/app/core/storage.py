"""存储管理：文件路径解析 + 目录初始化

安全红线：磁盘路径只由服务端生成的 UUID 与整数 user_id 拼接，绝不使用用户传入的文件名；
所有路径在返回前都校验确实位于 STORAGE_DIR 之内（防穿越的第二道防线）。
"""
import logging
import shutil
import uuid
from pathlib import Path

from ..config import settings

logger = logging.getLogger(__name__)


def _log_rmtree_error(func, path, exc):
    """rmtree 单个条目删除失败：记日志后继续删其余条目"""
    logger.error("删除存储路径失败 %s（%s）: %s", path, getattr(func, "__name__", func), exc)


def _base_dir() -> Path:
    return Path(settings.STORAGE_DIR).resolve()


def _is_uuid(value: str) -> bool:
    try:
        return str(uuid.UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def is_valid_upload_id(upload_id: str) -> bool:
    """
    upload_id 必须是服务端生成的标准小写 UUID。
    数据库是大小写不敏感的排序规则，大写写法能查到会话行，却过不了磁盘路径校验：
    接口入口先用本函数拦下，统一按「会话不存在」处理。
    """
    return _is_uuid(upload_id)


def _ensure_inside_base(path: Path) -> Path:
    """确认路径位于存储根目录内，否则拒绝"""
    resolved = path.resolve()
    if not resolved.is_relative_to(_base_dir()):
        raise ValueError("非法存储路径")
    return resolved


def get_user_storage_dir(user_id: int) -> Path:
    """获取用户存储目录路径"""
    return _ensure_inside_base(_base_dir() / str(int(user_id)))


def get_upload_temp_dir(upload_id: str) -> Path:
    """获取上传临时目录路径（upload_id 必须是服务端生成的 UUID）"""
    if not _is_uuid(upload_id):
        raise ValueError("非法 upload_id")
    return _ensure_inside_base(_base_dir() / "tmp" / upload_id)


def ensure_user_storage_dir(user_id: int) -> Path:
    """确保用户存储目录存在"""
    user_dir = get_user_storage_dir(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


def ensure_upload_temp_dir(upload_id: str) -> Path:
    """确保上传临时目录存在"""
    temp_dir = get_upload_temp_dir(upload_id)
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir


def get_file_path(user_id: int, stored_name: str) -> Path:
    """
    获取文件完整路径

    安全红线：stored_name 必须是 UUID，禁止用户传入名拼接路径。
    """
    if not _is_uuid(stored_name):
        raise ValueError("非法 stored_name")
    return _ensure_inside_base(get_user_storage_dir(user_id) / stored_name)


def generate_stored_name() -> str:
    """生成存储文件名（UUID）"""
    return str(uuid.uuid4())


def cleanup_upload_temp(upload_id: str):
    """清理上传临时目录"""
    try:
        temp_dir = get_upload_temp_dir(upload_id)
    except ValueError:
        return
    if temp_dir.exists():
        shutil.rmtree(temp_dir, onexc=_log_rmtree_error)


def delete_file(user_id: int, stored_name: str):
    """删除文件"""
    try:
        file_path = get_file_path(user_id, stored_name)
    except ValueError:
        return
    file_path.unlink(missing_ok=True)


def delete_user_storage(user_id: int):
    """删除用户整个存储目录（删除用户时使用）"""
    user_dir = get_user_storage_dir(user_id)
    if user_dir.exists():
        shutil.rmtree(user_dir, onexc=_log_rmtree_error)
