# ClipSync Docker 部署

使用 Docker Compose 快速部署 ClipSync。

## 前提条件

- Docker 20.10+
- Docker Compose 2.0+

## 快速开始

### 1. 准备配置文件

```bash
cd deployment/docker
cp .env.example .env
nano .env
```

**必须修改的配置：**
- `DB_ROOT_PASSWORD`: MySQL root 密码
- `DB_PASSWORD`: 数据库密码
- `JWT_SECRET`: JWT 密钥（用 `openssl rand -hex 32` 生成；未设置时 compose 直接报错）

### 2. 启动服务

```bash
docker-compose up -d
```

首次启动会自动：
1. 拉取/构建镜像
2. 创建数据库
3. 执行数据库迁移
4. 启动所有服务

### 3. 创建超级管理员

```bash
docker-compose exec backend python -m scripts.create_superadmin
```

### 4. 访问应用

- 前端：http://localhost
- 后端 API：http://localhost:8000

## 常用命令

### 查看日志

```bash
# 查看所有服务日志
docker-compose logs -f

# 查看特定服务日志
docker-compose logs -f backend
docker-compose logs -f frontend
docker-compose logs -f db
```

### 停止服务

```bash
docker-compose stop
```

### 重启服务

```bash
docker-compose restart
```

### 停止并删除容器

```bash
docker-compose down
```

### 停止并删除容器和数据

```bash
docker-compose down -v
```

### 更新应用

```bash
# 拉取最新代码
git pull

# 重新构建镜像
docker-compose build

# 重启服务
docker-compose up -d
```

### 进入容器

```bash
# 进入后端容器
docker-compose exec backend bash

# 进入数据库容器
docker-compose exec db mysql -u clipsync -p
```

### 备份数据库

```bash
docker-compose exec db mysqldump \
    -u clipsync -p \
    clipsync > backup_$(date +%Y%m%d_%H%M%S).sql
```

### 恢复数据库

```bash
cat backup.sql | docker-compose exec -T db mysql -u clipsync -p clipsync
```

## 服务说明

### db (MySQL)
- 镜像：`mysql:8.0`
- 端口：3306
- 数据卷：`mysql_data`

### backend (FastAPI)
- 构建自：`../../backend`
- 端口：8000
- 数据卷：`uploads_data`（文件上传）
- 依赖：db

### frontend (Nginx)
- 构建自：`../../frontend`
- 端口：80
- 依赖：backend

## 数据持久化

数据存储在 Docker 卷中：
- `mysql_data`: 数据库数据
- `uploads_data`: 用户上传的文件

查看卷：
```bash
docker volume ls
```

备份卷：
```bash
docker run --rm \
    -v clipsync_mysql_data:/data \
    -v $(pwd):/backup \
    alpine tar czf /backup/mysql_data_backup.tar.gz -C /data .
```

## 生产环境配置

### 使用 HTTPS

1. 获取 SSL 证书（如 Let's Encrypt）

2. 修改 `docker-compose.yml`，挂载证书：

```yaml
frontend:
  volumes:
    - ./nginx/nginx-docker.conf:/etc/nginx/conf.d/default.conf:ro
    - /etc/letsencrypt:/etc/letsencrypt:ro
```

3. 更新 Nginx 配置，添加 HTTPS server 块

4. 修改 `.env`：
```
DEPLOY_SCHEME=https
COOKIE_SECURE=true
HSTS_ENABLED=true
CORS_ORIGINS=https://your-domain.com
```

### 性能优化

1. **worker 数量保持为 1**

backend 必须单 worker 运行：WebSocket 连接表与限流计数都在进程内存中，多 worker 会导致实时同步与限流失效。backend 的 `--forwarded-allow-ips` 已信任容器私有网段，限流按 Nginx 传来的真实客户端 IP 计数。

2. **资源限制**

添加资源限制：
```yaml
backend:
  deploy:
    resources:
      limits:
        cpus: '2'
        memory: 2G
      reservations:
        cpus: '1'
        memory: 1G
```

### 监控与日志

使用 Docker 日志驱动：

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
# 查看容器状态
docker-compose ps

# 查看详细日志
docker-compose logs backend
```

### 数据库连接失败

```bash
# 检查数据库是否健康
docker-compose exec db mysqladmin ping

# 测试连接
docker-compose exec backend python -c "
from app.database import engine
print('Database connected')
"
```

### 端口冲突

修改 `docker-compose.yml` 中的端口映射：
```yaml
ports:
  - "8080:80"  # 将前端改到 8080
```

## 限制与注意事项

1. Docker 部署适合小型部署和开发环境
2. 生产环境建议使用 Kubernetes 或传统部署
3. WebSocket 长连接可能受容器网络影响
4. 大文件上传需要注意卷的磁盘空间

## 从 Docker 迁移到传统部署

1. 备份数据库：
```bash
docker-compose exec db mysqldump -u clipsync -p clipsync > backup.sql
```

2. 导出上传文件：
```bash
docker cp clipsync-backend:/app/uploads ./uploads_backup
```

3. 在目标服务器导入数据和文件

4. 按照 `../DEPLOY.md` 进行传统部署
