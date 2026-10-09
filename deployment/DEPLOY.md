# ClipSync 部署指南

本文档是**部署的权威文档**，描述如何在生产环境直接部署 ClipSync（systemd + Nginx），支持 Debian / Ubuntu 与 Rocky Linux / AlmaLinux / RHEL 9+。Docker 部署见 [docker/README.md](docker/README.md)，逐项核对见 [CHECKLIST.md](CHECKLIST.md)。

## 系统要求

### 硬件
- CPU 2 核及以上，内存 2GB 及以上
- 磁盘 20GB 及以上（按用户数与文件量调整）

### 软件
- **操作系统**，二选一：
  - **Debian 系**：Ubuntu 22.04 / 24.04、Debian 12
  - **RHEL 系**：Rocky Linux 9、AlmaLinux 9、RHEL 9、CentOS Stream 9 及以上版本
- **Python 3.12+**。后端用到 `shutil.rmtree(onexc=...)` 等 3.12 才有的接口。
- **Node.js 20.19+ 或 22.12+**。Vite 8 要求 `^20.19.0 || >=22.12.0`，系统源里的 Node 版本太旧，不能用。
- MySQL 8.0+
- Nginx 1.18+

`deploy.sh` 读取 `/etc/os-release` 判断发行版，其他系统会直接退出。CentOS 7 / 8、Rocky 8 等旧版本装不上 Python 3.12 和 Node.js 20+，请改用 [Docker 部署](docker/README.md)。

两类发行版的差异由脚本自动处理：

| 项 | Debian 系 | RHEL 系 |
|----|-----------|---------|
| 应用用户（运行后端、持有项目文件，与 Nginx 一致） | `www-data` | `nginx` |
| Nginx 站点配置 | `/etc/nginx/sites-available/clipsync` + `sites-enabled` 软链 | `/etc/nginx/conf.d/clipsync.conf` |
| MySQL 服务名 | `mysql` | `mysqld` |
| SELinux | 无 | `deploy.sh` 自动放行 Nginx 反代并给 venv 打标签（见第 5 步） |
| 防火墙 | ufw（如启用） | firewalld，需手动放行（见第 1 步） |

下文命令里的 `www-data` 在 RHEL 系上一律换成 `nginx`。

## 部署步骤

### 1. 安装系统依赖

**Debian / Ubuntu**

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv mysql-server nginx git curl

# Node.js 22 LTS（NodeSource），不要用 apt 自带的 nodejs
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs
node -v   # 确认 >= 20.19
```

Ubuntu 24.04 自带 Python 3.12。Ubuntu 22.04 自带 3.10、Debian 12 自带 3.11，需要另装 3.12（Ubuntu 可用 deadsnakes PPA 安装 `python3.12` 与 `python3.12-venv`）。系统里有 `python3.12` 命令时，`deploy.sh` 会自动用它创建虚拟环境。

**Rocky Linux / AlmaLinux / RHEL 9**

```bash
sudo dnf install -y python3.12 python3.12-pip mysql-server nginx git curl \
    cronie policycoreutils-python-utils
sudo systemctl enable --now crond

# Node.js 22 LTS（NodeSource），不要用 dnf 自带的旧版 nodejs
curl -fsSL https://rpm.nodesource.com/setup_22.x | sudo bash -
sudo dnf install -y nodejs
node -v && python3.12 --version

# 防火墙放行 HTTP / HTTPS
sudo firewall-cmd --permanent --add-service=http --add-service=https
sudo firewall-cmd --reload
```

- 系统的 `python3` 是 3.9，不要改它（`dnf` 依赖它）。`deploy.sh` 会找到 `python3.12` 并用它创建虚拟环境。`python3.12` 包需要 9.4 及以上的小版本，更早的版本先 `sudo dnf upgrade`。
- `policycoreutils-python-utils` 提供 `semanage`。SELinux 开启时 `deploy.sh` 依赖它，没装会在第 2 步退出。
- `cronie` 提供 `/etc/cron.d` 与定时任务服务，最小化安装的系统可能没有。

### 2. 配置 MySQL（deploy.sh 不会建库）

```bash
sudo systemctl enable --now mysql    # RHEL 系为 mysqld
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

脚本共 10 步：
1. 创建项目目录与备份目录 `/var/backups/clipsync/database`
2. 识别发行版并检查依赖（只检查，不安装、不建库）：
   - Python：`backend/venv` 已存在时检查其解释器 ≥ 3.12；不存在时依次查找 `python3`、`python3.12`、`python3.13`、`python3.14`，用第一个 ≥ 3.12 的
   - node / mysql / nginx 已安装，应用用户（`www-data` 或 `nginx`）存在
   - `/etc/cron.d` 存在；SELinux 开启时 `semanage` 可用
