#!/bin/bash

# ClipSync 健康检查脚本
# 检查服务、数据库、磁盘等状态
# 不使用 set -e：某项检查失败（如服务未运行）时仍要继续执行后续检查

ENV_FILE="/var/www/clipsync/backend/.env"

# 逐行读取 .env 而不是 source，避免值里的特殊字符被 shell 执行
read_env() {
    grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"
}

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}=== ClipSync 健康检查 ===${NC}"
echo

# 1. 检查 ClipSync 服务
echo -n "ClipSync 服务: "
if systemctl is-active --quiet clipsync; then
    echo -e "${GREEN}✓ 运行中${NC}"
else
    echo -e "${RED}✗ 未运行${NC}"
    systemctl status clipsync --no-pager
fi

# 2. 检查 Nginx 服务
echo -n "Nginx 服务: "
if systemctl is-active --quiet nginx; then
    echo -e "${GREEN}✓ 运行中${NC}"
else
    echo -e "${RED}✗ 未运行${NC}"
fi

# 3. 检查 MySQL 服务
echo -n "MySQL 服务: "
if systemctl is-active --quiet mysql; then
    echo -e "${GREEN}✓ 运行中${NC}"
else
    echo -e "${RED}✗ 未运行${NC}"
fi

# 4. 检查 API 健康端点
echo -n "API 健康检查: "
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/ || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    echo -e "${GREEN}✓ 正常 (HTTP $HTTP_CODE)${NC}"
else
    echo -e "${RED}✗ 异常 (HTTP $HTTP_CODE)${NC}"
fi

# 5. 检查前端页面
echo -n "前端页面: "
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    echo -e "${GREEN}✓ 正常 (HTTP $HTTP_CODE)${NC}"
elif [ "$HTTP_CODE" = "301" ] || [ "$HTTP_CODE" = "308" ]; then
    # HTTPS 阶段 80 端口统一跳转到 443，属于正常配置
    echo -e "${GREEN}✓ 正常 (HTTP $HTTP_CODE，已跳转 HTTPS)${NC}"
else
    echo -e "${RED}✗ 异常 (HTTP $HTTP_CODE)${NC}"
fi

# 6. 检查数据库连接
echo -n "数据库连接: "
if [ -f "$ENV_FILE" ]; then
    DB_HOST=$(read_env DB_HOST); DB_PORT=$(read_env DB_PORT)
    DB_USER=$(read_env DB_USER); DB_NAME=$(read_env DB_NAME)
    # 密码经环境变量传给 mysql，不出现在进程参数里
    if MYSQL_PWD="$(read_env DB_PASSWORD)" mysql -h "${DB_HOST:-localhost}" -P "${DB_PORT:-3306}" -u "$DB_USER" -e "USE \`$DB_NAME\`;" 2>/dev/null; then
        echo -e "${GREEN}✓ 正常${NC}"
    else
        echo -e "${RED}✗ 连接失败${NC}"
    fi
else
    echo -e "${YELLOW}⚠ 配置文件未找到${NC}"
fi

# 7. 检查磁盘空间
echo
echo "磁盘使用情况:"
df -h / | tail -1 | awk '{
    usage = int($5);
    if (usage >= 90)
        printf "\033[0;31m✗ 使用率过高: %s\033[0m\n", $5;
    else if (usage >= 75)
        printf "\033[1;33m⚠ 使用率偏高: %s\033[0m\n", $5;
    else
        printf "\033[0;32m✓ 正常: %s\033[0m\n", $5;
}'

# 8. 检查内存使用
echo
echo "内存使用情况:"
free -h | grep Mem | awk '{
    total = $2;
    used = $3;
    available = $7;
    printf "总计: %s, 已用: %s, 可用: %s\n", total, used, available;
}'

# 9. 检查 CPU 负载
echo
echo "CPU 负载:"
uptime | awk -F'load average:' '{print "平均负载:" $2}'

# 10. 检查最近的错误日志
echo
echo "最近的错误日志 (最新 5 条):"
journalctl -u clipsync --since "1 hour ago" -p err --no-pager | tail -5 || echo "无错误日志"

# 11. 检查 WebSocket 连接数
echo
# 只统计后端 8000 端口上已建立的 TCP 入站连接。
# 其中也含 Nginx 到后端的 HTTP 长连接，数值是近似上限
echo -n "后端已建立连接数（含 WebSocket，近似）: "
WS_CONN=$(ss -Htn state established '( sport = :8000 )' 2>/dev/null | wc -l)
echo "$WS_CONN"

# 12. 检查备份状态
echo
echo "最新备份:"
LATEST_BACKUP=$(ls -t /var/backups/clipsync/database/*.sql.gz 2>/dev/null | head -1)
if [ -n "$LATEST_BACKUP" ]; then
    BACKUP_DATE=$(stat -c %y "$LATEST_BACKUP" | cut -d' ' -f1,2 | cut -d. -f1)
    BACKUP_SIZE=$(du -h "$LATEST_BACKUP" | cut -f1)
    echo -e "${GREEN}✓ 最新备份: $BACKUP_DATE ($BACKUP_SIZE)${NC}"

    # 检查备份是否超过 2 天
    BACKUP_AGE=$(( ($(date +%s) - $(stat -c %Y "$LATEST_BACKUP")) / 86400 ))
    if [ $BACKUP_AGE -gt 2 ]; then
        echo -e "${YELLOW}⚠ 备份已超过 ${BACKUP_AGE} 天${NC}"
    fi
else
    echo -e "${RED}✗ 未找到备份文件${NC}"
fi

echo
echo -e "${GREEN}=== 检查完成 ===${NC}"
