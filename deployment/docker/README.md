# ClipSync Docker 部署

使用 Docker Compose 部署 ClipSync。直接部署（systemd + Nginx）见 [../DEPLOY.md](../DEPLOY.md)。

## 前提条件

- Docker 20.10+
- Docker Compose v2（命令为 `docker compose`；旧版独立的 `docker-compose` 也可用）

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
- 后端只信任私有网段（`172.16.0.0/12`、`10.0.0.0/8`、`192.168.0.0/16`）发来的 `X-Forwarded-For`，即前端容器里的 Nginx，限流才能拿到真实客户端 IP。

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
docker compose exec db mysql -u clipsync -p clipsync
```

## 备份与恢复

### 数据库

```bash
# 备份（-T 关闭 TTY，避免输出被破坏）
docker compose exec -T db mysqldump -u clipsync -p"$DB_PASSWORD" \
    --single-transaction clipsync > backup_$(date +%Y%m%d_%H%M%S).sql

# 恢复
docker compose exec -T db mysql -u clipsync -p"$DB_PASSWORD" clipsync < backup.sql
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
3. 在 `nginx-docker.conf` 中加入 443 server 块（可参考 `../nginx/clipsync-https.conf`，把 `proxy_pass` 改为 `http://backend:8000`）。
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

常见原因：`JWT_SECRET` 未设置或过弱、数据库尚未就绪（backend 依赖 db 的健康检查）。

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
