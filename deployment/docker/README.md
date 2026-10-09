# ClipSync Docker 部署

使用 Docker Compose 部署 ClipSync。直接部署（systemd + Nginx）见 [../DEPLOY.md](../DEPLOY.md)。

## 前提条件

- Docker 20.10+
- Docker Compose v2（命令为 `docker compose`；旧版独立的 `docker-compose` 也可用）
- 宿主机发行版不限。Rocky Linux / AlmaLinux / RHEL 上请装 Docker CE，不要用系统自带的 Podman：
  ```bash
  sudo dnf config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo
  sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
  sudo systemctl enable --now docker
  sudo firewall-cmd --permanent --add-service=http && sudo firewall-cmd --reload
  ```

## 快速开始

### 1. 准备配置文件

```bash
cd deployment/docker
cp .env.example .env
nano .env
```

**必须修改的配置：**
- `DB_ROOT_PASSWORD`：MySQL root 密码
- `DB_PASSWORD`：应用数据库用户密码
- `JWT_SECRET`：用 `openssl rand -hex 32` 生成。未设置时 compose 直接报错；少于 32 字符或仍是示例值时后端拒绝启动
- `CORS_ORIGINS`：浏览器访问的地址，例如 `http://localhost` 或 `https://your-domain.com`

### 2. 启动服务

```bash
docker compose up -d
```

backend 容器启动时会先执行 `alembic upgrade head`，再以单 worker 启动 uvicorn。数据库由 MySQL 镜像按 `.env` 中的 `DB_NAME` / `DB_USER` 自动创建。

全新数据卷首次启动时 MySQL 需要一段初始化时间，db 的 healthcheck 走 TCP 并设了 30 秒 `start_period`，backend 等它健康后才启动。这一点还没在 Linux 上实测，见 [TODO.md](../../TODO.md)。

### 3. 创建超级管理员

```bash
docker compose exec backend python -m scripts.create_superadmin
```

### 4. 访问应用

- 浏览器访问 http://localhost（前端容器的 Nginx 监听宿主机 80 端口）
- 后端 8000 端口和 MySQL 3306 端口**不对宿主机暴露**，只能在容器网络内访问。API 统一经 `http://localhost/api/...`，WebSocket 经 `/ws`

## 服务说明

| 服务 | 来源 | 宿主机端口 | 数据卷 |
|------|------|-----------|--------|
| db | `mysql:8.0` | 无 | `mysql_data` → `/var/lib/mysql` |
| backend | `../../backend` + `Dockerfile.backend`（Python 3.12，非 root 用户运行） | 无 | `storage_data` → `/app/storage` |
| frontend | `../../frontend` + `Dockerfile.frontend`（Node 22 构建，Nginx 提供服务） | 80 | 挂载 `./nginx-docker.conf` |

- 后端必须保持**单 worker**：WebSocket 连接表与限流计数都在进程内存中。
- compose 定义了固定子网 `172.28.0.0/16`，后端只信任这个网段发来的 `X-Forwarded-For`（即前端容器里的 Nginx）。Nginx 用 `$remote_addr` 覆盖 `X-Forwarded-For`，客户端自带的值一律丢弃，限流拿到的就是真实来源 IP。
- 若 `172.28.0.0/16` 与宿主机已有网段冲突，同时修改 `docker-compose.yml` 里的 `subnet` 和 backend `command` 中的 `--forwarded-allow-ips`。
- `DB_ROOT_PASSWORD`、`DB_PASSWORD`、`JWT_SECRET` 未设置时 `docker compose` 直接报错，不会回落到默认值。

## 常用命令

```bash
docker compose logs -f              # 所有服务日志
docker compose logs -f backend      # 单个服务日志
docker compose ps                   # 容器状态
docker compose stop                 # 停止
docker compose restart              # 重启
docker compose down                 # 删除容器（保留数据卷）
docker compose down -v              # 删除容器和数据卷（数据全部丢失）
```

### 更新应用

```bash
git pull                     # 在项目根目录执行
docker compose build
docker compose up -d         # backend 启动时会自动执行迁移
```

### 进入容器

```bash
docker compose exec backend sh
# 用户名、库名取容器内由 compose 注入的变量，改过 DB_USER / DB_NAME 也不用跟着改命令
docker compose exec db sh -c 'mysql -u "$MYSQL_USER" -p "$MYSQL_DATABASE"'
```

## 备份与恢复

### 数据库

用户名、密码、库名取容器内的 `$MYSQL_USER` / `$MYSQL_PASSWORD` / `$MYSQL_DATABASE`（由 compose 注入），
外层用单引号，变量在容器内展开，宿主机 shell 不需要知道密码：

