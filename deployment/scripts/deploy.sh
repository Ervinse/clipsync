#!/bin/bash

# ClipSync 部署脚本
# 用于首次部署或更新部署
# 支持 Debian / Ubuntu 与 Rocky Linux / AlmaLinux / RHEL 9+；发行版差异见同目录 os_env.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=os_env.sh
source "$SCRIPT_DIR/os_env.sh"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 配置
PROJECT_ROOT="/var/www/clipsync"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

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
detect_os || exit 1
echo "发行版: $OS_PRETTY_NAME（$OS_FAMILY 系，应用用户 $APP_USER，MySQL 服务 $MYSQL_SERVICE）"

# 后端要求 Python 3.12+（rmtree 的 onexc 等）；已有 venv 时检查 venv 的解释器，否则找系统里的 3.12+
if [ -d "$BACKEND_DIR/venv" ]; then
    if ! python_ok "$BACKEND_DIR/venv/bin/python"; then
        echo -e "${RED}错误: $BACKEND_DIR/venv 的 Python 低于 3.12，请删除该目录后重新运行本脚本${NC}"
        exit 1
    fi
elif ! PYTHON_BIN=$(find_python); then
    echo -e "${RED}错误: 未找到 Python 3.12+（当前 python3: $(python3 -V 2>&1)）${NC}"
    if [ "$OS_FAMILY" = "rhel" ]; then
        echo "请先安装: dnf install -y python3.12 python3.12-pip"
    else
        echo "Ubuntu 24.04 自带 3.12；Ubuntu 22.04 请先安装 python3.12 与 python3.12-venv（如 deadsnakes PPA）；Debian 12 自带 3.11，需自行安装 3.12（如 pyenv 或源码编译）"
    fi
    exit 1
fi
command -v node >/dev/null 2>&1 || { echo -e "${RED}错误: 未安装 Node.js${NC}"; exit 1; }
command -v mysql >/dev/null 2>&1 || { echo -e "${RED}错误: 未安装 MySQL${NC}"; exit 1; }
command -v nginx >/dev/null 2>&1 || { echo -e "${RED}错误: 未安装 Nginx${NC}"; exit 1; }
# 应用用户由 Nginx 软件包创建（Debian 系为 www-data，RHEL 系为 nginx）
id "$APP_USER" >/dev/null 2>&1 || { echo -e "${RED}错误: 用户 $APP_USER 不存在，请确认 Nginx 已正确安装${NC}"; exit 1; }
# SELinux 开启时需要 semanage 给 venv 打标签（见 os_env.sh 的 configure_selinux）
if selinux_enabled && ! command -v semanage >/dev/null 2>&1; then
    echo -e "${RED}错误: SELinux 已开启但未找到 semanage，请先安装: dnf install -y policycoreutils-python-utils${NC}"
    exit 1
fi
# 定时任务写入 /etc/cron.d，需要 cron 服务（RHEL 系为 cronie）
if [ ! -d /etc/cron.d ]; then
    echo -e "${RED}错误: 未找到 /etc/cron.d，请先安装 cron（RHEL 系: dnf install -y cronie && systemctl enable --now crond）${NC}"
    exit 1
fi
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
    "$PYTHON_BIN" -m venv venv
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
# 安装位置按发行版：Debian 系 sites-available + sites-enabled 软链，RHEL 系 conf.d（无需软链）
if [ -f "$PROJECT_ROOT/deployment/nginx/clipsync.conf" ]; then
    cp "$PROJECT_ROOT/deployment/nginx/clipsync.conf" "$NGINX_SITE_CONF"

    # 更新配置中的路径
    sed -i "s|/var/www/clipsync|$PROJECT_ROOT|g" "$NGINX_SITE_CONF"

    # 启用站点
    if [ -n "$NGINX_SITE_LINK" ]; then
        ln -sf "$NGINX_SITE_CONF" "$NGINX_SITE_LINK"
    fi

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
    # 按发行版替换项目路径、运行用户与 MySQL 服务名
    render_service_unit "$PROJECT_ROOT/deployment/systemd/clipsync.service" "$SERVICE_FILE"

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
chown -R "$APP_USER:$APP_USER" /var/log/clipsync

# 设置权限
echo -e "${YELLOW}设置文件权限...${NC}"
chown -R "$APP_USER:$APP_USER" "$PROJECT_ROOT"
chmod +x "$PROJECT_ROOT"/deployment/scripts/*.sh
# SELinux 开启时放行 Nginx 反代并修正文件标签；未开启时不做任何事
configure_selinux
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
nginx_default_site_warning
if [ "$OS_FAMILY" = "rhel" ]; then
    echo "防火墙（firewalld）需放行 HTTP/HTTPS: firewall-cmd --permanent --add-service=http --add-service=https && firewall-cmd --reload"
fi
