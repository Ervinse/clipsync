#!/bin/bash

# ClipSync 部署脚本
# 用于首次部署或更新部署

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 配置
PROJECT_ROOT="/var/www/clipsync"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
DEPLOY_USER="www-data"

echo -e "${GREEN}=== ClipSync 部署脚本 ===${NC}"
echo

# 检查是否以 root 运行
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}错误: 请使用 root 权限运行此脚本${NC}"
    exit 1
fi

# 步骤 1: 创建项目目录
echo -e "${YELLOW}[1/10] 创建项目目录...${NC}"
mkdir -p "$PROJECT_ROOT"
mkdir -p /var/backups/clipsync/database

# 步骤 2: 检查依赖
echo -e "${YELLOW}[2/10] 检查系统依赖...${NC}"
command -v python3 >/dev/null 2>&1 || { echo -e "${RED}错误: 未安装 Python 3${NC}"; exit 1; }
# 后端要求 Python 3.12+（rmtree 的 onexc 等）；已预建 venv 时以 venv 为准，不再检查系统 python3
if [ ! -d "$BACKEND_DIR/venv" ] && ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'; then
    echo -e "${RED}错误: 系统 python3 版本低于 3.12（当前 $(python3 -V 2>&1)）${NC}"
    echo "请先安装 Python 3.12 并预建虚拟环境: python3.12 -m venv $BACKEND_DIR/venv"
    exit 1
fi
command -v node >/dev/null 2>&1 || { echo -e "${RED}错误: 未安装 Node.js${NC}"; exit 1; }
command -v mysql >/dev/null 2>&1 || { echo -e "${RED}错误: 未安装 MySQL${NC}"; exit 1; }
command -v nginx >/dev/null 2>&1 || { echo -e "${RED}错误: 未安装 Nginx${NC}"; exit 1; }
echo -e "${GREEN}✓ 依赖检查通过${NC}"

# 步骤 3: 复制项目文件
echo -e "${YELLOW}[3/10] 复制项目文件...${NC}"
if [ ! -d "$BACKEND_DIR" ]; then
    echo "请先将项目文件复制到 $PROJECT_ROOT"
    exit 1
fi

# 步骤 4: 配置后端
echo -e "${YELLOW}[4/10] 配置后端环境...${NC}"
cd "$BACKEND_DIR"

# 创建虚拟环境
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo -e "${GREEN}✓ 虚拟环境已创建${NC}"
fi

# 安装依赖
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
echo -e "${GREEN}✓ Python 依赖已安装${NC}"

# 检查 .env 文件
if [ ! -f ".env" ]; then
    echo -e "${RED}错误: 未找到 .env 文件${NC}"
    echo "请先创建 .env 文件并配置数据库连接"
    exit 1
fi

# 步骤 5: 数据库迁移
echo -e "${YELLOW}[5/10] 执行数据库迁移...${NC}"
alembic upgrade head
echo -e "${GREEN}✓ 数据库迁移完成${NC}"

# 步骤 6: 创建超级管理员（首次部署）
echo -e "${YELLOW}[6/10] 创建超级管理员...${NC}"
if [ ! -f ".superadmin_created" ]; then
    python -m scripts.create_superadmin
    touch .superadmin_created
    echo -e "${GREEN}✓ 超级管理员已创建${NC}"
else
    echo "超级管理员已存在，跳过"
fi

# 步骤 7: 构建前端
echo -e "${YELLOW}[7/10] 构建前端...${NC}"
cd "$FRONTEND_DIR"
# npm ci：严格按 package-lock.json 安装，生产环境可复现
npm ci
npm run build
echo -e "${GREEN}✓ 前端构建完成${NC}"

# 步骤 8: 配置 Nginx
echo -e "${YELLOW}[8/10] 配置 Nginx...${NC}"
NGINX_CONF="/etc/nginx/sites-available/clipsync"
NGINX_ENABLED="/etc/nginx/sites-enabled/clipsync"

if [ -f "$PROJECT_ROOT/deployment/nginx/clipsync.conf" ]; then
    cp "$PROJECT_ROOT/deployment/nginx/clipsync.conf" "$NGINX_CONF"

    # 更新配置中的路径
    sed -i "s|/var/www/clipsync|$PROJECT_ROOT|g" "$NGINX_CONF"

    # 启用站点
    ln -sf "$NGINX_CONF" "$NGINX_ENABLED"

    # 测试配置
    nginx -t

    echo -e "${GREEN}✓ Nginx 配置完成${NC}"
else
    echo -e "${YELLOW}警告: 未找到 Nginx 配置模板${NC}"
fi

# 步骤 9: 配置 Systemd 服务
echo -e "${YELLOW}[9/10] 配置 Systemd 服务...${NC}"
SERVICE_FILE="/etc/systemd/system/clipsync.service"

if [ -f "$PROJECT_ROOT/deployment/systemd/clipsync.service" ]; then
    cp "$PROJECT_ROOT/deployment/systemd/clipsync.service" "$SERVICE_FILE"

    # 更新配置中的路径
    sed -i "s|/var/www/clipsync|$PROJECT_ROOT|g" "$SERVICE_FILE"

    # 重载 systemd
    systemctl daemon-reload

    echo -e "${GREEN}✓ Systemd 服务已配置${NC}"
else
    echo -e "${YELLOW}警告: 未找到 Systemd 配置模板${NC}"
fi

# 步骤 10: 设置定时任务
echo -e "${YELLOW}[10/10] 配置定时任务...${NC}"

# 创建 cron 任务
CRON_FILE="/etc/cron.d/clipsync"
cat > "$CRON_FILE" <<EOF
# ClipSync 定时任务

# 用 bash 显式调用，不依赖脚本的可执行位（git 检出、复制文件时可能丢失）

# 每天凌晨 2 点备份数据库
0 2 * * * root bash $PROJECT_ROOT/deployment/scripts/backup_database.sh >> /var/log/clipsync/backup.log 2>&1

# 每小时清理过期数据
0 * * * * root bash $PROJECT_ROOT/deployment/scripts/cleanup_expired.sh >> /var/log/clipsync/cleanup.log 2>&1
EOF

chmod 644 "$CRON_FILE"
echo -e "${GREEN}✓ 定时任务已配置${NC}"

# 创建日志目录
mkdir -p /var/log/clipsync
chown -R "$DEPLOY_USER:$DEPLOY_USER" /var/log/clipsync

# 设置权限
echo -e "${YELLOW}设置文件权限...${NC}"
chown -R "$DEPLOY_USER:$DEPLOY_USER" "$PROJECT_ROOT"
chmod +x "$PROJECT_ROOT"/deployment/scripts/*.sh
echo -e "${GREEN}✓ 权限设置完成${NC}"

echo
echo -e "${GREEN}=== 部署完成 ===${NC}"
echo
echo "下一步操作:"
echo "  1. 启动服务: systemctl start clipsync"
echo "  2. 启用开机自启: systemctl enable clipsync"
echo "  3. 重启 Nginx: systemctl restart nginx"
echo "  4. 查看服务状态: systemctl status clipsync"
echo "  5. 查看日志: journalctl -u clipsync -f"
echo
echo "管理命令:"
echo "  - 停止服务: systemctl stop clipsync"
echo "  - 重启服务: systemctl restart clipsync"
echo "  - 查看备份: ls -lh /var/backups/clipsync/database"
echo
echo -e "${YELLOW}注意: 请确保 .env 文件已正确配置数据库连接和密钥${NC}"
