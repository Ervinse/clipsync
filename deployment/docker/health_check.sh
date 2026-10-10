#!/bin/bash
# ClipSync 健康检查：版本、容器状态、网站与接口、数据库、磁盘、备份、HTTPS 证书
#
# 用法（root，在任意目录）：bash /opt/clipsync/health_check.sh
#   全部正常时退出码为 0，有 ✗ 项时为 1；! 是提醒，不影响退出码。
#   BACKUP_DIR 与 backup.sh 一致，默认 /var/backups/clipsync
# 不用 set -e：某项检查失败时仍要继续执行后续检查

cd "$(dirname "$(readlink -f "$0")")" || exit 1

BACKUP_DIR="${BACKUP_DIR:-/var/backups/clipsync}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'
status=0
ok()   { echo -e "  ${GREEN}✓${NC} $*"; }
bad()  { echo -e "  ${RED}✗${NC} $*"; status=1; }
warn() { echo -e "  ${YELLOW}!${NC} $*"; }

# 只读取 .env 里的普通配置项，不 source（避免执行文件内容），也不打印密码
env_value() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2-; }

echo "== 版本"
if [ -f VERSION ]; then
    sed 's/^/  部署包 /' VERSION
else
    warn "部署目录里没有 VERSION 文件"
fi
tag=$(env_value CLIPSYNC_TAG)
echo "  .env CLIPSYNC_TAG=${tag:-latest}"
running=$(docker inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' clipsync-backend 2>/dev/null)
echo "  正在运行的后端镜像提交：${running:-未知（服务器上从源码构建的镜像不带提交号）}"

echo "== 容器"
for name in clipsync-db clipsync-backend clipsync-frontend; do
    if ! state=$(docker inspect -f '{{.State.Status}}' "$name" 2>/dev/null); then
        bad "$name 不存在（docker compose up -d 启动）"
        continue
    fi
    health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$name")
    restarts=$(docker inspect -f '{{.RestartCount}}' "$name")
    if [ "$state" = "running" ] && { [ -z "$health" ] || [ "$health" = "healthy" ]; }; then
        ok "$name 运行中${health:+（$health）}"
    else
        bad "$name 状态 $state${health:+ / $health}"
    fi
    if [ "${restarts:-0}" -gt 0 ]; then
        warn "$name 自动重启过 $restarts 次，查看日志：docker compose logs --tail 100 ${name#clipsync-}"
    fi
done

echo "== 网站与接口"
port=$(env_value HTTP_PORT)
port=${port:-80}
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://127.0.0.1:$port/")
case "$code" in
    200) ok "首页 HTTP $code" ;;
    301|308) ok "首页 HTTP $code（跳转到 HTTPS）" ;;
    *) bad "首页 HTTP $code（000 表示连不上）" ;;
esac
# 未登录访问 /api/auth/me 应返回 401：说明 Nginx 能把请求转给后端，后端也在正常处理
if env_value COMPOSE_FILE | grep -q https; then
    api_url="https://127.0.0.1/api/auth/me"
else
    api_url="http://127.0.0.1:$port/api/auth/me"
fi
code=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 "$api_url")
if [ "$code" = "401" ]; then
    ok "后端接口正常（$api_url → 401 未登录）"
else
    bad "后端接口异常（$api_url → HTTP $code，正常应为 401）"
fi

echo "== 数据库"
if docker compose exec -T db sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" mysql -u "$MYSQL_USER" -e "SELECT 1" "$MYSQL_DATABASE"' >/dev/null 2>&1; then
    version=$(docker compose exec -T db mysqld --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
    ok "应用账号能连接数据库（MySQL ${version:-?}）"
else
    bad "应用账号连不上数据库"
fi

echo "== 磁盘"
docker_root=$(docker info -f '{{.DockerRootDir}}' 2>/dev/null)
for dir in / "$docker_root" "$BACKUP_DIR"; do
    [ -n "$dir" ] && [ -d "$dir" ] || continue
    # --output=pcent 只输出使用率一列，不受文件系统名里空格的影响
    usage=$(df --output=pcent "$dir" 2>/dev/null | tail -1 | tr -dc '0-9')
    [ -n "$usage" ] || { warn "$dir 读不到磁盘使用率"; continue; }
    if [ "$usage" -ge 90 ]; then
        bad "$dir 所在分区已用 ${usage}%"
    elif [ "$usage" -ge 75 ]; then
        warn "$dir 所在分区已用 ${usage}%"
    else
        ok "$dir 所在分区已用 ${usage}%"
    fi
done

echo "== 备份（$BACKUP_DIR）"
latest=$(ls -t "$BACKUP_DIR"/clipsync_db_*.sql.gz 2>/dev/null | head -1)
if [ -z "$latest" ]; then
    warn "还没有数据库备份（定时任务装好后每天自动生成，也可以手动执行 bash backup.sh）"
else
    age_days=$(( ($(date +%s) - $(stat -c %Y "$latest")) / 86400 ))
    if [ "$age_days" -gt 2 ]; then
        bad "最新的数据库备份已经是 $age_days 天前：$latest（检查 /var/log/clipsync/backup.log）"
    else
        ok "最新的数据库备份：$latest（$(du -h "$latest" | cut -f1)）"
    fi
fi

cert=letsencrypt/live/clipsync/fullchain.pem
if [ -f "$cert" ]; then
    echo "== HTTPS 证书"
    end=$(openssl x509 -enddate -noout -in "$cert" | cut -d= -f2)
    days_left=$(( ($(date -d "$end" +%s) - $(date +%s)) / 86400 ))
    if [ "$days_left" -lt 14 ]; then
        bad "证书 $days_left 天后过期（续期：bash cert.sh renew，日志 /var/log/clipsync/cert.log）"
    else
        ok "证书还有 $days_left 天过期"
    fi
fi

echo
if [ "$status" -eq 0 ]; then
    echo -e "${GREEN}检查完成：全部正常${NC}"
else
    echo -e "${RED}检查完成：有异常项（✗）${NC}"
fi
exit "$status"
