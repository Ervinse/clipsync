#!/bin/bash

# ClipSync 数据库备份脚本
# 每天自动备份数据库，保留最近 30 天的备份

set -e

# 配置
BACKUP_DIR="/var/backups/clipsync/database"
DB_USER="${DB_USER:-clipsync}"
DB_PASSWORD="${DB_PASSWORD}"
DB_HOST="${DB_HOST:-localhost}"
DB_NAME="${DB_NAME:-clipsync}"
RETENTION_DAYS=30

# 创建备份目录
mkdir -p "$BACKUP_DIR"

# 生成备份文件名（带时间戳）
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/clipsync_${TIMESTAMP}.sql.gz"

echo "[$(date)] 开始备份数据库..."

# 执行备份
mysqldump \
    --host="$DB_HOST" \
    --user="$DB_USER" \
    --password="$DB_PASSWORD" \
    --single-transaction \
    --quick \
    --lock-tables=false \
    "$DB_NAME" | gzip > "$BACKUP_FILE"

echo "[$(date)] 备份完成: $BACKUP_FILE"

# 显示备份文件大小
BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "[$(date)] 备份大小: $BACKUP_SIZE"

# 清理旧备份（保留最近 N 天）
echo "[$(date)] 清理 ${RETENTION_DAYS} 天前的旧备份..."
find "$BACKUP_DIR" -name "clipsync_*.sql.gz" -mtime +${RETENTION_DAYS} -delete

# 显示当前备份列表
echo "[$(date)] 当前备份列表:"
ls -lh "$BACKUP_DIR"

echo "[$(date)] 备份任务完成"
