#!/bin/bash

# ClipSync 清理任务脚本
# 清理过期访问码、过期的上传会话及其临时分片目录，并扫描删除孤儿目录

set -e

# 配置
PROJECT_ROOT="/var/www/clipsync"
BACKEND_DIR="$PROJECT_ROOT/backend"
VENV_PYTHON="$BACKEND_DIR/venv/bin/python"

echo "[$(date)] 开始清理过期数据..."

cd "$BACKEND_DIR"

"$VENV_PYTHON" - <<'EOF'
import asyncio
import logging
from datetime import timedelta, timezone
from pathlib import Path

from sqlalchemy import select, delete

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import AccessCode, UploadSession, User
from app.core.storage import cleanup_upload_temp, delete_user_storage, get_upload_temp_dir
from app.core.timeutil import utcnow

# storage 模块的 rmtree 失败回调走 logging，这里让它输出到 cron 日志
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


async def cleanup():
    # 数据库时间统一为 naive UTC，用 utcnow() 比较
    now = utcnow()
    async with AsyncSessionLocal() as db:
        # 1. 过期访问码（已无法使用，直接删除）
        result = await db.execute(
            delete(AccessCode).where(
                AccessCode.expires_at.is_not(None),
                AccessCode.expires_at <= now,
            )
        )
        print(f"删除 {result.rowcount} 个过期访问码")

        # 2. 超过 TTL 的上传会话：先取 ID 用于清理临时目录，再删记录
        cutoff = now - timedelta(hours=settings.UPLOAD_SESSION_TTL_HOURS)
        result = await db.execute(
            select(UploadSession.upload_id).where(UploadSession.created_at < cutoff)
        )
        stale_ids = [row[0] for row in result.all()]
        if stale_ids:
            await db.execute(delete(UploadSession).where(UploadSession.upload_id.in_(stale_ids)))
        await db.commit()

    for upload_id in stale_ids:
        cleanup_upload_temp(upload_id)
    print(f"删除 {len(stale_ids)} 个过期上传会话及其临时分片")

    await scan_orphans(cutoff)


async def scan_orphans(cutoff):
    """
    孤儿扫描：应用内磁盘删除失败只记日志，残留目录在这里兜底清理。
    - storage/tmp/<upload_id>：mtime 早于 TTL 且不在 upload_sessions 中
    - storage/<user_id>：user_id 不在 users 表中
    只处理名字合法的目录（UUID / 纯数字），路径一律经 storage 模块解析，不越出 STORAGE_DIR。
    """
    base = Path(settings.STORAGE_DIR).resolve()
    if not base.is_dir():
        return

    async with AsyncSessionLocal() as db:
        live_uploads = {row[0] for row in (await db.execute(select(UploadSession.upload_id))).all()}
        live_users = {row[0] for row in (await db.execute(select(User.id))).all()}

    cutoff_ts = cutoff.replace(tzinfo=timezone.utc).timestamp()

    removed_tmp = 0
    tmp_root = base / "tmp"
    if tmp_root.is_dir():
        for entry in tmp_root.iterdir():
            if not entry.is_dir() or entry.name in live_uploads:
                continue
            try:
                get_upload_temp_dir(entry.name)  # 名字不是 UUID 会抛 ValueError，跳过
            except ValueError:
                continue
            if entry.stat().st_mtime >= cutoff_ts:
                continue  # 可能是刚 init、会话行尚未可见的目录，留到下次
            cleanup_upload_temp(entry.name)
            removed_tmp += 1
            print(f"删除孤儿临时目录 tmp/{entry.name}")

    removed_users = 0
    for entry in base.iterdir():
        if not entry.is_dir() or not entry.name.isdigit():
            continue
        if int(entry.name) in live_users:
            continue
        delete_user_storage(int(entry.name))
        removed_users += 1
        print(f"删除孤儿用户目录 {entry.name}/")

    print(f"孤儿扫描：删除 {removed_tmp} 个临时目录、{removed_users} 个用户目录")


asyncio.run(cleanup())
EOF

echo "[$(date)] 清理任务全部完成"
