# ClipSync 部署指南

本文档描述如何在生产环境部署 ClipSync。

## 系统要求

### 硬件要求
- CPU: 2 核心及以上
- 内存: 2GB 及以上
- 磁盘: 20GB 及以上（根据用户数和文件存储需求调整）

### 软件要求
- Ubuntu 20.04 / 22.04 或 CentOS 7 / 8
- Python 3.9+
- Node.js 16+
- MySQL 8.0+
- Nginx 1.18+

## 部署步骤

### 1. 安装系统依赖

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv \
    nodejs npm mysql-server nginx git curl
```

**CentOS/RHEL:**
```bash
sudo yum install -y python3 python3-pip python3-venv \
    nodejs npm mysql-server nginx git curl
```

### 2. 配置 MySQL

```bash
# 启动 MySQL
sudo systemctl start mysql
sudo systemctl enable mysql

# 运行安全配置
sudo mysql_secure_installation

# 创建数据库和用户
sudo mysql -u root -p
```

在 MySQL 中执行：

```sql
CREATE DATABASE clipsync CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'clipsync'@'localhost' IDENTIFIED BY 'your_secure_password';
GRANT ALL PRIVILEGES ON clipsync.* TO 'clipsync'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

### 3. 部署项目

```bash
# 克隆或上传项目到服务器
sudo mkdir -p /var/www
cd /var/www
sudo git clone https://github.com/your-repo/clipsync.git
# 或使用 scp/rsync 上传

# 设置权限
sudo chown -R www-data:www-data /var/www/clipsync
```

### 4. 配置后端

```bash
cd /var/www/clipsync/backend

# 复制并编辑配置文件
sudo cp ../deployment/.env.production.example .env
sudo nano .env
```

**必须修改的配置项：**
- `DB_PASSWORD`: 数据库密码
- `JWT_SECRET_KEY`: 随机密钥（用 `openssl rand -hex 32` 生成）
- `CORS_ORIGINS`: 前端域名
- `DEPLOY_SCHEME`: http 或 https
- `COOKIE_SECURE`: HTTPS 环境设为 true
- `HSTS_ENABLED`: HTTPS 环境推荐启用

### 5. 配置前端

```bash
cd /var/www/clipsync/frontend

# 如需自定义 API 地址，编辑 vite.config.js
# 生产环境通常无需修改（通过 Nginx 代理）
```

### 6. 执行部署脚本

```bash
cd /var/www/clipsync
sudo chmod +x deployment/scripts/*.sh
sudo bash deployment/scripts/deploy.sh
```

脚本会自动完成：
1. 创建虚拟环境并安装依赖
2. 执行数据库迁移
3. 创建超级管理员
4. 构建前端
5. 配置 Nginx
6. 配置 Systemd 服务
7. 设置定时任务

### 7. 配置 SSL（HTTPS 部署）

**使用 Let's Encrypt 免费证书：**

```bash
# 安装 Certbot
sudo apt install certbot python3-certbot-nginx

# 获取证书（替换为你的域名）
sudo certbot --nginx -d your-domain.com -d www.your-domain.com

# 证书会自动更新，测试自动更新
sudo certbot renew --dry-run
```

编辑 Nginx 配置 `/etc/nginx/sites-available/clipsync`，取消注释 HTTPS 部分，并修改：
- `server_name your-domain.com;`
- SSL 证书路径（Certbot 会自动配置）

**手动证书：**

将证书文件放置到服务器并在 Nginx 配置中指定路径。

### 8. 启动服务

```bash
# 启动 ClipSync 服务
sudo systemctl start clipsync
sudo systemctl enable clipsync

# 重启 Nginx
sudo systemctl restart nginx
```

### 9. 验证部署

```bash
# 检查服务状态
sudo systemctl status clipsync
sudo systemctl status nginx

# 查看日志
sudo journalctl -u clipsync -f

# 测试 API
curl http://localhost:8000/api/health

# 测试前端
curl http://your-domain.com
```

### 10. 创建第一个超级管理员

如果部署脚本未自动创建，手动创建：

```bash
cd /var/www/clipsync/backend
source venv/bin/activate
python -m scripts.create_superadmin
```

## 日常维护

### 更新应用

```bash
cd /var/www/clipsync
sudo bash deployment/scripts/update.sh
```

### 查看日志

```bash
# 应用日志
sudo journalctl -u clipsync -f

# Nginx 访问日志
sudo tail -f /var/log/nginx/access.log

# Nginx 错误日志
sudo tail -f /var/log/nginx/error.log

# 备份日志
sudo tail -f /var/log/clipsync/backup.log

# 清理日志
sudo tail -f /var/log/clipsync/cleanup.log
```

### 备份与恢复

**手动备份：**
```bash
sudo bash /var/www/clipsync/deployment/scripts/backup_database.sh
```

