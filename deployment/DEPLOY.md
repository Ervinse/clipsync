# ClipSync 部署指南

本文档是**部署的权威文档**，描述如何在生产环境直接部署 ClipSync（systemd + Nginx）。Docker 部署见 [docker/README.md](docker/README.md)，逐项核对见 [CHECKLIST.md](CHECKLIST.md)。

## 系统要求

### 硬件
- CPU 2 核及以上，内存 2GB 及以上
- 磁盘 20GB 及以上（按用户数与文件量调整）

### 软件
- **Ubuntu 22.04 / 24.04 或 Debian 12**。脚本写死了 `apt`、`/etc/nginx/sites-available`、`www-data`，**不支持 CentOS/RHEL**。
- **Python 3.12+**。代码使用了 3.10+ 语法，项目统一要求 3.12。
- **Node.js 20.19+ 或 22.12+**。Vite 8 要求 `^20.19.0 || >=22.12.0`，系统 apt 源里的 Node 版本太旧，不能用。
- MySQL 8.0+
- Nginx 1.18+

## 部署步骤

### 1. 安装系统依赖

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv mysql-server nginx git curl

# Node.js 22 LTS（NodeSource），不要用 apt 自带的 nodejs
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs
node -v   # 确认 >= 20.19
```

Ubuntu 22.04 自带 Python 3.10，需要另装 3.12（如 deadsnakes PPA），并用 `python3.12 -m venv` 建虚拟环境。

### 2. 配置 MySQL（deploy.sh 不会建库）

```bash
sudo systemctl enable --now mysql
sudo mysql_secure_installation
sudo mysql -u root -p
```

```sql
CREATE DATABASE clipsync CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'clipsync'@'localhost' IDENTIFIED BY 'your_secure_password';
GRANT ALL PRIVILEGES ON clipsync.* TO 'clipsync'@'localhost';
FLUSH PRIVILEGES;
```

### 3. 上传项目

```bash
sudo mkdir -p /var/www
cd /var/www
sudo git clone <your-repo> clipsync   # 或 scp / rsync 上传
```

### 4. 配置后端 `.env`

```bash
cd /var/www/clipsync/backend
sudo cp ../deployment/.env.production.example .env
sudo chmod 600 .env
sudo nano .env
```

必须修改的配置项：
- `DB_USER` / `DB_PASSWORD` / `DB_NAME`：与第 2 步一致
- `JWT_SECRET`：用 `openssl rand -hex 32` 生成。少于 32 字符或仍是示例值时，后端会拒绝启动
- `CORS_ORIGINS`：前端访问地址（如 `http://192.168.1.10` 或 `https://your-domain.com`），不支持 `*`
- `HSTS_ENABLED`：只在 HTTPS 阶段设为 `true`

`DEPLOY_SCHEME`、`COOKIE_SECURE` 目前代码里没有读取（访问码链接按请求协议动态拼接，Token 不走 cookie），保持与协议一致即可。

### 5. 执行部署脚本

```bash
cd /var/www/clipsync
sudo bash deployment/scripts/deploy.sh
```

脚本会依次完成：
1. 检查 python3 / node / mysql / nginx 是否已安装（只检查，不安装、不建库）
2. 创建 `backend/venv` 并安装依赖
3. `alembic upgrade head`
4. 交互式创建首个超级管理员
5. 构建前端
6. 安装 HTTP 版 Nginx 配置并执行 `nginx -t`
7. 安装 systemd 服务
8. 写入 cron 定时任务（备份、清理）

Debian/Ubuntu 自带的 `/etc/nginx/sites-enabled/default` 也监听 80 端口，可能会先接走请求。如果不需要它，请删除：`sudo rm /etc/nginx/sites-enabled/default`。

### 6. 启动服务

```bash
sudo systemctl enable --now clipsync
sudo systemctl reload nginx
```

### 7. 验证

```bash
sudo systemctl status clipsync
curl http://127.0.0.1:8000/          # 健康检查，返回 {"status":"ok",...}
curl -I http://<服务器地址>/          # 前端页面
sudo bash deployment/scripts/health_check.sh
```

如果部署脚本没有成功创建超级管理员，手动执行：

```bash
cd /var/www/clipsync/backend && source venv/bin/activate
python -m scripts.create_superadmin
```

## HTTP / HTTPS 切换

`deployment/nginx/` 下有两份配置：

| 文件 | 用途 |
|------|------|
| `clipsync.conf` | HTTP 阶段，只监听 80，deploy.sh 默认安装这一份 |
| `clipsync-https.conf` | HTTPS 阶段：80 跳转 443，443 使用 TLS 证书 |

