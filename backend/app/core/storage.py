"""存储管理：文件路径解析 + 目录初始化"""
import os
import shutil
import uuid
from pathlib import Path

from ..config import settings


def get_user_storage_dir(user_id: int) -> Path:
    """获取用户存储目录路径"""
    base_dir = Path(settings.STORAGE_DIR)
    user_dir = base_dir / str(user_id)
    return user_dir


def get_upload_temp_dir(upload_id: str) -> Path:
    """获取上传临时目录路径"""
    base_dir = Path(settings.STORAGE_DIR)
    temp_dir = base_dir / "tmp" / upload_id
    return temp_dir


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
    user_dir = get_user_storage_dir(user_id)
    return user_dir / stored_name


def generate_stored_name() -> str:
    """生成存储文件名（UUID）"""
    return str(uuid.uuid4())


def cleanup_upload_temp(upload_id: str):
    """清理上传临时目录"""
    temp_dir = get_upload_temp_dir(upload_id)
    if temp_dir.exists():
        shutil.rmtree(temp_dir)


def delete_file(user_id: int, stored_name: str):
    """删除文件"""
    file_path = get_file_path(user_id, stored_name)
    if file_path.exists():
        file_path.unlink()
