"""创建首个超级管理员的交互式脚本"""
import asyncio
import getpass
import sys
from pathlib import Path

# 添加父目录到 Python 路径
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

import re

from sqlalchemy import select
from app.database import AsyncSessionLocal, engine
from app.models import User, UserRole
from app.core.security import hash_password
from app.core.app_settings import get_default_quota_bytes
from app.schemas.user import USERNAME_PATTERN


def username_error(username: str) -> str | None:
    """用户名不合规返回原因，合规返回 None；规则与注册接口一致（长度 3–64，只含字母、数字与 _ . -）"""
    if len(username) < 3 or len(username) > 64:
        return "Username must be 3-64 characters."
    if not re.fullmatch(USERNAME_PATTERN, username):
        return "Username may only contain letters, digits, and _ . - (no '@' or spaces)."
    return None


async def find_existing_superadmin(db):
    """返回任意一个已有的超级管理员（没有则 None）；可能已有多个，不能要求结果唯一"""
    result = await db.execute(
        select(User).where(User.role == UserRole.SUPERADMIN).order_by(User.id).limit(1)
    )
    return result.scalars().first()


async def create_superadmin():
    """交互式创建超级管理员"""
    print("=" * 50)
    print("ClipSync - Create Superadmin")
    print("=" * 50)

    # 检查是否已有超级管理员
    async with AsyncSessionLocal() as db:
        existing_superadmin = await find_existing_superadmin(db)

        if existing_superadmin:
            print(f"\n[!] Existing superadmin found: {existing_superadmin.username}")
            confirm = input("Still create new superadmin? (y/N): ").strip().lower()
            if confirm != "y":
                print("Operation cancelled.")
                return

        # 交互输入
        print("\nEnter superadmin information:")
        username = input("Username (3-64 chars; letters, digits, _ . -): ").strip()

        error = username_error(username)
        if error:
            print(f"[X] {error}")
            return

        # 检查用户名是否已存在
        result = await db.execute(select(User).where(User.username == username))
        if result.scalar_one_or_none():
            print(f"[X] Username '{username}' already exists.")
            return

        # getpass：密码不回显到终端
        password = getpass.getpass("Password (8+ chars, max 72 bytes): ")
        if len(password) < 8:
            print("[X] Password must be at least 8 characters.")
            return
        if len(password.encode("utf-8")) > 72:
            print("[X] Password must not exceed 72 bytes.")
            return

        password_confirm = getpass.getpass("Confirm password: ")
        if password != password_confirm:
            print("[X] Passwords do not match.")
            return

        # 创建超级管理员；配额与注册一致，取后台「新用户默认配额」
        superadmin = User(
            username=username,
            password_hash=hash_password(password),
            role=UserRole.SUPERADMIN,
            quota_bytes=await get_default_quota_bytes(db),
            is_active=True,
        )

        db.add(superadmin)
        await db.commit()
        await db.refresh(superadmin)

        print("\n" + "=" * 50)
        print("[OK] Superadmin created successfully!")
        print("=" * 50)
        print(f"ID: {superadmin.id}")
        print(f"Username: {superadmin.username}")
        print(f"Role: {superadmin.role.value}")
        print(f"Quota: {superadmin.quota_bytes // (1024 * 1024)} MB")
        print("\nYou can now login with this account.")


async def _run():
    try:
        await create_superadmin()
    finally:
        # 事件循环关闭前释放连接池，否则退出时 aiomysql 会打印 "Event loop is closed"
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print("\n\nOperation cancelled.")
    except Exception as e:
        print(f"\n[X] Creation failed: {e}")
        sys.exit(1)
