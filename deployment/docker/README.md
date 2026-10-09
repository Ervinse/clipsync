# ClipSync Docker 部署

使用 Docker Compose 部署 ClipSync。直接部署（systemd + Nginx）见 [../DEPLOY.md](../DEPLOY.md)。

有两种方式：

| | 方式 A：开发机构建（推荐） | 方式 B：服务器上构建 |
|---|---|---|
| 镜像在哪里构建 | 开发机（Windows + Docker Desktop），`build-release.ps1` 打成镜像包 | 服务器，`docker-compose.build.yml` 从源码构建 |
| 服务器上需要的文件 | 镜像包 + 部署包（3 个配置文件） | 完整项目源码 |
| 服务器联网下载 | 不需要（安装 Docker 本身除外） | 需要访问 Docker Hub、Debian、PyPI、npm |
| 适合 | 服务器网络受限，或访问国外下载源很慢 | 服务器网络通畅 |

两种方式用同一份 `docker-compose.yml`、同样的 `.env` 和数据卷，可以互相切换。下文的「部署目录」指 `docker-compose.yml` 所在的目录：方式 A 为解压部署包的目录（示例为 `/opt/clipsync`），方式 B 为 `<项目根>/deployment/docker`。

## 前提条件

- **服务器**：x86_64 架构（`build-release.ps1` 按 `linux/amd64` 构建，ARM 服务器上运行会报 `exec format error`）；Docker 20.10+ 与 Docker Compose v2.20+（`docker compose` 命令。compose 文件用到顶层 `name` 和 `pull_policy`，旧版独立的 `docker-compose` v1 不支持；按下面命令安装的就是新版）。发行版不限，Rocky Linux / AlmaLinux / RHEL 上装 Docker CE，不要用系统自带的 Podman：
  ```bash
  sudo dnf -y install dnf-plugins-core
  sudo dnf -y remove podman buildah runc     # 与 Docker 冲突；提示未安装时忽略
  sudo dnf config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo
  # 国内网络访问 download.docker.com 失败时，改用阿里云镜像源：
  #   sudo dnf config-manager --add-repo https://mirrors.aliyun.com/docker-ce/linux/rhel/docker-ce.repo
  #   sudo sed -i 's|download.docker.com|mirrors.aliyun.com/docker-ce|g' /etc/yum.repos.d/docker-ce.repo
  # docker-buildx-plugin 只有方式 B（服务器上构建）需要
  sudo dnf -y install docker-ce docker-ce-cli containerd.io docker-compose-plugin docker-buildx-plugin
  sudo systemctl enable --now docker
  sudo firewall-cmd --permanent --add-service=http && sudo firewall-cmd --reload
  ```
- **开发机（方式 A）**：Windows 10 22H2 或 Windows 11，安装 Docker Desktop（使用默认的 Linux 容器模式）和 git。

## 方式 A：开发机构建，服务器离线导入

### 1. 开发机：构建并打包

先启动 Docker Desktop，再在项目根目录的 PowerShell 中执行：

```powershell
powershell -ExecutionPolicy Bypass -File deployment\docker\build-release.ps1
```

脚本只打包**已提交**到 git 的代码（默认是当前 HEAD，可用 `-Ref <分支或提交>` 指定），在项目根目录的 `release/`（已 gitignore）生成两个文件：

| 文件 | 内容 |
|---|---|
| `clipsync-images-<提交号>.tar.gz` | 镜像包：`clipsync-backend`、`clipsync-frontend`（各带 `<提交号>` 和 `latest` 两个标签），以及 `mysql:8.0`、`alpine` |
| `clipsync-deploy-<提交号>.tar.gz` | 部署包：`docker-compose.yml`、`nginx-docker.conf`、`.env.example`、本 README |

构建要下载的东西（基础镜像、Python 库、npm 依赖）都在开发机上下载。服务器已经导入过 `mysql:8.0` 和 `alpine` 时，加 `-AppOnly` 只打包两个应用镜像，文件更小（见下文「更新应用」）。

