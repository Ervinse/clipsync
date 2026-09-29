#!/bin/bash

# ClipSync 清理任务脚本
# 清理过期访问码和临时上传文件

set -e

# 配置
PROJECT_ROOT="/var/www/clipsync"
BACKEND_DIR="$PROJECT_ROOT/backend"
VENV_PYTHON="$BACKEND_DIR/venv/bin/python"

echo "[$(date)] 开始清理过期数据..."

cd "$BACKEND_DIR"

# 激活虚拟环境并执行清理脚本
"$VENV_PYTHON" - <<EOF
import asyncio
from datetime import datetime, timezone
from sqlalchemy import select
from app.database import async_session_maker
from app.models import AccessCode, FileUpload

async def cleanup():
    """清理过期访问码和未完成的上传"""
    async with async_session_maker() as session:
        now = datetime.now(timezone.utc)

        # 1. 清理过期访问码
        result = await session.execute(
            select(AccessCode).where(
                AccessCode.expires_at.isnot(None),
                AccessCode.expires_at < now
            )
        )
        expired_codes = result.scalars().all()

        for code in expired_codes:
            await session.delete(code)

        print(f"[{datetime.now()}] 删除 {len(expired_codes)} 个过期访问码")

        # 2. 清理 24 小时前未完成的上传记录
        from datetime import timedelta
        cutoff_time = now - timedelta(hours=24)

        result = await session.execute(
            select(FileUpload).where(
                FileUpload.status != 'completed',
                FileUpload.created_at < cutoff_time
            )
        )
        stale_uploads = result.scalars().all()

        for upload in stale_uploads:
            await session.delete(upload)

        print(f"[{datetime.now()}] 删除 {len(stale_uploads)} 个未完成的上传记录")

        await session.commit()

# 运行清理
asyncio.run(cleanup())
print(f"[{datetime.now()}] 清理完成")
EOF

# 清理临时上传文件（24 小时前的 .tmp 文件）
UPLOAD_DIR="$BACKEND_DIR/uploads"
if [ -d "$UPLOAD_DIR" ]; then
    echo "[$(date)] 清理临时上传文件..."
    find "$UPLOAD_DIR" -name "*.tmp" -mtime +1 -delete
    echo "[$(date)] 临时文件清理完成"
fi

echo "[$(date)] 清理任务全部完成"