3. 确认项目文件已放到 `/var/www/clipsync`
4. 创建 `backend/venv`（已存在则复用）并安装依赖，确认 `backend/.env` 已存在
5. `alembic upgrade head`
6. 交互式创建首个超级管理员；成功后写入标记文件 `backend/.superadmin_created`，再次运行脚本时跳过这一步
7. `npm ci` 并构建前端
8. 安装 HTTP 版 Nginx 配置并执行 `nginx -t`。安装位置见上方「系统要求」的差异表
9. 安装 systemd 服务并 `daemon-reload`，安装时按发行版替换运行用户与 MySQL 服务名（**不会**启用或启动服务）
10. 写入 cron 定时任务（备份、清理，均用 `bash` 显式调用）

最后把项目目录和 `/var/log/clipsync` 的属主设为应用用户。SELinux 开启时（RHEL 系默认 enforcing）还会：
- `setsebool -P httpd_can_network_connect 1`：允许 Nginx 反代到 `127.0.0.1:8000`，否则页面返回 502
- `semanage fcontext` 把 `backend/venv/bin` 标为 `bin_t`：`/var/www` 下的文件默认不允许 systemd 执行，否则 clipsync 服务以 `203/EXEC` 启动失败
- `restorecon -R /var/www/clipsync`：恢复项目文件的安全上下文，否则从家目录 `mv` 过来的文件保留原标签，Nginx 读静态文件返回 403

发行版自带的 Nginx 默认站点也监听 80 端口，可能会先接走请求，脚本结束时检测到会提示：
- **Debian 系**：如果不需要，删除 `sudo rm /etc/nginx/sites-enabled/default`
- **RHEL 系**：默认站点写在 `/etc/nginx/nginx.conf` 的 `http { }` 里。把其中的 `server { ... }` 整段注释掉，再执行 `sudo nginx -t`

### 6. 启动服务

```bash
sudo systemctl enable --now clipsync
# 用 restart 而不是 reload：RHEL 系装完 Nginx 不会自动启动，reload 一个未运行的服务会失败
sudo systemctl enable nginx && sudo systemctl restart nginx
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

> 生产环境**不需要运行 `pytest`**。测试会 DROP 并重建 `clipsync_test` 库，需要建库、删库权限，第 2 步创建的 `clipsync` 账号只有 `clipsync` 库的权限，测试会直接失败。测试只在开发环境运行（见项目根目录 README.md 第 16 节）；上线后的检查以本节命令和 [CHECKLIST.md](CHECKLIST.md) 为准。

## HTTP / HTTPS 切换

`deployment/nginx/` 下有两份配置：

| 文件 | 用途 |
|------|------|
| `clipsync.conf` | HTTP 阶段，只监听 80，deploy.sh 默认安装这一份 |
| `clipsync-https.conf` | HTTPS 阶段：80 跳转 443，443 使用 TLS 证书 |

升级到 HTTPS：

```bash
# 1. 申请证书
sudo apt install -y certbot                                # Debian 系
sudo dnf install -y epel-release && sudo dnf install -y certbot   # RHEL 系（certbot 在 EPEL 源）
sudo certbot certonly --webroot -w /var/www/clipsync/frontend/dist -d your-domain.com

# 2. 修改 clipsync-https.conf 里的 server_name 与证书路径，然后替换站点配置
#    Debian 系：
sudo cp /var/www/clipsync/deployment/nginx/clipsync-https.conf /etc/nginx/sites-available/clipsync
#    RHEL 系：
sudo cp /var/www/clipsync/deployment/nginx/clipsync-https.conf /etc/nginx/conf.d/clipsync.conf
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

流程：停服务 → 备份数据库 → 在项目根目录以项目目录的属主（`deploy.sh` 设置的应用用户）执行 `git pull --ff-only` → 更新后端依赖并执行迁移 → `npm ci` 并构建前端 → SELinux 开启时 `restorecon` 恢复新文件的安全上下文 → 重启服务。任何一步失败，脚本退出前都会尝试把服务重新拉起。

### 回滚

更新后发现问题时，回到上一个版本：