### 2. 上传到服务器

```powershell
scp release\clipsync-images-<提交号>.tar.gz release\clipsync-deploy-<提交号>.tar.gz root@服务器IP:/root/
```

### 3. 服务器：导入镜像、解压部署包

```bash
docker load -i /root/clipsync-images-<提交号>.tar.gz
docker images | grep -E 'clipsync|mysql|alpine'     # 应看到 clipsync-backend、clipsync-frontend、mysql、alpine
mkdir -p /opt/clipsync
tar -xzf /root/clipsync-deploy-<提交号>.tar.gz -C /opt/clipsync
cd /opt/clipsync
```

然后按下文「配置与启动」继续。

## 方式 B：服务器上从源码构建

服务器上需要完整的项目源码（`git clone`，或在开发机用 `git -c core.autocrlf=false archive --format=tar.gz -o ../clipsync.tar.gz HEAD` 打包后上传解压），并且能访问 Docker Hub、Debian、PyPI、npm。

```bash
cd <项目根>/deployment/docker
# 先完成下文「配置与启动」第 1 步（.env），再构建并启动：
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

`docker-compose.build.yml` 给 backend、frontend 加上 `build`，构建出的镜像名与方式 A 相同。构建完成后，`ps`、`logs`、`exec`、`up -d` 等日常命令只用默认的 `docker-compose.yml` 就行，只有重新构建时才需要加 `-f docker-compose.build.yml`。

国内网络：拉取 Docker Hub 镜像失败时，在 `/etc/docker/daemon.json` 里配置 `registry-mirrors`，再 `systemctl restart docker`。镜像加速只对拉取镜像有效；构建时 `pip install`、`npm ci` 下载很慢的话，改用方式 A。

## 配置与启动（两种方式相同，在部署目录执行）

### 1. 准备配置文件

```bash
cp .env.example .env
chmod 600 .env
sed -i "s|^JWT_SECRET=.*|JWT_SECRET=$(openssl rand -hex 32)|" .env   # 随机生成 JWT_SECRET
nano .env
```

**必须修改的配置：**
- `DB_ROOT_PASSWORD`：MySQL root 账号的密码（用户名固定为 `root`）
- `DB_USER` / `DB_PASSWORD`：应用数据库账号与密码，用户名可自定（不能是 `root`）
  - 密码只用字母、数字和 `_ - . @`，至少 12 位；`$ #`、引号、空格、反斜杠在 `.env` 里有特殊含义，会被截断或改写
  - 账号只在数据库**第一次启动**（数据卷为空）时创建，之后改 `.env` 不会生效，反而会让后端连不上数据库
- `JWT_SECRET`：用 `openssl rand -hex 32` 生成。未设置时 compose 直接报错；少于 32 字符或仍是示例值时后端拒绝启动
- `CORS_ORIGINS`：浏览器访问的地址，例如 `http://localhost` 或 `https://your-domain.com`

### 2. 启动服务

```bash
docker compose up -d
```

方式 B 已经在构建那一步启动，可以跳过。

backend 容器启动时会先执行 `alembic upgrade head`，再以单 worker 启动 uvicorn。数据库由 MySQL 镜像按 `.env` 中的 `DB_NAME` / `DB_USER` 自动创建。

全新数据卷首次启动时 MySQL 需要一段初始化时间，db 的 healthcheck 走 TCP 并设了 30 秒 `start_period`，backend 等它健康后才启动。这一点还没在 Linux 上实测，见 [TODO.md](../../TODO.md)。

### 3. 创建超级管理员

```bash
docker compose exec backend python -m scripts.create_superadmin
```

### 4. 访问应用

- 浏览器访问 `http://服务器地址`（前端容器的 Nginx 监听宿主机 80 端口），地址要与 `.env` 的 `CORS_ORIGINS` 一致
- 后端 8000 端口**不对宿主机暴露**，API 统一经 `http://localhost/api/...`，WebSocket 经 `/ws`
- MySQL 3306 端口只绑定宿主机的 `127.0.0.1`：外网和局域网连不进来，只供宿主机本机和 SSH 隧道查询数据库（见下文「远程查询数据库」）

