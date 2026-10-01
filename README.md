# ClipSync

自托管的跨终端剪贴板与文件同步工具。粘贴文本即实时同步到你的其他终端，上传文件后其他终端即可下载。适合小范围、自托管的部署场景。

> 设计细节（数据模型、接口清单、权限表、目录结构）以 [DESIGN.md](DESIGN.md) 为准；部署步骤以 [deployment/DEPLOY.md](deployment/DEPLOY.md) 为准。

## 功能概览

- **实时文本同步**：每个用户拥有一段「剪贴板」文本，在任一终端保存后通过 WebSocket 通知该用户的其他终端重新拉取。
- **文本历史版本**：保留最近 N 条历史（`HISTORY_KEEP`，默认 50），前端可查看并把某条历史载入编辑框。后端另有「恢复」「删除」历史的接口，**前端暂未提供入口**。
- **文件上传/下载**：分片上传（支持单片重传），带配额限制（默认 100MB/用户，超级管理员可调整）。其他终端需刷新文件列表才能看到新文件（后端会广播事件，**前端暂未订阅**）。
- **快速访问码**：为自己的文本或文件生成一个 12 位访问码，在任意终端无需登录即可查看**自己的**内容（文本码始终指向你当前最新的剪贴板文本）。用途是方便自己跨设备取用，不是对外分享。
- **三级角色**：
  - 普通用户：管理自己的文本、文件与访问码。
  - 管理员：查看统计与用户列表、管理邀请码、查看全站文件**元数据**、读取系统设置；**无法查看他人文件或文本内容**。
  - 超级管理员：在管理员之上，可修改用户配额、启用/禁用/删除用户、修改系统设置，并可下载任意文件。
- **多用户隔离**：用户之间互相看不到对方的文本与文件（超级管理员仅能额外下载文件）。
- **邀请码注册**：一次性邀请码，可设过期时间；系统设置可关闭注册（关闭后持有邀请码也无法注册）。
- **HTTP / HTTPS 双方案**：初期纯 HTTP 内网访问，后续切换 Nginx 配置即可启用 HTTPS。

## 技术栈

- **后端**：Python 3.12+ / FastAPI（异步）、SQLAlchemy 2.0 async + aiomysql、Alembic、JWT（python-jose）、bcrypt、slowapi 限流。
- **数据库**：MySQL 8.0（utf8mb4）。
- **前端**：Vue 3 + Vite 8、Pinia、vue-router、axios、原生 WebSocket。
- **部署**：Uvicorn（**单 worker**）+ Nginx 反向代理 + systemd；另提供 Docker Compose。

## 目录结构

```
clipsync/
├── DESIGN.md / README.md / CLAUDE.md
├── backend/
│   ├── requirements.txt / .env.example / alembic.ini / pytest.ini
│   ├── alembic/           # 数据库迁移
│   ├── scripts/create_superadmin.py
│   ├── tests/             # pytest 安全与接口测试
│   ├── storage/           # 运行时生成：上传文件落盘（已被 .gitignore 排除）
│   └── app/
│       ├── main.py / config.py / database.py / rate_limit.py
│       ├── models/        # ORM 模型
│       ├── schemas/       # Pydantic 模型
│       ├── core/          # 安全/依赖/WS 管理/存储/系统设置/时间/HTTP 工具
│       └── api/           # 路由：auth/clipboard/files/access/admin/ws
├── frontend/
│   ├── package.json / vite.config.js
│   └── src/  api/  stores/  router/  views/  utils/
└── deployment/
    ├── nginx/             # clipsync.conf（HTTP）、clipsync-https.conf（HTTPS）
    ├── systemd/clipsync.service
    ├── scripts/           # deploy / update / backup / cleanup / health_check
    └── docker/            # Dockerfile 与 docker-compose.yml
```

## 快速开始（开发环境）

### 先决条件

- Python 3.12+
- Node.js 20.19+ 或 22.12+（Vite 8 的要求）
- MySQL 8.0（已运行，且能创建数据库）

### 1. 创建数据库