```bash
sudo systemctl stop clipsync

# 1. 代码回到更新前的提交（git reflog 可查到 pull 之前的位置）
cd /var/www/clipsync
sudo -u www-data git reflog -n 5
sudo -u www-data git checkout <更新前的提交>

# 2. 若这次更新包含数据库迁移：先降级迁移，或用更新前的备份恢复（update.sh 第 2 步已自动备份）
cd backend
sudo venv/bin/alembic downgrade <更新前的 revision>
# 或：gunzip < /var/backups/clipsync/database/clipsync_<更新前时间>.sql.gz | mysql -u clipsync -p clipsync

# 3. 依赖与前端回到对应版本（与 update.sh 一样以 root 执行）
sudo venv/bin/pip install -r requirements.txt
cd ../frontend && sudo npm ci && sudo npm run build

sudo systemctl start clipsync
```

- 降级迁移 `3f1c2a9d7b4e`（剪贴板文本改 MEDIUMTEXT）时，如果库里已有超过 64KB 的文本，降级会失败或截断，这种情况改用备份恢复。
- 回滚到旧提交后仓库处于分离 HEAD 状态，问题修好后用 `sudo -u www-data git checkout master && sudo -u www-data git pull --ff-only` 回到主线。
- RHEL 系回滚后执行 `sudo restorecon -R /var/www/clipsync`，再启动服务。

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

cron 每小时执行一次 `cleanup_expired.sh`（实际逻辑在 `backend/scripts/cleanup_expired.py`）：删除已过期的访问码，超过 `UPLOAD_SESSION_TTL_HOURS` 仍未完成的上传会话和对应临时目录，并做孤儿扫描（超过 TTL 且无会话记录的 tmp 目录、用户已不存在的 `storage/<uid>` 目录）。

### 日志

```bash
sudo journalctl -u clipsync -f
sudo tail -f /var/log/nginx/error.log
sudo tail -f /var/log/clipsync/backup.log /var/log/clipsync/cleanup.log
```

## 性能与扩容

- **保持 `--workers 1`**。WebSocket 连接表和限流计数都在进程内存中，多 worker 或多实例会导致实时同步和限流失效。如果确实要扩容，需要先引入 Redis 等跨进程 pub/sub 和共享的限流存储。
- 后端只监听 `127.0.0.1:8000`，由同机 Nginx 反代。uvicorn 只信任 `127.0.0.1` 发来的 `X-Forwarded-For`，限流才能拿到真实客户端 IP。
- MySQL 调优示例（Debian 系 `/etc/mysql/mysql.conf.d/mysqld.cnf`，RHEL 系 `/etc/my.cnf.d/mysql-server.cnf`）：

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
| 服务以 `status=203/EXEC` 失败（RHEL 系） | SELinux 拦截了 venv 里的可执行文件。确认 `ls -Z /var/www/clipsync/backend/venv/bin/uvicorn` 为 `bin_t`，不是则重新运行 `deploy.sh` |
| 页面 404 或打开的是 Nginx 默认页 | Debian 系确认已删除 `sites-enabled/default`；RHEL 系确认 `nginx.conf` 里自带的 `server { }` 已注释。然后 `nginx -t` 通过 |
| 页面 502（RHEL 系） | 后端正常时，多半是 SELinux 拦截了 Nginx 反代：`getsebool httpd_can_network_connect` 应为 `on`，可用 `sudo ausearch -m avc -ts recent` 查拒绝记录 |
| 静态页面 403（RHEL 系） | 文件 SELinux 标签不对（常见于从家目录 `mv` 过来）：`sudo restorecon -R /var/www/clipsync` |
| WebSocket 连不上 | 检查 Nginx `/ws` 的 `Upgrade` / `Connection` 头；token 走 `Sec-WebSocket-Protocol`，代理不能剥掉这个头 |
| 所有人一起被限流 | 后端没拿到真实 IP，检查 Nginx 是否设置了 `X-Forwarded-For`，以及 uvicorn 的 `--forwarded-allow-ips` |

## 安全建议

- `.env` 权限设为 600。更换 `JWT_SECRET` 后，所有已签发的 token 会立即失效。
- 防火墙只开放 22 / 80 / 443（Debian 系 `ufw`，RHEL 系 `firewall-cmd --list-all`）。后端 8000 端口和 MySQL 3306 端口只监听本机。
- RHEL 系保持 SELinux 为 enforcing，不要用 `setenforce 0` 绕过问题；按上方故障排查修正标签或布尔值。
- 正式环境使用 HTTPS 并开启 HSTS。
- FastAPI 自带的 `/docs` 没有经过 Nginx 反代，外部访问不到，这是有意的。
