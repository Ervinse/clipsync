# ClipSync 部署资源

本目录包含 ClipSync 的所有部署相关资源。

## 目录结构

```
deployment/
├── README.md                      # 本文件
├── DEPLOY.md                      # 详细部署文档
├── CHECKLIST.md                   # 部署检查清单
├── .env.production.example        # 生产环境配置模板
├── nginx/
│   └── clipsync.conf              # Nginx 配置（HTTP + HTTPS）
├── systemd/
│   └── clipsync.service           # Systemd 服务配置
├── scripts/
│   ├── deploy.sh                  # 自动化部署脚本
│   ├── update.sh                  # 更新脚本
│   ├── backup_database.sh         # 数据库备份脚本
│   ├── cleanup_expired.sh         # 清理过期数据脚本
│   └── health_check.sh            # 健康检查脚本
└── docker/
    ├── README.md                  # Docker 部署文档
    ├── docker-compose.yml         # Docker Compose 配置
    ├── Dockerfile.backend         # 后端 Dockerfile
    ├── Dockerfile.frontend        # 前端 Dockerfile
    ├── nginx-docker.conf          # Docker 环境 Nginx 配置
    └── .env.example               # Docker 环境变量模板
```

## 快速开始

### 方式一：自动化脚本部署（推荐）

适合 Ubuntu/Debian/CentOS 等标准 Linux 发行版。

```bash
# 1. 上传项目到服务器
cd /var/www
sudo git clone <your-repo> clipsync
cd clipsync

# 2. 配置后端环境变量
cd backend
sudo cp ../deployment/.env.production.example .env
sudo nano .env  # 编辑配置

# 3. 执行自动化部署
cd ..
sudo bash deployment/scripts/deploy.sh

# 4. 启动服务
sudo systemctl start clipsync
sudo systemctl enable clipsync
sudo systemctl restart nginx
```

详细步骤见 [DEPLOY.md](DEPLOY.md)。

### 方式二：Docker 部署

适合容器化环境或快速测试。

```bash
cd deployment/docker
cp .env.example .env
nano .env  # 编辑配置
docker-compose up -d
docker-compose exec backend python -m scripts.create_superadmin
```

详细步骤见 [docker/README.md](docker/README.md)。

## 文件说明

### 配置文件

**nginx/clipsync.conf**
- Nginx 反向代理配置
- 包含 HTTP 和 HTTPS 两套配置
- 支持 WebSocket 转发
- 静态资源缓存优化

**systemd/clipsync.service**
- Systemd 服务单元文件
- 配置后端服务的启动方式
- 包含环境变量加载、重启策略等

**.env.production.example**
- 生产环境配置模板
- 包含所有必需和可选配置项
- 使用前需复制为 `.env` 并填写实际值

### 脚本文件

**deploy.sh**
- 自动化部署脚本
- 检查依赖、配置服务、设置定时任务
- 适合首次部署

**update.sh**
- 应用更新脚本
- 停止服务 → 备份 → 更新代码 → 迁移数据库 → 重启
- 适合后续更新

**backup_database.sh**
- 数据库备份脚本
- 自动压缩、保留 30 天
- 配合 Cron 定时执行

**cleanup_expired.sh**
- 清理过期数据脚本
- 删除过期访问码和未完成的上传
- 配合 Cron 定时执行

**health_check.sh**
- 健康检查脚本
- 检查服务、数据库、磁盘、内存等
- 用于日常监控

### Docker 文件

**docker-compose.yml**
- 定义三个服务：db, backend, frontend
- 配置数据卷和网络
- 包含健康检查

**Dockerfile.backend**
- 后端镜像构建
- 基于 Python 3.11 slim
- 安装依赖并启动 Uvicorn

**Dockerfile.frontend**
- 前端镜像构建（多阶段）
- 第一阶段：Node.js 构建
- 第二阶段：Nginx 提供服务

## 使用场景

### 场景一：开发环境测试

使用 Docker Compose 快速启动：

```bash
cd deployment/docker
docker-compose up
```

### 场景二：内网生产部署（HTTP）

1. 使用 `deploy.sh` 自动部署
2. 配置 `.env` 为 `DEPLOY_SCHEME=http`
3. 使用 Nginx HTTP 配置

### 场景三：公网生产部署（HTTPS）

