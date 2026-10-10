#!/bin/bash
# ClipSync 备份：数据库（mysqldump）与上传的文件（数据卷 clipsync_storage_data）
#
# 用法（root，在任意目录）：bash /opt/clipsync/backup.sh
#   脚本会切换到自己所在的部署目录执行 docker compose，需要 db、backend 容器在运行。
#   BACKUP_DIR       备份目录，默认 /var/backups/clipsync
#   DB_KEEP_DAYS     数据库备份保留天数，默认 30
#   FILES_KEEP_DAYS  文件备份保留天数，默认 7（文件备份是全量的，占用空间较大）
# 宿主机 cron 每天调用（见 clipsync.cron）。恢复步骤见 DEPLOYMENT.md「备份与恢复」。

set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

BACKUP_DIR="${BACKUP_DIR:-/var/backups/clipsync}"
DB_KEEP_DAYS="${DB_KEEP_DAYS:-30}"
FILES_KEEP_DAYS="${FILES_KEEP_DAYS:-7}"

log() { echo "[$(date '+%F %T')] $*"; }
fail() { log "错误: $*" >&2; exit 1; }

# 备份里有明文的剪贴板内容和用户文件：目录和文件只允许 root 读写
umask 077
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

ts=$(date +%Y%m%d_%H%M%S)

# 先写到 .part，校验通过后才改成正式文件名：中途失败不会留下看似正常的备份
db_file="$BACKUP_DIR/clipsync_db_$ts.sql.gz"
log "备份数据库 → $db_file"
# 用户名、密码、库名取容器内由 compose 注入的变量（外层单引号，变量在容器里展开），宿主机不需要知道密码。
# --no-tablespaces：导出表空间信息需要全局 PROCESS 权限，应用账号只有本库权限；本项目没有自定义表空间
if ! docker compose exec -T db sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" exec mysqldump -u "$MYSQL_USER" --single-transaction --quick --no-tablespaces "$MYSQL_DATABASE"' \
        | gzip > "$db_file.part"; then
    rm -f "$db_file.part"
    fail "mysqldump 失败，已删除不完整的备份"
fi
# mysqldump 正常结束时最后一行是 "-- Dump completed on ..."
if ! gzip -dc "$db_file.part" | tail -n 1 | grep -q '^-- Dump completed'; then
    rm -f "$db_file.part"
    fail "数据库备份不完整，已删除"
fi
mv "$db_file.part" "$db_file"
log "数据库备份完成（$(du -h "$db_file" | cut -f1)）"

files_file="$BACKUP_DIR/clipsync_files_$ts.tar.gz"
log "备份上传的文件 → $files_file"
# 在 backend 容器里打包 /app/storage，跳过 tmp/（未完成的上传分片）。
# tar 退出码 1 表示打包时有文件正在变化（有人在上传或删除），不影响其余文件，按成功处理
if ! docker compose exec -T backend sh -c 'tar -czf - -C /app/storage --exclude=./tmp --warning=no-file-changed .; [ $? -le 1 ]' \
        > "$files_file.part"; then
    rm -f "$files_file.part"
    fail "文件打包失败，已删除不完整的备份"
fi
if ! gzip -t "$files_file.part"; then
    rm -f "$files_file.part"
    fail "文件备份校验失败，已删除"
fi
mv "$files_file.part" "$files_file"
log "文件备份完成（$(du -h "$files_file" | cut -f1)）"

log "删除超过保留期的旧备份"
find "$BACKUP_DIR" -maxdepth 1 -name 'clipsync_db_*.sql.gz' -mtime +"$DB_KEEP_DAYS" -print -delete
find "$BACKUP_DIR" -maxdepth 1 -name 'clipsync_files_*.tar.gz' -mtime +"$FILES_KEEP_DAYS" -print -delete
# 被强行中断的备份留下的半成品
find "$BACKUP_DIR" -maxdepth 1 -name 'clipsync_*.part' -mmin +60 -print -delete

log "备份完成。备份和服务器在同一块硬盘上，请定期复制到其他机器"
