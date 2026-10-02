#!/bin/bash

# ClipSync 清理任务脚本
# 清理过期访问码、过期的上传会话及其临时分片目录，并扫描删除孤儿目录
# 清理逻辑在 backend/scripts/cleanup_expired.py，Docker 部署直接在容器内调用同一模块

set -e

# 配置
PROJECT_ROOT="/var/www/clipsync"
BACKEND_DIR="$PROJECT_ROOT/backend"
VENV_PYTHON="$BACKEND_DIR/venv/bin/python"

echo "[$(date)] 开始清理过期数据..."

cd "$BACKEND_DIR"
"$VENV_PYTHON" -m scripts.cleanup_expired

echo "[$(date)] 清理任务全部完成"
