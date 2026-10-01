# ClipSync 部署资源索引

本目录存放部署相关的配置和脚本。**部署步骤以 [DEPLOY.md](DEPLOY.md) 为准**，本文件只说明每个文件的用途。

## 目录结构

```
deployment/
├── README.md                  # 本文件（索引）
├── DEPLOY.md                  # 部署权威文档：步骤、HTTPS 切换、维护、排障
├── CHECKLIST.md               # 部署检查清单
├── .env.production.example    # 生产环境 backend/.env 模板
├── nginx/
│   ├── clipsync.conf          # HTTP 阶段（deploy.sh 默认安装）
│   └── clipsync-https.conf    # HTTPS 阶段（80 跳转 443 + TLS）
├── systemd/
│   └── clipsync.service       # uvicorn 单 worker，只监听 127.0.0.1:8000
├── scripts/
│   ├── deploy.sh              # 首次部署（不建库，需先按 DEPLOY.md 建库）
│   ├── update.sh              # 更新：备份 → 在项目根 git pull → 迁移 → 构建 → 重启
│   ├── backup_database.sh     # 从 backend/.env 读连接信息，mysqldump + gzip，保留 30 天
│   ├── cleanup_expired.sh     # 清理过期访问码、超时上传会话及其临时目录
│   └── health_check.sh        # 检查服务、接口、数据库、磁盘、备份
└── docker/
    ├── README.md              # Docker 部署文档
    ├── docker-compose.yml     # db / backend / frontend 三个服务
    ├── Dockerfile.backend     # python:3.12-slim，非 root 运行
    ├── Dockerfile.frontend    # node:22-alpine 构建 + nginx:alpine 提供服务
    ├── nginx-docker.conf      # 前端容器内的 Nginx 配置
    └── .env.example           # compose 环境变量模板
```

## 定时任务（deploy.sh 写入 `/etc/cron.d/clipsync`）

- 每天 2:00：`backup_database.sh`，日志写入 `/var/log/clipsync/backup.log`
- 每小时：`cleanup_expired.sh`，日志写入 `/var/log/clipsync/cleanup.log`

## 重要约束

- 后端**必须单 worker**，不支持多实例负载均衡。WebSocket 广播和限流计数都依赖进程内存。
- 只支持 Debian / Ubuntu（脚本使用 apt、`sites-available`、`www-data`）。

## 相关文档

- [DEPLOY.md](DEPLOY.md)：部署步骤与维护
- [CHECKLIST.md](CHECKLIST.md)：上线前逐项核对
- [docker/README.md](docker/README.md)：Docker 部署
- [../README.md](../README.md)：项目说明与开发环境
- [../DESIGN.md](../DESIGN.md)：技术设计
- [../frontend/README.md](../frontend/README.md)：前端说明