升级到 HTTPS：

```bash
# 1. 申请证书
sudo apt install -y certbot
sudo certbot certonly --webroot -w /var/www/clipsync/frontend/dist -d your-domain.com

# 2. 修改 clipsync-https.conf 里的 server_name 与证书路径，然后替换站点配置
sudo cp /var/www/clipsync/deployment/nginx/clipsync-https.conf /etc/nginx/sites-available/clipsync
sudo nginx -t && sudo systemctl reload nginx

# 3. 修改 backend/.env：HSTS_ENABLED=true、CORS_ORIGINS=https://your-domain.com
sudo systemctl restart clipsync
```

前端使用相对路径，WebSocket 按页面协议自动选择 `ws://` 或 `wss://`，切换协议后不需要重新构建前端。HSTS 响应头由后端按 `HSTS_ENABLED` 下发，Nginx 不需要再配置。

> HTTP 阶段密码、Token 和内容都以明文传输，只能用于可信内网。

## 日常维护

### 更新应用

```bash
sudo bash /var/www/clipsync/deployment/scripts/update.sh
```

流程：停服务 → 备份数据库 → 在项目根目录执行 `git pull --ff-only` → 更新后端依赖并执行迁移 → 构建前端 → 重启服务。

### 备份与恢复

```bash
# 手动备份（cron 每天 2:00 自动执行）
sudo bash /var/www/clipsync/deployment/scripts/backup_database.sh
ls -lh /var/backups/clipsync/database/

# 恢复
gunzip < /var/backups/clipsync/database/clipsync_YYYYMMDD_HHMMSS.sql.gz | mysql -u clipsync -p clipsync
```

备份脚本从 `backend/.env` 读取数据库连接信息，并启用了 `pipefail`。mysqldump 失败时脚本会报错退出，不会留下空的备份文件。数据库备份**不包含上传的文件**，文件在 `backend/storage/`，需要另外备份。

### 清理任务

cron 每小时执行一次 `cleanup_expired.sh`：删除已过期的访问码，以及超过 `UPLOAD_SESSION_TTL_HOURS` 仍未完成的上传会话和对应临时目录。

### 日志

```bash
sudo journalctl -u clipsync -f
sudo tail -f /var/log/nginx/error.log
sudo tail -f /var/log/clipsync/backup.log /var/log/clipsync/cleanup.log
```

## 性能与扩容

- **保持 `--workers 1`**。WebSocket 连接表和限流计数都在进程内存中，多 worker 或多实例会导致实时同步和限流失效。如果确实要扩容，需要先引入 Redis 等跨进程 pub/sub 和共享的限流存储。
- 后端只监听 `127.0.0.1:8000`，由同机 Nginx 反代。uvicorn 只信任 `127.0.0.1` 发来的 `X-Forwarded-For`，限流才能拿到真实客户端 IP。
- MySQL 调优示例（`/etc/mysql/mysql.conf.d/mysqld.cnf`）：

  ```ini
  [mysqld]
  max_connections = 200
  innodb_buffer_pool_size = 1G   # 按内存调整
  ```

  MySQL 8.0 已移除 `query_cache_size`，配置里不要写这个参数，否则 MySQL 会拒绝启动。

## 故障排查

| 现象 | 排查 |
|------|------|
| 服务起不来 | `journalctl -u clipsync -n 100`。常见原因：`JWT_SECRET` 过弱或仍是示例值、数据库连不上、`backend/storage/` 没有写权限 |
| 页面 404 或打开的是 Nginx 默认页 | 确认已删除 `sites-enabled/default`，并且 `nginx -t` 通过 |
| WebSocket 连不上 | 检查 Nginx `/ws` 的 `Upgrade` / `Connection` 头；token 走 `Sec-WebSocket-Protocol`，代理不能剥掉这个头 |
| 所有人一起被限流 | 后端没拿到真实 IP，检查 Nginx 是否设置了 `X-Forwarded-For`，以及 uvicorn 的 `--forwarded-allow-ips` |

## 安全建议

- `.env` 权限设为 600。更换 `JWT_SECRET` 后，所有已签发的 token 会立即失效。
- 防火墙只开放 22 / 80 / 443。后端 8000 端口和 MySQL 3306 端口只监听本机。
- 正式环境使用 HTTPS 并开启 HSTS。
- FastAPI 自带的 `/docs` 没有经过 Nginx 反代，外部访问不到，这是有意的。
