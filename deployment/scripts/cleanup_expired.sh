#!/bin/bash

# ClipSync 清理任务脚本
# 清理过期访问码、过期的上传会话及其临时分片目录

set -e

# 配置
PROJECT_ROOT="/var/www/clipsync"
BACKEND_DIR="$PROJECT_ROOT/backend"
VENV_PYTHON="$BACKEND_DIR/venv/bin/python"

echo "[$(date)] 开始清理过期数据..."

cd "$BACKEND_DIR"

"$VENV_PYTHON" - <<'EOF'
import asyncio
from datetime import timedelta

from sqlalchemy import select, delete

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import AccessCode, UploadSession
from app.core.storage import cleanup_upload_temp
from app.core.timeutil import utcnow


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


asyncio.run(cleanup())
EOF

echo "[$(date)] 清理任务全部完成"
