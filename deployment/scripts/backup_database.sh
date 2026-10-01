#!/bin/bash

# ClipSync 数据库备份脚本
# 每天自动备份数据库，保留最近 30 天的备份

# pipefail：mysqldump 失败时整条管道返回非零，不会留下"看似成功"的空备份
set -eo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/var/www/clipsync}"
ENV_FILE="$PROJECT_ROOT/backend/.env"
BACKUP_DIR="/var/backups/clipsync/database"
RETENTION_DAYS=30

# cron / update.sh 调用时没有数据库环境变量，从 backend/.env 读取
# 逐行解析而不是 source，避免值里的特殊字符被 shell 执行
read_env() {
    local key="$1"
    [ -f "$ENV_FILE" ] || return 0
    grep -E "^${key}=" "$ENV_FILE" | tail -1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"
}

DB_HOST="${DB_HOST:-$(read_env DB_HOST)}"
DB_PORT="${DB_PORT:-$(read_env DB_PORT)}"
DB_USER="${DB_USER:-$(read_env DB_USER)}"
DB_PASSWORD="${DB_PASSWORD:-$(read_env DB_PASSWORD)}"
DB_NAME="${DB_NAME:-$(read_env DB_NAME)}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-3306}"

if [ -z "$DB_USER" ] || [ -z "$DB_NAME" ]; then
    echo "[$(date)] 错误: 未能从 $ENV_FILE 读取 DB_USER / DB_NAME" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/clipsync_${TIMESTAMP}.sql.gz"

# 密码写入临时配置文件传给 mysqldump，不出现在进程参数里
MYSQL_CNF=$(mktemp)
chmod 600 "$MYSQL_CNF"
trap 'rm -f "$MYSQL_CNF"' EXIT
cat > "$MYSQL_CNF" <<EOF
[client]
host=$DB_HOST
port=$DB_PORT
user=$DB_USER
password=$DB_PASSWORD
EOF

echo "[$(date)] 开始备份数据库..."

if ! mysqldump \
    --defaults-extra-file="$MYSQL_CNF" \
    --single-transaction \
    --quick \
    --lock-tables=false \
    "$DB_NAME" | gzip > "$BACKUP_FILE"; then
    rm -f "$BACKUP_FILE"
    echo "[$(date)] 错误: 备份失败，已删除不完整的备份文件" >&2
    exit 1
fi

echo "[$(date)] 备份完成: $BACKUP_FILE"
echo "[$(date)] 备份大小: $(du -h "$BACKUP_FILE" | cut -f1)"

echo "[$(date)] 清理 ${RETENTION_DAYS} 天前的旧备份..."
find "$BACKUP_DIR" -name "clipsync_*.sql.gz" -mtime +${RETENTION_DAYS} -delete

echo "[$(date)] 当前备份列表:"
ls -lh "$BACKUP_DIR"

echo "[$(date)] 备份任务完成"