```sql
CREATE DATABASE clipsync CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 2. 后端

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# 编辑 .env：填写 DB_* 连接信息；JWT_SECRET 用 `openssl rand -hex 32` 生成（至少 32 位）
# JWT_SECRET 为空、过短或仍是示例值时，后端会拒绝启动

# 建表
alembic upgrade head

# 创建第一个超级管理员（交互式）
python -m scripts.create_superadmin

# 启动开发服务器
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 3. 前端

```bash
cd frontend
npm install
npm run dev
```

Vite 开发服务器运行在 http://localhost:3000，并把 `/api` 与 `/ws` 代理到 `127.0.0.1:8000`。

### 4. 运行测试

```bash
cd backend
pytest
```

测试会连接 `.env` 中配置的 MySQL，每次运行 **DROP 并重建** 独立的 `clipsync_test` 库（开发库不受影响），因此该账号需要有创建/删除数据库的权限。

## 生产部署

三种方式，完整步骤见 [deployment/DEPLOY.md](deployment/DEPLOY.md)：

- **自动化脚本**：`sudo bash deployment/scripts/deploy.sh`。脚本**不会建库建用户**，需先手动创建数据库并写好 `backend/.env`。
- **Docker Compose**：见 [deployment/docker/README.md](deployment/docker/README.md)。
- **手动部署**：见 DEPLOY.md。

> **重要**：后端必须**单 worker** 运行。WebSocket 连接表与限流计数都在进程内存中，多 worker 会让实时同步与限流失效。

## HTTP / HTTPS 切换

- **HTTP（内网）**：Nginx 使用 `deployment/nginx/clipsync.conf`，`.env` 中 `HSTS_ENABLED=false`。
- **HTTPS**：证书就位后改用 `deployment/nginx/clipsync-https.conf`（含 80→443 跳转），`.env` 中 `HSTS_ENABLED=true`、`CORS_ORIGINS` 改为 https 域名，然后重启后端与 Nginx。

HSTS 响应头由后端按 `HSTS_ENABLED` 下发。前端使用相对路径和协议自适应，访问码链接按请求协议动态生成，切换协议无需重新构建。

> `DEPLOY_SCHEME`、`COOKIE_SECURE` 目前代码中没有读取（Token 走 `Authorization` 头，不使用 cookie），保留仅为配置占位。

> ⚠️ **HTTP 阶段安全提示**：纯 HTTP 下密码、令牌和所有内容都明文传输，**仅用于可信内网**。

## 关键配置项（backend/.env）

| 变量 | 说明 | 代码默认值 |
|------|------|------|
| `DB_HOST` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` | MySQL 连接 | 必填 |
| `DB_PORT` | MySQL 端口 | 3306 |
| `JWT_SECRET` | JWT 签名密钥，至少 32 位且非示例值 | 必填 |
| `JWT_ALGORITHM` | 仅允许 HS256 / HS384 / HS512 | HS256 |
| `JWT_EXPIRE_MINUTES` | 令牌有效期 | 10080（7 天） |
| `HSTS_ENABLED` | 是否下发 HSTS（仅 HTTPS 下开启） | false |
| `CORS_ORIGINS` | 允许的前端来源，逗号分隔，忽略 `*` | http://localhost:5173（`.env.example` 已按开发端口写为 3000） |
| `DEPLOY_SCHEME` / `COOKIE_SECURE` | 占位，代码未使用 | http / false |
| `STORAGE_DIR` | 文件存储根目录（相对 `backend/`） | ./storage |
| `DEFAULT_QUOTA_BYTES` | 新用户默认配额 | 104857600（100MB） |
| `MAX_FILE_BYTES` | 单文件上限 | 524288000（500MB） |
| `CHUNK_SIZE` | 单分片上限（客户端请求值会被裁剪到此值） | 5242880（5MB） |
| `MAX_UPLOAD_SESSIONS_PER_USER` | 单用户同时进行的上传会话上限 | 5 |
| `HISTORY_KEEP` | 每用户保留的文本历史条数 | 50 |
| `UPLOAD_SESSION_TTL_HOURS` | 未完成上传会话的过期时间 | 24 |

数据库中的系统设置目前只有两项：**是否开放注册**、**新用户默认配额**，优先于 `.env`。它们可通过 `GET/PATCH /api/admin/settings` 读写（修改仅限超级管理员），**管理后台暂无设置页面**。其余各项只能通过 `.env` 修改并重启后端。

## 权限与隐私模型

- 文件内容下载仅限**文件所有者本人**与**超级管理员**；他人文件一律返回 404。
- 管理员的文件页只显示元数据（文件名、大小、所有者、时间），**没有下载入口**。
- 没有任何接口允许查看他人的文本内容（包括超级管理员）。
- 快速访问码只解析属主本人的内容；属主被禁用、码被撤销或过期、文件被删除后立即失效。文本码读取实时剪贴板，不做快照，也不记录访问次数或日志。

## 说明

本项目为小范围自托管设计，实时同步依赖单进程内存。若要支持多实例部署，需要引入跨进程消息机制（如 Redis pub/sub）并改造 WebSocket 广播层与限流存储。