## 服务说明

| 服务 | 来源 | 宿主机端口 | 数据卷 |
|------|------|-----------|--------|
| db | `mysql:8.0` | `127.0.0.1:3306`（仅本机，端口可用 `.env` 的 `DB_HOST_PORT` 修改） | `mysql_data` → `/var/lib/mysql` |
| backend | 镜像 `clipsync-backend`（`Dockerfile.backend`：Python 3.12，非 root 用户运行） | 无 | `storage_data` → `/app/storage` |
| frontend | 镜像 `clipsync-frontend`（`Dockerfile.frontend`：Node 22 构建，Nginx 提供服务） | 80 | 挂载 `./nginx-docker.conf` |

- compose 项目名固定为 `clipsync`（顶层 `name`），数据卷的实际名称是 `clipsync_mysql_data`、`clipsync_storage_data`，不随部署目录的名字变化。
- backend、frontend 设了 `pull_policy: never`：镜像只来自 `docker load` 或方式 B 的本地构建，找不到时直接报错，不会去 Docker Hub 拉同名镜像。用哪个镜像标签由 `.env` 的 `CLIPSYNC_TAG` 决定（默认 `latest`）。
- `Dockerfile.backend` 不安装 gcc 等编译工具：`requirements.txt` 里的依赖都有 x86_64 预编译包，`aiomysql` 是纯 Python。新增的依赖如果没有预编译包，构建时 pip 会因缺编译器报错，到时再在 Dockerfile 里补装。

- 后端必须保持**单 worker**：WebSocket 连接表与限流计数都在进程内存中。
- compose 定义了固定子网 `172.28.0.0/16`，后端只信任这个网段发来的 `X-Forwarded-For`（即前端容器里的 Nginx）。Nginx 用 `$remote_addr` 覆盖 `X-Forwarded-For`，客户端自带的值一律丢弃，限流拿到的就是真实来源 IP。
- 若 `172.28.0.0/16` 与宿主机已有网段冲突，同时修改 `docker-compose.yml` 里的 `subnet` 和 backend `command` 中的 `--forwarded-allow-ips`。
- `DB_ROOT_PASSWORD`、`DB_PASSWORD`、`JWT_SECRET` 未设置时 `docker compose` 直接报错，不会回落到默认值。

## 常用命令

在部署目录执行：

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

**方式 A**：

```powershell
# 开发机：先提交代码再打包；服务器已有 mysql、alpine 镜像时加 -AppOnly
powershell -ExecutionPolicy Bypass -File deployment\docker\build-release.ps1 -AppOnly
scp release\clipsync-images-<提交号>-app.tar.gz release\clipsync-deploy-<提交号>.tar.gz root@服务器IP:/root/
```

```bash
# 服务器：先按「备份与恢复」备份数据库，再导入并重启。部署包里没有 .env，解压不会覆盖已有配置
docker load -i /root/clipsync-images-<提交号>-app.tar.gz
tar -xzf /root/clipsync-deploy-<提交号>.tar.gz -C /opt/clipsync
cd /opt/clipsync && docker compose up -d      # backend 启动时会自动执行迁移
```

回滚到旧版本：用 `docker images clipsync-backend` 查到旧的提交号标签，把 `.env` 的 `CLIPSYNC_TAG` 改成它，再 `docker compose up -d`。数据库迁移不会自动降级，如果这次更新包含迁移，回滚前先用备份恢复数据库。旧镜像占用磁盘时，用 `docker rmi clipsync-backend:<提交号> clipsync-frontend:<提交号>` 删除。

**方式 B**：更新源码（`git pull` 或重新上传解压）后，在 `deployment/docker` 执行 `docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build`。

### 进入容器

```bash
docker compose exec backend sh
# 用户名、库名取容器内由 compose 注入的变量，改过 DB_USER / DB_NAME 也不用跟着改命令
docker compose exec db sh -c 'mysql -u "$MYSQL_USER" -p "$MYSQL_DATABASE"'
```