**查看备份：**
```bash
ls -lh /var/backups/clipsync/database/
```

**恢复备份：**
```bash
# 选择一个备份文件
BACKUP_FILE="/var/backups/clipsync/database/clipsync_20250101_020000.sql.gz"

# 恢复数据库
gunzip < "$BACKUP_FILE" | mysql -u clipsync -p clipsync
```

### 清理任务

定时任务会自动执行：
- **每天凌晨 2 点**：备份数据库
- **每小时**：清理过期访问码和临时文件

手动执行清理：
```bash
sudo bash /var/www/clipsync/deployment/scripts/cleanup_expired.sh
```

### 服务管理

```bash
# 启动
sudo systemctl start clipsync

# 停止
sudo systemctl stop clipsync

# 重启
sudo systemctl restart clipsync

# 查看状态
sudo systemctl status clipsync

# 启用开机自启
sudo systemctl enable clipsync

# 禁用开机自启
sudo systemctl disable clipsync
```

### 重新加载配置

修改 `.env` 后需要重启服务：
```bash
sudo systemctl restart clipsync
```

修改 Nginx 配置后：
```bash
sudo nginx -t  # 测试配置
sudo systemctl reload nginx
```

## 性能优化

### Uvicorn Workers

根据 CPU 核心数调整 worker 数量，编辑 `/etc/systemd/system/clipsync.service`：

```
ExecStart=/var/www/clipsync/backend/venv/bin/uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 4 \  # CPU 核心数
    ...
```

重载配置：
```bash
sudo systemctl daemon-reload
sudo systemctl restart clipsync
```

### 数据库优化

编辑 MySQL 配置 `/etc/mysql/mysql.conf.d/mysqld.cnf`：

```ini
[mysqld]
max_connections = 200
innodb_buffer_pool_size = 1G  # 根据内存调整
innodb_log_file_size = 256M
query_cache_size = 64M
```

重启 MySQL：
```bash
sudo systemctl restart mysql
```

### Nginx 缓存

在 Nginx 配置中已启用静态资源缓存（30 天）。

## 监控

### 系统资源监控

```bash
# 查看 CPU 和内存使用
htop

# 查看磁盘使用
df -h

# 查看网络连接
netstat -tulnp
```

### 应用监控

```bash
# 查看进程
ps aux | grep clipsync

# 查看端口监听
sudo netstat -tulnp | grep 8000

# 查看 WebSocket 连接数
ss -tun | grep :8000 | wc -l
```

## 故障排查

### 服务无法启动

1. 查看日志：`sudo journalctl -u clipsync -n 100`
2. 检查配置：`.env` 文件是否正确
3. 检查数据库：是否可连接
4. 检查权限：`uploads/` 目录权限

### 前端无法访问

1. 检查 Nginx：`sudo nginx -t`
2. 查看 Nginx 日志：`sudo tail -f /var/log/nginx/error.log`
3. 检查防火墙：`sudo ufw status`

### WebSocket 连接失败

1. 检查 Nginx WebSocket 配置
2. 确认 `Upgrade` 和 `Connection` header 正确
3. 检查超时设置

### 数据库连接失败

1. 确认 MySQL 运行：`sudo systemctl status mysql`
2. 测试连接：`mysql -u clipsync -p clipsync`
3. 检查 `.env` 中的数据库配置

## 安全建议

1. **定期更新系统**：
   ```bash
   sudo apt update && sudo apt upgrade
   ```

2. **配置防火墙**：
   ```bash
   sudo ufw allow 80/tcp
   sudo ufw allow 443/tcp
   sudo ufw allow 22/tcp
   sudo ufw enable
   ```

3. **定期更换密钥**：
   - 定期更换 `JWT_SECRET_KEY`
   - 定期更换数据库密码

4. **监控访问日志**：
   - 检查异常访问
   - 监控失败的登录尝试

5. **启用 HTTPS**：
   - 使用 Let's Encrypt 或购买证书
   - 启用 HSTS

6. **限制数据库访问**：
   - MySQL 只监听 localhost
   - 使用强密码

## 扩展部署

### 多实例负载均衡

使用 Nginx upstream 配置多个后端实例：

```nginx
upstream clipsync_backend {
    server 127.0.0.1:8000;
    server 127.0.0.1:8001;
    server 127.0.0.1:8002;
}

location /api {
    proxy_pass http://clipsync_backend;
    ...
}
```

### 使用 Redis 缓存

安装 Redis 并配置后端使用 Redis 存储会话。

### 对象存储

将文件上传到 S3/OSS 等对象存储服务，减轻服务器磁盘压力。

## 联系与支持

- 文档：`/docs`
- 问题反馈：GitHub Issues
- 技术支持：根据实际情况填写

---

**注意**：本文档基于 Ubuntu 22.04 编写，其他系统可能需要调整命令。