```bash
# 备份（-T 关闭 TTY，避免输出被破坏）
docker compose exec -T db sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" mysqldump -u "$MYSQL_USER" --single-transaction "$MYSQL_DATABASE"' \
    | gzip > backup_$(date +%Y%m%d_%H%M%S).sql.gz

# 恢复
gunzip -c backup.sql.gz | docker compose exec -T db sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" mysql -u "$MYSQL_USER" "$MYSQL_DATABASE"'
```

### 上传的文件

卷的实际名称带 compose 项目名前缀（默认是目录名），先用 `docker volume ls` 确认，例如：

```bash
docker volume ls | grep storage_data
docker run --rm -v <实际卷名>:/data -v "$(pwd)":/backup \
    alpine tar czf /backup/storage_backup.tar.gz -C /data .
```

也可以直接从容器拷出：

```bash
docker cp clipsync-backend:/app/storage ./storage_backup
```

## 定时任务（宿主机 cron）

Docker 部署不会自动写入 cron，需要在宿主机配置。在 `/etc/cron.d/clipsync-docker` 中写入（把 `/opt/clipsync` 换成实际的项目路径）：

```cron
# 每小时清理过期访问码、过期上传会话与孤儿目录（与直接部署共用 backend/scripts/cleanup_expired.py）
0 * * * * root cd /opt/clipsync/deployment/docker && docker compose exec -T backend python -m scripts.cleanup_expired >> /var/log/clipsync-cleanup.log 2>&1

# 每天凌晨 2 点备份数据库，保留 30 天（cron 里的 % 必须写成 \%）
0 2 * * * root mkdir -p /var/backups/clipsync && cd /opt/clipsync/deployment/docker && docker compose exec -T db sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" mysqldump -u "$MYSQL_USER" --single-transaction "$MYSQL_DATABASE"' | gzip > /var/backups/clipsync/clipsync_$(date +\%Y\%m\%d).sql.gz && find /var/backups/clipsync -name 'clipsync_*.sql.gz' -mtime +30 -delete
```

## 使用 HTTPS

当前 compose 只映射了 80 端口，切换 HTTPS 需要自己完成以下几步：

1. 获取证书（如 Let's Encrypt）。
2. 修改 `docker-compose.yml` 的 frontend 服务：增加 `"443:443"` 端口映射，并挂载证书：
   ```yaml
   frontend:
     ports:
       - "80:80"
       - "443:443"
     volumes:
       - ./nginx-docker.conf:/etc/nginx/conf.d/default.conf:ro
       - /etc/letsencrypt:/etc/letsencrypt:ro
   ```
3. 在 `nginx-docker.conf` 中加入 443 server 块，可参考 `../nginx/clipsync-https.conf`，但要按容器环境改几处：
   - `root` 改为 `/usr/share/nginx/html`
   - `proxy_pass` 改为 `$backend_upstream`，沿用本文件已有的 `resolver 127.0.0.11` 与 `set $backend_upstream`
   - `X-Forwarded-For` 用 `$remote_addr` 覆盖，不要用 `$proxy_add_x_forwarded_for`（后端信任整个 compose 子网，追加写法会放过客户端伪造的值）
   - 现有的 80 端口 server 块只保留跳转：`return 301 https://$host$request_uri;`
4. 修改 `.env`：`HSTS_ENABLED=true`，`CORS_ORIGINS=https://your-domain.com`。
5. `docker compose up -d` 重建。

> 纯 HTTP 下所有数据明文传输，仅用于可信内网。

## 日志轮转

```yaml
services:
  backend:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

## 故障排查

### 容器无法启动

```bash
docker compose ps
docker compose logs backend
```

常见原因：
- `DB_ROOT_PASSWORD`、`DB_PASSWORD`、`JWT_SECRET` 未设置：`docker compose` 在创建容器前直接报错
- `JWT_SECRET` 少于 32 位或含示例占位片段：backend 容器启动后立即退出，日志里有提示
- 数据库尚未就绪：backend 依赖 db 的健康检查，`docker compose ps` 里 db 应为 `healthy`

### 数据库连接失败

```bash
# 数据库是否健康
docker compose exec db mysqladmin ping -u root -p

# 从 backend 实际发起一次查询
docker compose exec backend python -c "
import asyncio
from sqlalchemy import text
from app.database import engine
async def main():
    async with engine.connect() as conn:
        print(await conn.scalar(text('SELECT 1')))
asyncio.run(main())
"
```

### 端口冲突

修改 frontend 的端口映射，例如 `"8080:80"`，同时把 `CORS_ORIGINS` 改为对应地址。

## 从 Docker 迁移到直接部署

1. 按上文备份数据库和 `/app/storage`。
2. 在目标服务器按 [../DEPLOY.md](../DEPLOY.md) 部署。
3. 导入数据库，把文件放到 `backend/storage/`（目录结构 `<user_id>/<uuid>` 保持不变）。