## 备份与恢复

### 数据库

用户名、密码、库名取容器内的 `$MYSQL_USER` / `$MYSQL_PASSWORD` / `$MYSQL_DATABASE`（由 compose 注入），
外层用单引号，变量在容器内展开，宿主机 shell 不需要知道密码。
`--no-tablespaces`：MySQL 8.0.21 起导出表空间信息需要全局 `PROCESS` 权限，应用账号没有，不加会报 Access denied；本项目没有自定义表空间，跳过不影响恢复。

```bash
# 备份（-T 关闭 TTY，避免输出被破坏）
docker compose exec -T db sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" mysqldump -u "$MYSQL_USER" --single-transaction --no-tablespaces "$MYSQL_DATABASE"' \
    | gzip > backup_$(date +%Y%m%d_%H%M%S).sql.gz

# 恢复
gunzip -c backup.sql.gz | docker compose exec -T db sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" mysql -u "$MYSQL_USER" "$MYSQL_DATABASE"'
```

### 上传的文件

上传的文件在数据卷 `clipsync_storage_data` 里（compose 项目名固定为 `clipsync`）：

```bash
docker run --rm -v clipsync_storage_data:/data:ro -v "$(pwd)":/backup \
    alpine tar czf /backup/storage_backup.tar.gz -C /data .
```

也可以直接从容器拷出：

```bash
docker cp clipsync-backend:/app/storage ./storage_backup
```

## 定时任务（宿主机 cron）

Docker 部署不会自动写入 cron，需要在宿主机配置。在 `/etc/cron.d/clipsync-docker` 中写入。命令里的 `/opt/clipsync` 是方式 A 的部署目录，方式 B 换成 `<项目根>/deployment/docker`：

```cron
# 每小时清理过期访问码、过期上传会话与孤儿目录（与直接部署共用 backend/scripts/cleanup_expired.py）
0 * * * * root cd /opt/clipsync && docker compose exec -T backend python -m scripts.cleanup_expired >> /var/log/clipsync-cleanup.log 2>&1

# 每天凌晨 2 点备份数据库，保留 30 天（cron 里的 % 必须写成 \%）
0 2 * * * root mkdir -p /var/backups/clipsync && cd /opt/clipsync && docker compose exec -T db sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" mysqldump -u "$MYSQL_USER" --single-transaction --no-tablespaces "$MYSQL_DATABASE"' | gzip > /var/backups/clipsync/clipsync_$(date +\%Y\%m\%d).sql.gz && find /var/backups/clipsync -name 'clipsync_*.sql.gz' -mtime +30 -delete

# 每天凌晨 3 点备份上传的文件，保留 7 天（alpine 镜像在方式 A 的镜像包里）
0 3 * * * root mkdir -p /var/backups/clipsync && docker run --rm -v clipsync_storage_data:/data:ro -v /var/backups/clipsync:/backup alpine tar czf /backup/storage_$(date +\%Y\%m\%d).tar.gz -C /data . && find /var/backups/clipsync -name 'storage_*.tar.gz' -mtime +7 -delete
```

备份文件和服务器在同一块硬盘上，硬盘损坏时会一起丢失，请定期复制到其他机器。

## 远程查询数据库（SSH 隧道）

数据库端口只绑定宿主机 `127.0.0.1`，从自己电脑查询时先 SSH 登录服务器，再经这条加密通道连数据库。外网、局域网都不能直接连 3306。

> 不要把 compose 里的端口改成 `"3306:3306"`：Docker 发布的端口会绕过 firewalld，即使防火墙没放行，数据库也会直接暴露在网络上。

### 1. 创建只读账号（建议）

用 root 查询容易误改、误删数据，建议另建只能查询的账号：

```bash
docker compose exec db mysql -u root -p
```

