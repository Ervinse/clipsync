"""创建首个超级管理员的交互式脚本"""
import asyncio
import getpass
import sys
from pathlib import Path

# 添加父目录到 Python 路径
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

from sqlalchemy import select
from app.database import AsyncSessionLocal, engine
from app.models import User, UserRole
from app.core.security import hash_password
from app.config import settings


async def create_superadmin():
    """交互式创建超级管理员"""
    print("=" * 50)
    print("ClipSync - Create Superadmin")
    print("=" * 50)

    # 检查是否已有超级管理员
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.role == UserRole.SUPERADMIN))
        existing_superadmin = result.scalar_one_or_none()

        if existing_superadmin:
            print(f"\n[!] Existing superadmin found: {existing_superadmin.username}")
            confirm = input("Still create new superadmin? (y/N): ").strip().lower()
            if confirm != "y":
                print("Operation cancelled.")
                return

        # 交互输入
        print("\nEnter superadmin information:")
        username = input("Username (3-64 chars): ").strip()

        if len(username) < 3 or len(username) > 64:
            print("[X] Username must be 3-64 characters.")
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

        # 创建超级管理员
        superadmin = User(
            username=username,
            password_hash=hash_password(password),
            role=UserRole.SUPERADMIN,
            quota_bytes=settings.DEFAULT_QUOTA_BYTES,
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
