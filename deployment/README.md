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
│   ├── os_env.sh              # 被 deploy.sh / update.sh 引入：识别发行版，给出应用用户、Nginx 配置位置、MySQL 服务名，处理 SELinux
│   ├── test_os_env.sh         # os_env.sh 的自测（伪造 os-release 与桩命令，不需要 root）
│   ├── deploy.sh              # 首次部署（不建库，需先按 DEPLOY.md 建库）
│   ├── update.sh              # 更新：备份 → 以项目属主在项目根 git pull → 迁移 → npm ci 构建 → 重启；失败时自动拉起服务
│   ├── backup_database.sh     # 从 backend/.env 读连接信息，mysqldump + gzip，保留 30 天
│   ├── cleanup_expired.sh     # 调用 backend/scripts/cleanup_expired.py：过期访问码、超时上传会话、孤儿目录
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
- 直接部署支持 Debian / Ubuntu 与 Rocky Linux / AlmaLinux / RHEL 9+，发行版差异集中在 `scripts/os_env.sh`。CentOS 7 / 8 等旧系统请用 Docker。
- `systemd/clipsync.service` 按 Debian 系书写，`deploy.sh` 安装时按发行版替换运行用户和 MySQL 服务名；手动安装到 RHEL 系时要自己改。
- 修改 `os_env.sh` 后运行 `bash scripts/test_os_env.sh`。
- cron 用 `bash 脚本路径` 调用，不依赖脚本的可执行位。

## 相关文档

- [DEPLOY.md](DEPLOY.md)：部署步骤与维护
- [CHECKLIST.md](CHECKLIST.md)：上线前逐项核对
- [docker/README.md](docker/README.md)：Docker 部署
- [../README.md](../README.md)：项目说明、技术设计与开发环境
- [../frontend/README.md](../frontend/README.md)：前端说明
