# ClipSync 部署手册

ClipSync 只支持 Docker Compose 部署：MySQL、后端、前端（Nginx）三个容器运行在一台 x86_64 Linux 服务器上。项目设计与开发环境见根目录的 README.md。

本文件也会放进部署包。下文的「部署目录」指 `docker-compose.yml` 所在的目录：方式 A 为解压部署包的目录（示例为 `/opt/clipsync`），方式 B 为 `<项目根>/deployment/docker`。没有特别说明时，服务器上的命令都以 root 身份在部署目录执行。

## 1. 架构

```
浏览器 ──80 / 443──▶ frontend（Nginx：静态页面）──/api、/ws──▶ backend（FastAPI，单 worker）──▶ db（MySQL 8.4）
                                                               数据卷 clipsync_storage_data        数据卷 clipsync_mysql_data
```

| 服务 | 镜像 | 宿主机端口 | 数据 |
|------|------|-----------|------|
| db | `mysql:8.4.x`（版本号固定在 `docker-compose.yml`） | `127.0.0.1:3306`（`DB_HOST_PORT`） | 数据卷 `clipsync_mysql_data` |
| backend | `clipsync-backend:<CLIPSYNC_TAG>` | 无 | 数据卷 `clipsync_storage_data` → `/app/storage` |
| frontend | `clipsync-frontend:<CLIPSYNC_TAG>` | `HTTP_PORT`（默认 80），启用 HTTPS 时另加 443 | 无 |

- compose 项目名固定为 `clipsync`，网络和数据卷名不随部署目录的名字变化。
- backend 每次启动先执行 `alembic upgrade head` 升级表结构，再以**单 worker** 运行 uvicorn。WebSocket 连接表与限流计数都在进程内存中，不能多进程、多实例运行。
- 数据库端口只绑定宿主机 `127.0.0.1`，外部连不进来，只供宿主机本机和 SSH 隧道查询（第 12 节）。
- backend、frontend 设了 `pull_policy: never`：镜像只来自 `docker load` 或方式 B 的本地构建，找不到时直接报错，不会去镜像仓库拉同名镜像。
- 每个容器的日志最多保留 3 个 10MB 的文件。backend 以非 root 用户运行，去掉了全部 Linux capability。

部署目录里的文件：

| 文件 | 作用 |
|------|------|
| `.env` | 你的配置（从 `.env.example` 复制）。部署包里没有，更新时不会被覆盖 |
| `docker-compose.yml` | 三个服务的定义 |
| `docker-compose.https.yml` / `docker-compose.build.yml` | 叠加使用：启用 HTTPS / 在服务器上从源码构建 |
| `nginx-common.conf`、`nginx-docker.conf`、`nginx-https.conf` | frontend 容器的 Nginx 配置（公共规则 / HTTP 站点 / HTTPS 站点） |
| `backup.sh`、`health_check.sh`、`cert.sh` | 备份、健康检查、HTTPS 证书申请与续期 |
| `clipsync.cron`、`clipsync.logrotate` | 宿主机定时任务与其日志轮转的模板 |
| `VERSION` | 方式 A 的部署包才有：打包时的分支、提交号、时间；正式版本的发布包还有版本号 |
| `acme/`、`letsencrypt/` | 运行后自动生成：证书验证文件、HTTPS 证书 |

除 `.env` 外，这些文件会在每次更新部署包时被覆盖。需要调整的配置都放在 `.env` 里，不要直接修改其他文件。

## 2. 版本与分支

- 正式部署使用 **master** 分支上的提交。
- `build-release.ps1` 给镜像打 `<提交号>` 标签（git 提交号的前 12 位）。只有打包的是 master 的最新提交时，才额外打 `latest` 标签。
- 服务器 `.env` 的 `CLIPSYNC_TAG` 默认是 `latest`，所以只会运行 master 的版本。要部署其他分支（比如测试一个还没合并的功能），把 `CLIPSYNC_TAG` 改成那次打包的提交号；测试结束后改回 `latest`。
- 测试通过的构建用 `publish-release.ps1` 晋级为正式版本（第 4.4 节）：不重新构建，给同一份镜像追加 `<版本号>` 标签（如 `1.0.0-alpha.1`），发布包里的镜像只有 `<版本号>` 和 `<提交号>` 两个标签，没有 `latest`。
- 镜像包和部署包来自同一次打包，文件名里的提交号（或版本号）相同，不要混用不同版本的两个包。
## 3. 环境要求

**服务器**