1. 获取 SSL 证书（Let's Encrypt）
2. 配置 `.env` 为 `DEPLOY_SCHEME=https`
3. 更新 Nginx 配置中的证书路径
4. 启用 HTTPS 相关安全选项

### 场景四：应用更新

```bash
cd /var/www/clipsync
sudo bash deployment/scripts/update.sh
```

### 场景五：定期维护

```bash
# 检查健康状态
sudo bash deployment/scripts/health_check.sh

# 手动备份数据库
sudo bash deployment/scripts/backup_database.sh

# 清理过期数据
sudo bash deployment/scripts/cleanup_expired.sh
```

## 定时任务

部署脚本会自动配置以下定时任务（/etc/cron.d/clipsync）：

- **每天凌晨 2 点**：备份数据库
- **每小时**：清理过期访问码和临时文件

查看定时任务日志：
```bash
sudo tail -f /var/log/clipsync/backup.log
sudo tail -f /var/log/clipsync/cleanup.log
```

## 常用命令

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

# 查看日志
sudo journalctl -u clipsync -f
```

### 数据库操作

```bash
# 备份
sudo bash deployment/scripts/backup_database.sh

# 恢复（需要先解压备份文件）
gunzip < backup.sql.gz | mysql -u clipsync -p clipsync

# 查看备份
ls -lh /var/backups/clipsync/database/
```

### Nginx 操作

```bash
# 测试配置
sudo nginx -t

# 重载配置
sudo systemctl reload nginx

# 查看日志
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

### Docker 操作

```bash
# 启动
docker-compose up -d

# 停止
docker-compose stop

# 查看日志
docker-compose logs -f

# 重新构建
docker-compose build

# 清理
docker-compose down -v
```

## 故障排查

常见问题及解决方案见 [DEPLOY.md](DEPLOY.md) 的"故障排查"章节。

快速诊断：
```bash
# 运行健康检查
sudo bash deployment/scripts/health_check.sh

# 查看最近错误
sudo journalctl -u clipsync -p err --since "1 hour ago"
```

## 安全建议

1. **保护配置文件**
   - `.env` 文件包含敏感信息，权限设为 600
   - 定期更换 JWT 密钥和数据库密码

2. **启用 HTTPS**
   - 使用 Let's Encrypt 免费证书
   - 启用 HSTS

3. **配置防火墙**
   ```bash
   sudo ufw allow 80/tcp
   sudo ufw allow 443/tcp
   sudo ufw enable
   ```

4. **定期更新**
   - 系统软件包
   - Python 依赖
   - Node.js 依赖

5. **监控日志**
   - 检查异常访问
   - 监控失败的登录尝试

## 性能优化

1. **调整 Workers**
   - 根据 CPU 核心数调整 Uvicorn workers
   - 编辑 `systemd/clipsync.service`

2. **数据库优化**
   - 调整 MySQL buffer pool size
   - 启用慢查询日志

3. **Nginx 缓存**
   - 静态资源已配置 30 天缓存
   - 可根据需要调整

## 扩展部署

### 多实例负载均衡

使用 Nginx upstream 配置多个后端实例：

```nginx
upstream clipsync_backend {
    server 127.0.0.1:8000;
    server 127.0.0.1:8001;
    server 127.0.0.1:8002;
}
```

**注意**：多实例需要引入 Redis 等跨进程消息机制来支持 WebSocket 广播。

### 对象存储

将文件上传到 S3/OSS 等对象存储，减轻服务器磁盘压力。

## 文档索引

- [DEPLOY.md](DEPLOY.md) - 详细部署步骤、配置说明、故障排查
- [CHECKLIST.md](CHECKLIST.md) - 部署检查清单
- [docker/README.md](docker/README.md) - Docker 部署专用文档
- [../backend/README.md](../backend/README.md) - 后端开发文档
- [../frontend/README.md](../frontend/README.md) - 前端开发文档
- [../DESIGN.md](../DESIGN.md) - 技术设计文档

## 获取帮助

- 查看文档：优先查阅上述文档
- 检查日志：`sudo journalctl -u clipsync -f`
- 运行健康检查：`sudo bash deployment/scripts/health_check.sh`
- 问题反馈：GitHub Issues

---

**维护建议**：每月检查一次备份、日志和系统资源使用情况。
