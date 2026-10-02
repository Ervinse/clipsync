#!/bin/bash

# ClipSync 更新脚本
# 用于更新已部署的应用

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 配置
PROJECT_ROOT="/var/www/clipsync"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

echo -e "${GREEN}=== ClipSync 更新脚本 ===${NC}"
echo

# 检查是否以 root 运行
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}错误: 请使用 root 权限运行此脚本${NC}"
    exit 1
fi

# 步骤 1: 停止服务
echo -e "${YELLOW}[1/6] 停止服务...${NC}"
systemctl stop clipsync
# 任何一步失败（set -e 退出）都要把服务拉起来，不能让线上服务一直停着
trap 'echo -e "${RED}更新中断，尝试重新启动服务...${NC}"; systemctl start clipsync || true' EXIT
echo -e "${GREEN}✓ 服务已停止${NC}"

# 步骤 2: 备份数据库
echo -e "${YELLOW}[2/6] 备份数据库...${NC}"
bash "$PROJECT_ROOT/deployment/scripts/backup_database.sh"
echo -e "${GREEN}✓ 数据库已备份${NC}"

# 步骤 3: 更新后端
echo -e "${YELLOW}[3/6] 更新后端...${NC}"

# 拉取最新代码：.git 在项目根目录，必须在根目录执行
# 以项目文件属主（www-data）执行：root 执行会把 .git 内新对象改成 root 所有，之后 www-data 无法再操作
if [ -d "$PROJECT_ROOT/.git" ]; then
    sudo -u www-data git -C "$PROJECT_ROOT" pull --ff-only
    echo -e "${GREEN}✓ 代码已更新${NC}"
else
    echo -e "${YELLOW}⚠ $PROJECT_ROOT 不是 git 仓库，跳过拉取代码${NC}"
fi

cd "$BACKEND_DIR"

# 更新依赖
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
echo -e "${GREEN}✓ 依赖已更新${NC}"

# 执行数据库迁移
alembic upgrade head
echo -e "${GREEN}✓ 数据库迁移完成${NC}"

# 步骤 4: 更新前端
echo -e "${YELLOW}[4/6] 更新前端...${NC}"
cd "$FRONTEND_DIR"

# 更新依赖并构建（代码已在步骤 3 拉取）
npm ci
npm run build
echo -e "${GREEN}✓ 前端已构建${NC}"

# 步骤 5: 重启服务
echo -e "${YELLOW}[5/6] 重启服务...${NC}"
systemctl start clipsync
# 服务已正常拉起，解除失败兜底
trap - EXIT
systemctl restart nginx
echo -e "${GREEN}✓ 服务已重启${NC}"

# 步骤 6: 检查状态
echo -e "${YELLOW}[6/6] 检查服务状态...${NC}"
sleep 3

if systemctl is-active --quiet clipsync; then
    echo -e "${GREEN}✓ ClipSync 服务运行正常${NC}"
else
    echo -e "${RED}✗ ClipSync 服务启动失败${NC}"
    echo "查看日志: journalctl -u clipsync -n 50"
    exit 1
fi

if systemctl is-active --quiet nginx; then
    echo -e "${GREEN}✓ Nginx 运行正常${NC}"
else
    echo -e "${RED}✗ Nginx 启动失败${NC}"
    exit 1
fi

echo
echo -e "${GREEN}=== 更新完成 ===${NC}"
echo
echo "查看实时日志: journalctl -u clipsync -f"
echo "查看 Nginx 日志: tail -f /var/log/nginx/error.log"