```sql
-- clipsync 为库名（.env 的 DB_NAME）；'%' 是因为隧道进来的连接在容器里看来来自 Docker 网关地址，
-- 端口只绑定 127.0.0.1，外部仍然连不进来
CREATE USER 'reader'@'%' IDENTIFIED BY '自己设的只读密码';
GRANT SELECT ON clipsync.* TO 'reader'@'%';
```

### 2. 图形工具（以 DBeaver 为例）

新建连接 → MySQL：

| 页签 | 项 | 填写 |
|------|----|------|
| SSH | 勾选 Use SSH Tunnel；Host / Port / User / 认证 | 服务器 IP / 22 / 服务器登录用户 / 该用户的密码或私钥 |
| 主页（Main） | Server Host / Port | `127.0.0.1` / `3306`（改过 `DB_HOST_PORT` 则填该值）。隧道另一头在服务器上，对服务器来说数据库就在本机 |
| 主页（Main） | Database / Username / Password | `clipsync` / `reader` / 只读密码 |
| 驱动属性（Driver properties） | `allowPublicKeyRetrieval` | 仅在连接时报 "Public Key Retrieval is not allowed" 时设为 `true`（MySQL 8 的默认认证方式在未启用 SSL 的连接上需要它；数据已经在 SSH 隧道里加密传输） |

MySQL Workbench、HeidiSQL、Navicat 也都支持「通过 SSH 连接」，填写的信息相同。

### 3. 命令行

```bash
# 在自己电脑上：把本机 13306 端口经 SSH 转发到服务器的 127.0.0.1:3306，保持这个窗口不关
ssh -N -L 13306:127.0.0.1:3306 用户@服务器IP
# 另开一个窗口连接本机 13306
mysql -h 127.0.0.1 -P 13306 -u reader -p clipsync
```

### 注意

- 服务器的 SSH 需要允许端口转发（`AllowTcpForwarding`，默认允许）。root 不能用密码登录 SSH 时，改用有 sudo 权限的普通用户。
- 数据库里的剪贴板文本是明文（登录密码只存 bcrypt 哈希）。直接查库会绕过应用里「admin 不能看他人内容」的限制，这个入口只留给运维者本人。
- 宿主机已装有 MySQL 并占用 3306 时，`docker compose up` 会报端口被占用，在 `.env` 里把 `DB_HOST_PORT` 改成 3307 等空闲端口。

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
5. `docker compose up -d --force-recreate frontend`，让新的端口映射和 Nginx 配置生效（挂载的配置文件内容变了，`up -d` 不会自动发现）。

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

### 镜像相关

| 现象 | 原因与处理 |
|------|------|
| `docker compose up` 报 `pull access denied for clipsync-backend`、`No such image` 或提示镜像不存在 | 镜像没有导入，或 `.env` 的 `CLIPSYNC_TAG` 指向不存在的标签。`docker images clipsync-backend` 检查后重新 `docker load` |
| 容器启动即退出，日志为 `exec format error` | 镜像架构与服务器不一致。`build-release.ps1` 按 `linux/amd64` 构建，服务器需为 x86_64（`uname -m` 显示 `x86_64`） |
| `build-release.ps1` 报「无法连接 Docker」 | Docker Desktop 没有启动，或还在启动中。等托盘图标显示 Engine running 后重试 |
| `build-release.ps1` 在 `docker save` 报 `content digest ... not found` | 启用了 containerd 镜像存储且 Docker CLI 较旧、不支持 `docker save --platform`。升级 Docker Desktop，或在 Settings → General 里取消 Use containerd for pulling and storing images |
| 方式 B 构建时 `apt-get` / `pip` / `npm` 长时间卡在下载 | 服务器访问国外下载源很慢（镜像加速只管拉取镜像，不管构建时的下载）。改用方式 A |

## 从 Docker 迁移到直接部署

1. 按上文备份数据库和 `/app/storage`。
2. 在目标服务器按 [../DEPLOY.md](../DEPLOY.md) 部署。
3. 导入数据库，把文件放到 `backend/storage/`（目录结构 `<user_id>/<uuid>` 保持不变）。