- x86_64 架构（`uname -m` 显示 `x86_64`）。镜像按 `linux/amd64` 构建，ARM 服务器上运行会报 `exec format error`。
- Docker Engine 20.10+ 与 Docker Compose v2.20+（`docker compose version`）。compose 文件用到顶层 `name` 和 `pull_policy`，旧版独立的 `docker-compose` v1 不支持。发行版不限，按 [Docker 官方文档](https://docs.docker.com/engine/install/) 安装。Rocky Linux / AlmaLinux / RHEL 示例（不要用系统自带的 Podman）：
  ```bash
  dnf -y install dnf-plugins-core
  dnf -y remove podman buildah runc        # 与 Docker 冲突；提示未安装时忽略
  dnf config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo
  dnf -y install docker-ce docker-ce-cli containerd.io docker-compose-plugin docker-buildx-plugin
  systemctl enable --now docker crond
  ```
  `docker-buildx-plugin` 只有方式 B 需要。访问 `download.docker.com` 慢时可改用国内镜像源（如 `mirrors.aliyun.com/docker-ce`）。
- 内存 1GB 以上（MySQL 约占 400MB），磁盘按上传文件量预留，并给备份留出同样多的空间。

**网络与防火墙**

- 云服务器在控制台的**安全组**里放行 SSH 端口与 `HTTP_PORT`（默认 80），启用 HTTPS 时再放行 443。
- Docker 发布的端口会绕过 firewalld / ufw：防火墙没放行，端口照样能从外部访问。所以不要靠宿主机防火墙挡端口，数据库端口也只绑定在 `127.0.0.1`。

**开发机（只有方式 A 需要）**

- Windows 10 22H2 或 Windows 11，安装 Docker Desktop（默认的 Linux 容器模式）和 git，并能访问 Docker Hub、PyPI、npm。

## 4. 方式 A：开发机构建，服务器离线导入（推荐）

镜像在开发机上构建，服务器只需要导入，不用联网下载任何依赖。

### 4.1 开发机：构建并打包

先启动 Docker Desktop，等它显示 Engine running。然后在项目根目录的 PowerShell 中执行：

```powershell
git switch master        # 正式部署用 master；git status 应显示 working tree clean
powershell -ExecutionPolicy Bypass -File deployment\docker\build-release.ps1
```

脚本先显示要打包的分支、提交和镜像标签。打包的不是 master 的最新提交，或者工作区有未提交的改动时，会要求输入 `y` 确认。脚本只打包**已提交**的代码，未提交的改动不会进入镜像。

| 参数 | 作用 |
|------|------|
| `-Ref <分支或提交>` | 打包指定的提交，默认是当前检出的提交 |
| `-AppOnly` | 不打包 MySQL 镜像（服务器上已有同版本时用，文件更小） |
| `-WithCertbot` | 额外打包 certbot 镜像（服务器拉取不到 Docker Hub、又要申请 HTTPS 证书时用） |
| `-Yes` | 跳过确认 |

产物在项目根目录的 `release\<提交号>\`：

| 文件 | 内容 |
|------|------|
| `clipsync-images-<提交号>[-app].tar.gz` | 镜像包：`clipsync-backend`、`clipsync-frontend`，以及 MySQL（`-AppOnly` 时没有） |
| `clipsync-deploy-<提交号>.tar.gz` | 部署包：第 1 节表格中的文件和本手册 |
### 4.2 上传到服务器

```powershell
scp release\<提交号>\clipsync-images-<提交号>.tar.gz release\<提交号>\clipsync-deploy-<提交号>.tar.gz root@<服务器IP>:/root/
```

使用正式版本的发布包时，把文件名里的 `<提交号>` 换成 `<版本号>`（第 4.4 节）。

### 4.3 服务器：导入镜像、解压部署包

```bash
docker load -i /root/clipsync-images-<提交号>.tar.gz
docker images | grep -E 'clipsync|mysql'        # 应看到 clipsync-backend、clipsync-frontend、mysql
mkdir -p /opt/clipsync
tar -xzf /root/clipsync-deploy-<提交号>.tar.gz -C /opt/clipsync
cd /opt/clipsync && cat VERSION
```

然后按第 6 节「配置与启动」继续。

### 4.4 正式版本的发布包

测试通过的构建在开发机上晋级为正式版本。先在要发布的提交（必须在 master 上）建好 Git 标签 `v<版本号>`，然后执行：

```powershell
powershell -ExecutionPolicy Bypass -File deployment\docker\publish-release.ps1 -Version <版本号>
```

脚本不重新构建镜像：检查本机有该提交的 `clipsync-backend:<提交号>`、`clipsync-frontend:<提交号>`，且镜像里记录的提交号一致，再追加 `<版本号>` 标签导出。本机镜像被清理过时，先 `docker load` 导入该提交测试时的镜像包。产物在 `release\<版本号>\`：

| 文件 | 内容 |
|------|------|
| `clipsync-images-<版本号>.tar.gz` | 镜像包：backend、frontend（各带 `<版本号>` 与 `<提交号>` 标签）、MySQL |
| `clipsync-deploy-<版本号>.tar.gz` | 部署包：与测试构建的部署包相同，只有两处不同：`.env.example` 的 `CLIPSYNC_TAG` 预填为 `<版本号>`；`VERSION` 多了 `version=`、`published=` 两行 |
| `SHA256SUMS` | 两个包的 SHA-256 |

使用发布包部署：

```bash
cd /root && sha256sum -c SHA256SUMS          # 两行都显示 OK 再继续
docker load -i clipsync-images-<版本号>.tar.gz
mkdir -p /opt/clipsync && tar -xzf clipsync-deploy-<版本号>.tar.gz -C /opt/clipsync
```

- 首次部署：从 `.env.example` 复制出的 `.env` 已经是 `CLIPSYNC_TAG=<版本号>`，不用修改。
- 已有部署更新到正式版本：解压部署包不会覆盖 `.env`，要手动把 `.env` 的 `CLIPSYNC_TAG` 改成 `<版本号>`。发布包里没有 `latest` 标签，`CLIPSYNC_TAG` 仍是 `latest` 时会用回旧镜像，或因找不到镜像而启动失败。
- 核对和测试过的是同一份镜像：发布脚本最后打印的镜像 ID，与测试服务器上 `docker images clipsync-backend` 显示的 IMAGE ID 相同。开发机启用了 containerd 镜像存储时，本机 `docker images` 显示的 ID 是另一种摘要，以脚本打印的为准。

## 5. 方式 B：服务器上从源码构建

服务器上需要完整的项目源码，并且能访问 Docker Hub、Debian、PyPI、npm。

```bash
git clone <仓库地址> clipsync && cd clipsync && git switch master
cd deployment/docker
# 先完成第 6.1 节（准备 .env），再构建并启动：
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

`docker-compose.build.yml` 给 backend、frontend 加上 `build`，构建出的镜像名与方式 A 相同（标签为 `.env` 的 `CLIPSYNC_TAG`，默认 `latest`）。日常的 `ps`、`logs`、`exec`、`up -d` 只用默认的 `docker-compose.yml`，只有重新构建时才需要加 `-f docker-compose.build.yml`。

拉取 Docker Hub 镜像慢时，可以在 `/etc/docker/daemon.json` 里配置 `registry-mirrors` 后 `systemctl restart docker`。镜像加速只影响拉取镜像，不影响构建时 `pip install`、`npm ci` 的下载，构建很慢时改用方式 A。

## 6. 配置与启动（两种方式相同）

### 6.1 准备配置文件

```bash
cp .env.example .env
chmod 600 .env
# 随机生成两个数据库密码和 JWT 密钥
sed -i "s|^DB_ROOT_PASSWORD=.*|DB_ROOT_PASSWORD=$(openssl rand -hex 16)|" .env
sed -i "s|^DB_PASSWORD=.*|DB_PASSWORD=$(openssl rand -hex 16)|" .env
sed -i "s|^JWT_SECRET=.*|JWT_SECRET=$(openssl rand -hex 32)|" .env
vi .env          # 至少修改 CORS_ORIGINS
```

`.env` 里的值只用字母、数字和 `_ - . @ : / ,`：`$`、`#`、引号、空格、反斜杠在 compose 的 `.env` 里有特殊含义，会被截断或改写。

### 6.2 配置说明

| 变量 | 说明 | 默认 |
|------|------|------|
| `CLIPSYNC_TAG` | 使用哪个版本的镜像：`latest`、提交号或正式版本号（第 2 节） | `latest`（正式版本发布包里的模板预填版本号） |
| `HTTP_PORT` | 网站端口。启用 HTTPS 时必须是 80 | `80` |
| `DB_HOST_PORT` | 数据库在宿主机 `127.0.0.1` 上的端口，3306 被占用时修改 | `3306` |
| `COMPOSE_FILE` | 启用 HTTPS 时设为 `docker-compose.yml:docker-compose.https.yml`（第 9 节） | 不设置 |
| `DB_ROOT_PASSWORD` | MySQL root 密码（用户名固定为 `root`） | 必填 |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` | 应用使用的库名、账号、密码。`DB_USER` 不能是 `root` | `clipsync` / `clipsync` / 必填 |
| `JWT_SECRET` | 登录令牌的签名密钥，至少 32 位。修改后所有用户需要重新登录 | 必填 |
| `JWT_ALGORITHM` / `JWT_EXPIRE_MINUTES` | 签名算法（HS256/384/512）、令牌有效期（分钟） | `HS256` / `10080`（7 天） |
| `CORS_ORIGINS` | 浏览器地址栏里的访问地址（协议 + 域名或 IP + 非默认端口），逗号分隔，不支持 `*` | `http://localhost` |
| `HSTS_ENABLED` | HTTPS 生效后设为 `true`，HTTP 阶段必须为 `false` | `false` |
| `DEFAULT_QUOTA_BYTES` | 新用户默认配额（管理后台的设置优先） | 100MB |
| `MAX_FILE_BYTES` | 单文件上限 | 500MB |
| `CHUNK_SIZE` | 单个上传分片上限，不能超过 Nginx 的 10MB | 5MB |
| `MAX_UPLOAD_SESSIONS_PER_USER` / `UPLOAD_SESSION_TTL_HOURS` | 每用户同时上传数、未完成上传的保留小时数 | `5` / `24` |
| `HISTORY_KEEP` | 每个用户保留的文本历史条数 | `50` |
| `DEPLOY_SCHEME` / `COOKIE_SECURE` | 预留，代码未使用 | — |

- 三个必填项未设置时 `docker compose` 直接报错；`JWT_SECRET` 太短或仍是示例值时 backend 拒绝启动。
- 数据库账号只在**第一次启动**（数据卷为空）时创建。之后修改 `DB_USER`、`DB_PASSWORD`、`DB_ROOT_PASSWORD` 不会改变数据库里的账号，反而会让 backend 连不上数据库。要改密码，先在数据库里 `ALTER USER`，再同步修改 `.env`。
- `CORS_ORIGINS` 只影响从其他网址跨域调用接口；浏览器直接访问本站时不受它影响。仍建议填写实际访问地址。
- 修改 `.env` 后执行 `docker compose up -d`，compose 会重建配置有变化的容器。

### 6.3 启动

```bash
docker compose up -d          # 方式 B 已在构建时启动，可跳过
docker compose ps             # db 为 healthy，backend、frontend 为 Up
```

全新数据卷首次启动时，MySQL 需要几十秒初始化，backend 会等 db 的健康检查通过后才启动。

### 6.4 创建超级管理员

```bash
docker compose exec backend python -m scripts.create_superadmin
```

按提示输入用户名和密码（密码不回显）。用户名 3–64 位，只能含字母、数字和 `_ . -`（不能含 `@`）。之后用浏览器访问 `CORS_ORIGINS` 里的地址登录，在管理后台生成邀请码给其他用户注册。

### 6.5 安装定时任务

```bash
mkdir -p /var/log/clipsync
sed "s|/opt/clipsync|$(pwd)|g" clipsync.cron > /etc/cron.d/clipsync && chmod 644 /etc/cron.d/clipsync
cp clipsync.logrotate /etc/logrotate.d/clipsync
```

| 时间 | 任务 | 日志 |
|------|------|------|
| 每小时 | 清理过期访问码、过期上传会话与残留目录 | `/var/log/clipsync/cleanup.log` |
| 每天 02:30 | `backup.sh`：备份数据库与上传的文件 | `/var/log/clipsync/backup.log` |
| 每天 04:15 | `cert.sh renew`：证书快到期时续期（没有证书时什么都不做） | `/var/log/clipsync/cert.log` |

cron 需要 `crond`（RHEL 系）或 `cron`（Debian 系）服务在运行。

### 6.6 检查

```bash
bash health_check.sh
```

检查版本、容器状态与重启次数、首页与接口、数据库连接、磁盘、最近一次备份、证书有效期。全部正常时最后显示「全部正常」。
## 7. 更新

更新前先备份（`bash backup.sh`）。backend 启动时会自动执行数据库迁移，迁移不会自动回退。

### 7.1 方式 A

```powershell
# 开发机：在 master 上打包。这次更新没有改 MySQL 版本时加 -AppOnly
git switch master
powershell -ExecutionPolicy Bypass -File deployment\docker\build-release.ps1 -AppOnly
scp release\<提交号>\clipsync-images-<提交号>-app.tar.gz release\<提交号>\clipsync-deploy-<提交号>.tar.gz root@<服务器IP>:/root/
```

```bash
# 服务器
cd /opt/clipsync
bash backup.sh
docker load -i /root/clipsync-images-<提交号>-app.tar.gz
tar -xzf /root/clipsync-deploy-<提交号>.tar.gz -C /opt/clipsync     # 不会覆盖 .env
cat VERSION
docker compose up -d
# 挂载的 Nginx 配置内容变化时 compose 发现不了，强制重建 frontend、backend 让新配置生效（db 不受影响）
docker compose up -d --force-recreate backend frontend
# 部署包里的定时任务模板可能有变化，重新安装一次
sed "s|/opt/clipsync|$(pwd)|g" clipsync.cron > /etc/cron.d/clipsync
bash health_check.sh
```

部署非 master 的测试版本时，先把 `.env` 的 `CLIPSYNC_TAG` 改成打包时显示的提交号，再执行 `docker compose up -d`。

更新到正式版本的发布包时，命令相同，文件名里的 `<提交号>` 换成 `<版本号>`，并在 `docker compose up -d` 前把 `.env` 的 `CLIPSYNC_TAG` 改成 `<版本号>`（第 4.4 节）。

### 7.2 方式 B

```bash
cd <项目根> && git pull
cd deployment/docker
bash backup.sh
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
docker compose up -d --force-recreate frontend
```

## 8. 回滚

方式 A 的旧版本镜像在 `docker load` 后会一直保留在服务器上（`docker images clipsync-backend` 可以看到各个提交号和版本号）。

```bash
bash backup.sh
vi .env                     # CLIPSYNC_TAG 改成旧的版本号或提交号
docker compose up -d
```

- 如果要回滚的那次更新包含数据库迁移，旧版本可能无法使用新的表结构：先按第 10.3 节用更新前的备份恢复数据库，再回滚。
- 新旧版本的 compose 或 Nginx 配置有差别时，再把旧版本的部署包解压到部署目录，然后执行 `docker compose up -d --force-recreate backend frontend`。所以建议在服务器上保留最近几次的部署包。
- 旧镜像占用磁盘时删除：`docker rmi clipsync-backend:<提交号> clipsync-frontend:<提交号>`（正式版本还要删掉 `<版本号>` 标签，同一个镜像的标签全部删掉后才会释放空间）。
## 9. 使用 HTTPS

HTTP 下密码、登录令牌和所有内容都以明文传输，只适合测试或可信内网。正式使用、尤其是暴露在公网时，应启用 HTTPS。

证书由 `cert.sh` 调用 certbot 向 Let's Encrypt 免费申请，有效期 90 天，cron 每天检查，到期前 30 天内自动续期。

**前提**

- 有一个域名，并已把它的 A 记录解析到服务器的公网 IP（`ping <域名>` 显示的是服务器 IP）。服务器在中国大陆时，域名需要先完成 ICP 备案。
- 安全组放行 80 和 443。80 端口必须能从公网访问（申请和续期时 Let's Encrypt 要访问它），`.env` 的 `HTTP_PORT` 必须是 80。
- 已按第 6 节以 HTTP 启动，并且 `http://<域名>` 能打开页面。
- 服务器能拉取 `certbot/certbot` 镜像；不能访问 Docker Hub 时，用 `build-release.ps1 -WithCertbot` 把它打进镜像包。

**步骤**

```bash
# 1. 申请证书（证书保存在部署目录的 letsencrypt/）
bash cert.sh issue <域名> <邮箱>

# 2. 修改 .env：
#    取消 COMPOSE_FILE=docker-compose.yml:docker-compose.https.yml 这一行的注释
#    CORS_ORIGINS=https://<域名>
vi .env

# 3. 重建容器：frontend 映射 443 并改用 nginx-https.conf，backend 读取新的 CORS_ORIGINS
docker compose up -d --force-recreate backend frontend

# 4. 确认 https://<域名> 能正常登录、实时同步正常后，再开启 HSTS
#    HSTS_ENABLED=true，然后执行：
docker compose up -d backend
```

- 启用后 80 端口只保留证书验证，其余请求都 301 跳转到 HTTPS。
- `HSTS_ENABLED=true` 之后，浏览器在一年内只会用 HTTPS 访问这个域名。因此要确认 HTTPS 稳定后再开；开启后如果要退回 HTTP，用户的浏览器会一直打不开。
- 更换域名：用新域名再执行一次 `bash cert.sh issue`（证书名固定为 `clipsync`，会覆盖旧证书），修改 `CORS_ORIGINS`，再执行 `docker compose up -d --force-recreate backend frontend`。
- 退回 HTTP：先把 `HSTS_ENABLED` 改为 `false`，注释掉 `COMPOSE_FILE`，改回 `CORS_ORIGINS`，再 `docker compose up -d --force-recreate backend frontend`。
- 设置了 `COMPOSE_FILE` 时，命令里再写 `-f` 会使 `COMPOSE_FILE` 失效。方式 B 启用 HTTPS 后重新构建，要把三个文件都写上：`docker compose -f docker-compose.yml -f docker-compose.https.yml -f docker-compose.build.yml up -d --build`。

## 10. 备份与恢复

### 10.1 备份内容

`backup.sh` 每次生成两个文件，默认放在 `/var/backups/clipsync`：

| 文件 | 内容 | 默认保留 |
|------|------|------|
| `clipsync_db_<时间>.sql.gz` | 数据库（mysqldump，`--single-transaction` 不锁表） | 30 天 |
| `clipsync_files_<时间>.tar.gz` | 上传的文件（不含未完成的上传分片） | 7 天 |

- 两者要一起恢复：数据库里记录了文件，文件备份里是文件内容。
- 导出失败或内容不完整时，脚本会删除这次的备份、以非零退出码结束，不会留下看似正常的空备份。
- 备份目录和文件只允许 root 读写：数据库备份里有明文的剪贴板文本。
- 可以用环境变量 `BACKUP_DIR`、`DB_KEEP_DAYS`、`FILES_KEEP_DAYS` 调整目录和保留天数，例如 `DB_KEEP_DAYS=60 bash backup.sh`。改 cron 里的调用时同样适用。
- 备份默认和服务器在同一块硬盘上，硬盘损坏或服务器被删除时会一起丢失。请定期把备份复制到其他机器，例如在另一台电脑上执行 `scp root@<服务器IP>:/var/backups/clipsync/clipsync_*_<日期>_* .`。

手动备份：`bash backup.sh`。

### 10.2 检查备份

```bash
ls -lh /var/backups/clipsync/
gzip -dc /var/backups/clipsync/clipsync_db_<时间>.sql.gz | tail -n 1      # 应为 -- Dump completed on ...
tar -tzf /var/backups/clipsync/clipsync_files_<时间>.tar.gz | head        # 列出 ./<用户ID>/<文件UUID>
```

### 10.3 恢复

恢复会用备份**覆盖**当前的数据。先确认要恢复的是哪一份备份；不确定时，先 `bash backup.sh` 把当前状态也备份下来。

```bash
cd /opt/clipsync
docker compose stop frontend                 # 停止网站访问，避免恢复期间有人写入

# 数据库：备份里每张表都带 DROP TABLE，会整体替换
gzip -dc /var/backups/clipsync/clipsync_db_<时间>.sql.gz \
    | docker compose exec -T db sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" exec mysql -u "$MYSQL_USER" "$MYSQL_DATABASE"'

# 上传的文件：解压回数据卷（同名文件被覆盖；备份之后新上传的文件仍留在磁盘上占用空间，但数据库里没有记录，页面上不会显示）
docker compose exec -T backend sh -c 'tar -xzf - -C /app/storage' \
    < /var/backups/clipsync/clipsync_files_<时间>.tar.gz

docker compose restart backend               # 重新加载数据，并按需执行迁移
docker compose start frontend
bash health_check.sh
```

## 11. 迁移到新服务器

1. 旧服务器：`bash backup.sh`，把最新的两个备份文件和 `.env` 复制出来。
2. 新服务器：按第 3、4 节安装 Docker、导入镜像、解压部署包（使用与旧服务器相同或更新的版本）。
3. 把旧的 `.env` 放到部署目录（`chmod 600 .env`）。沿用相同的 `JWT_SECRET`，用户就不用重新登录。
4. `docker compose up -d`，等 `docker compose ps` 显示 db 为 healthy。
5. 按第 10.3 节恢复数据库和文件。
6. 按第 6.5 节安装定时任务。用了 HTTPS 的话，把域名解析改到新服务器 IP，再按第 9 节重新申请证书。
7. 确认新服务器一切正常后，再停用旧服务器。

## 12. 远程查询数据库（SSH 隧道）

数据库端口只绑定宿主机的 `127.0.0.1`，外网和局域网都不能直接连接。从自己的电脑查询时，先通过 SSH 登录服务器，再经这条加密通道连接数据库。

> 不要把 compose 里的端口改成 `"3306:3306"`：Docker 发布的端口会绕过防火墙，数据库会直接暴露在公网上。

### 12.1 创建只读账号（建议）

用 root 或应用账号查询，容易误改、误删数据。建议另建一个只能查询的账号：

```bash
docker compose exec db mysql -u root -p          # 输入 .env 里的 DB_ROOT_PASSWORD
```

```sql
-- clipsync 为库名（.env 的 DB_NAME）。用 '%' 是因为从隧道进来的连接，在容器看来来自 Docker 网关地址；
-- 端口只绑定在 127.0.0.1，外部仍然连不进来
CREATE USER 'reader'@'%' IDENTIFIED BY '<只读账号的密码>';
GRANT SELECT ON clipsync.* TO 'reader'@'%';
```

### 12.2 图形工具（以 DBeaver 为例）

新建连接，选 MySQL：

| 页签 | 项 | 填写 |
|------|----|------|
| SSH | 勾选 Use SSH Tunnel；Host / Port / User / 认证方式 | 服务器 IP / SSH 端口（默认 22）/ 服务器登录用户 / 密码或私钥 |
| Main | Server Host / Port | `127.0.0.1` / `3306`（改过 `DB_HOST_PORT` 就填那个值）。隧道的另一头在服务器上，对服务器来说数据库就在本机 |
| Main | Database / Username / Password | `clipsync` / `reader` / 只读账号的密码 |
| Driver properties | `allowPublicKeyRetrieval` | 只在连接时报 "Public Key Retrieval is not allowed" 时设为 `true`（数据已经在 SSH 隧道里加密） |

MySQL Workbench、HeidiSQL、Navicat 等工具也支持「通过 SSH 连接」，需要填写的信息相同。

### 12.3 命令行

```bash
# 在自己的电脑上：把本机 13306 端口经 SSH 转发到服务器的 127.0.0.1:3306，保持这个窗口不关
ssh -N -L 13306:127.0.0.1:3306 <用户>@<服务器IP>
# 另开一个窗口
mysql -h 127.0.0.1 -P 13306 -u reader -p clipsync
```

### 12.4 注意

- 服务器的 SSH 需要允许端口转发（`AllowTcpForwarding`，默认允许）。
- 数据库里的剪贴板文本是明文（登录密码只存 bcrypt 哈希）。直接查数据库会绕过应用里「admin 不能查看他人内容」的限制，这个入口只应留给运维者本人。
## 13. 升级 MySQL

MySQL 的版本号固定在 `docker-compose.yml` 的 `image:` 一行，随新版本的部署包更新。

- **同一系列内的小版本升级**（如 8.4.11 → 8.4.12）：按第 7 节正常更新即可，MySQL 启动时会自动升级数据目录。方式 A 打包时不要加 `-AppOnly`，镜像包里要带上新版本的 MySQL。
- **从 MySQL 8.0 升级到 8.4**（旧版本的部署使用 8.0）：MySQL 支持在原数据卷上直接升级，但无法降级回去，所以一定要先备份：
  ```bash
  bash backup.sh                       # 用旧版本备份，以防升级失败需要恢复
  docker compose stop                  # 让 MySQL 8.0 正常关闭
  # 导入带 MySQL 8.4 的镜像包、解压新的部署包后：
  docker compose up -d
  docker compose logs db | grep -i upgrade      # 应看到类似 Server upgrade from '80046' to '80411' completed
  bash health_check.sh
  ```
  升级失败时，删除数据卷后用 8.4 全新启动，再按第 10.3 节恢复备份（备份文件是 SQL，8.0 导出的备份可以导入 8.4）。
- 不要跨大版本跳着升级（如 8.0 直接到 9.x），也不要把版本号改回更旧的版本。

## 14. 常用命令

```bash
docker compose ps                         # 容器状态
docker compose logs -f backend            # 实时查看日志（Ctrl+C 退出），服务名：db / backend / frontend
docker compose logs --tail 100 frontend   # 最近 100 行
docker compose restart backend            # 重启单个服务
docker compose stop                       # 停止全部（数据保留）
docker compose up -d                      # 启动全部 / 让 .env 的修改生效
docker compose down                       # 删除容器和网络（数据卷保留，up -d 后恢复）
docker compose exec backend sh            # 进入 backend 容器
docker compose exec db sh -c 'mysql -u "$MYSQL_USER" -p "$MYSQL_DATABASE"'    # 用应用账号连接数据库
docker system df                          # Docker 占用的磁盘
docker image prune                        # 删除没有标签的旧镜像层（不影响带提交号标签的镜像）
```

### 危险操作

以下命令会**永久删除**数据，执行前先备份，并确认自己确实要这样做：

| 命令 | 后果 |
|------|------|
| `docker compose down -v` | 删除数据卷：数据库和所有上传的文件 |
| `docker volume rm clipsync_mysql_data` / `clipsync_storage_data` | 删除数据库 / 上传的文件 |
| `docker volume prune`、`docker system prune --volumes` | 删除所有未被容器使用的数据卷，容器停止时 ClipSync 的数据卷也在其中 |

## 15. 故障排查

先执行 `bash health_check.sh` 和 `docker compose ps`，再看对应服务的日志：`docker compose logs --tail 100 <服务名>`。

| 现象 | 原因与处理 |
|------|------|
| `docker compose up` 报 `required variable DB_PASSWORD is missing` 等 | `.env` 里的必填项为空，或者没有在部署目录执行命令 |
| `pull access denied for clipsync-backend`、`No such image` | 镜像没有导入，或 `CLIPSYNC_TAG` 指向不存在的标签。`docker images clipsync-backend` 查看已有的标签，重新 `docker load` |
| 部署了测试分支，页面却还是旧版本 | 非 master 的镜像没有 `latest` 标签，要把 `CLIPSYNC_TAG` 改成提交号 |
| 导入了正式版本的发布包，页面却还是旧版本，或提示找不到镜像 | 发布包里的镜像没有 `latest` 标签，要把 `.env` 的 `CLIPSYNC_TAG` 改成版本号 |
| backend 反复重启，日志提示 `JWT_SECRET 过弱` | `JWT_SECRET` 少于 32 位或含示例占位文字，用 `openssl rand -hex 32` 重新生成 |
| backend 日志 `Access denied for user` | `.env` 的数据库密码与数据库里实际的账号不一致，常见于数据卷已存在后又修改了密码（第 6.2 节） |
| db 一直不是 healthy | `docker compose logs db`。磁盘满、数据目录损坏、内存不足都会导致 MySQL 启动失败 |
| 容器启动即退出，日志 `exec format error` | 服务器不是 x86_64 |
| 页面能打开，但登录或操作时报错 | `docker compose logs backend` 查看具体错误 |
| 页面打不开 | 依次检查：`docker compose ps` 中 frontend 是否为 Up；本机 `curl -I http://127.0.0.1:<HTTP_PORT>/` 是否 200；云安全组是否放行了端口 |
| frontend 反复重启，日志 `cannot load certificate` | 设置了 `COMPOSE_FILE` 启用 HTTPS，但还没有申请证书。先注释掉 `COMPOSE_FILE` 回到 HTTP，申请成功后再启用 |
| `cert.sh issue` 失败 | 域名没有解析到本服务器、80 端口从公网访问不到，或者 frontend 没有运行。检查 `curl -I http://<域名>/` |
| 实时同步不工作，页面提示连接断开 | 检查 `nginx-common.conf` 是否为部署包里的版本；修改过 Nginx 配置后要 `docker compose up -d --force-recreate frontend` |
| 上传文件失败，提示 413 | 单个分片超过 Nginx 的 10MB 上限，检查 `CHUNK_SIZE` 是否被改大 |
| 开启了 SELinux 的系统上，frontend 日志里读取 Nginx 配置报 `Permission denied` | Docker 启用了 SELinux 支持（`/etc/docker/daemon.json` 里 `"selinux-enabled": true`）时，挂载的文件需要容器可读的标签：在部署目录执行 `chcon -Rt container_file_t .`，再 `docker compose up -d --force-recreate frontend` |
| 端口 80 或 3306 被占用 | 修改 `.env` 的 `HTTP_PORT`（同时修改 `CORS_ORIGINS`，加上端口号）或 `DB_HOST_PORT` |
| `backup.sh` 报 `service "db" is not running` | 容器没有运行，`docker compose up -d` 后重试 |
| `172.28.0.0/16` 与服务器已有网段冲突 | 同时修改 `docker-compose.yml` 的 `subnet` 和 backend `command` 里的 `--forwarded-allow-ips`。这两处会随部署包更新被覆盖，每次更新后都要重新修改 |
| `build-release.ps1` 报「无法连接 Docker」 | Docker Desktop 没有启动，或还在启动中 |
| `build-release.ps1` 在下载镜像或 `npm ci`、`pip install` 时失败 | 开发机访问 Docker Hub、npm、PyPI 不稳定，网络恢复后重试 |
| `build-release.ps1` 在 `docker save` 报 `content digest ... not found` | Docker Desktop 版本较旧且启用了 containerd 镜像存储。升级 Docker Desktop，或在 Settings → General 里取消 Use containerd for pulling and storing images |
