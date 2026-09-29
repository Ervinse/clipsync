# ClipSync

自托管的跨终端剪贴板与文件同步工具。粘贴文本即实时同步到你的其他终端，上传文件后其他终端即可下载。适合小范围、公网可达的部署场景。

## 功能概览

- **实时文本同步**：每个用户拥有一段「剪贴板」文本，在任一终端修改后通过 WebSocket 实时推送到该用户的其他终端。
- **文本历史版本**：保留最近 N 条历史，可查看、恢复、删除。
- **文件上传/下载**：分片上传（支持断点续传），带配额限制（默认 100MB/用户，可由管理员调整）。
- **快速访问码**：为自己的文本或文件生成一个访问码，在任意终端无需登录即可查看**自己的**内容（文本码始终指向你当前最新的剪贴板文本）。这是为了方便自己在多台设备间快速取用，不是对外分享。
- **三级角色**：
  - 普通用户：管理自己的文本与文件。
  - 管理员：可配置系统、管理用户与邀请码，但**无法查看文件内容**（隐私红线）。
  - 超级管理员：在管理员权限之上，可查看/下载任意文件内容。
- **多用户隔离**：用户之间互相看不到对方的文本与文件（超级管理员除外）。
- **邀请码注册**：一次性邀请码，可开关是否开放注册。
- **HTTP / HTTPS 双方案**：初期纯 HTTP 内网访问，后续可快速切换到 HTTPS。

## 技术栈

- **后端**：Python 3.12+ / FastAPI（异步）、SQLAlchemy 2.0 async + asyncmy、Alembic、JWT（python-jose）、passlib[bcrypt]、slowapi 限流。
- **数据库**：MySQL 8.0（utf8mb4）。
- **前端**：Vue 3 + Vite、Pinia、vue-router、axios、原生 WebSocket。
- **部署**：Gunicorn（UvicornWorker）+ Nginx 反向代理 + systemd。

## 目录结构

```
clipsync/
├── DESIGN.md              # 设计文档
├── README.md              # 本文件
├── .gitignore
├── backend/
│   ├── requirements.txt
│   ├── .env.example
│   ├── alembic.ini
│   ├── alembic/           # 数据库迁移
│   ├── scripts/
│   │   └── create_superadmin.py
│   └── app/
│       ├── main.py        # 应用入口
│       ├── config.py
│       ├── database.py
│       ├── rate_limit.py
│       ├── models/        # ORM 模型
│       ├── schemas/       # Pydantic 模型
│       ├── core/          # 安全/依赖/WS管理/存储/设置/清理
│       └── api/           # 路由：auth/clipboard/files/access/admin/ws
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── api/  ws/  router/  stores/  views/
└── deploy/
    ├── nginx.http.conf
    ├── nginx.https.conf
    └── clipsync.service
```

## 快速开始（开发环境）

### 先决条件

- Python 3.12+
- Node.js 18+
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
# 编辑 .env：填写 DB_* 连接信息，并把 JWT_SECRET 改成一段随机长字符串

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

Vite 开发服务器已把 `/api` 与 `/ws` 代理到 `127.0.0.1:8000`，浏览器打开 Vite 提示的地址（默认 http://localhost:5173）即可。

## 生产部署

ClipSync 支持三种部署方式：

### 方式一：自动化脚本部署（推荐）

使用提供的自动化部署脚本，适合大多数 Linux 环境。

```bash
# 上传项目到服务器
cd /var/www
sudo git clone https://github.com/your-repo/clipsync.git
cd clipsync

# 配置环境变量
cd backend
sudo cp ../deployment/.env.production.example .env
sudo nano .env  # 编辑配置

# 执行部署脚本
cd ..
sudo bash deployment/scripts/deploy.sh
```

部署脚本会自动完成：
1. 检查系统依赖
2. 配置数据库
3. 安装 Python 和 Node.js 依赖
4. 执行数据库迁移
5. 创建超级管理员
6. 构建前端
7. 配置 Nginx 和 Systemd
8. 设置定时任务（数据库备份、过期数据清理）

完成后：
```bash
sudo systemctl start clipsync
sudo systemctl enable clipsync
sudo systemctl restart nginx
```

**详细文档**：[deployment/DEPLOY.md](deployment/DEPLOY.md)

### 方式二：Docker Compose 部署

适合容器化环境，快速启动。

```bash
cd deployment/docker
cp .env.example .env
nano .env  # 编辑配置

# 启动所有服务
docker-compose up -d

# 创建超级管理员
docker-compose exec backend python -m scripts.create_superadmin
```

访问 http://localhost

**详细文档**：[deployment/docker/README.md](deployment/docker/README.md)

### 方式三：手动部署

完整的手动部署步骤见 [deployment/DEPLOY.md](deployment/DEPLOY.md)。

## HTTP / HTTPS 切换

ClipSync 支持灵活的协议切换：

**HTTP（开发/内网）**：
- 在 `backend/.env` 设置：
  ```
  DEPLOY_SCHEME=http
  COOKIE_SECURE=false
  HSTS_ENABLED=false
  CORS_ORIGINS=http://your-ip
  ```

**HTTPS（生产）**：
1. 获取 SSL 证书（Let's Encrypt 或购买）
2. 配置 Nginx SSL（见 `deployment/nginx/clipsync.conf`）
3. 在 `backend/.env` 设置：
  ```
  DEPLOY_SCHEME=https
  COOKIE_SECURE=true
  HSTS_ENABLED=true
  CORS_ORIGINS=https://your-domain.com
  ```
4. 重启服务：`sudo systemctl restart clipsync nginx`

前端使用相对路径和协议自适应，切换协议无需重新构建。

> ⚠️ **HTTP 阶段安全提示**：纯 HTTP 下所有数据明文传输，**仅用于可信内网**。生产环境务必使用 HTTPS。

## 关键配置项（backend/.env）

| 变量 | 说明 | 默认 |
|------|------|------|
| `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` | MySQL 连接 | — |
| `JWT_SECRET` | JWT 签名密钥，**务必改为随机长串** | — |
| `JWT_EXPIRE_MINUTES` | 令牌有效期 | 10080（7天） |
| `DEPLOY_SCHEME` | `http` / `https` | http |
| `COOKIE_SECURE` / `HSTS_ENABLED` | 随协议切换 | false |
| `CORS_ORIGINS` | 允许的前端来源，逗号分隔 | — |
| `STORAGE_DIR` | 文件存储根目录 | ./storage |
| `DEFAULT_QUOTA_BYTES` | 单用户默认配额 | 104857600（100MB） |
| `MAX_FILE_BYTES` | 单文件上限 | 524288000（500MB） |
| `CHUNK_SIZE` | 分片大小 | 5242880（5MB） |
| `HISTORY_KEEP` | 保留文本历史条数 | 50 |
| `UPLOAD_SESSION_TTL_HOURS` | 未完成上传会话过期清理时间 | 24 |

部分项（开放注册、默认配额、单文件上限、分片大小、历史条数、邀请码有效期）也可在后台管理面板中动态修改，数据库设置优先于 `.env` 默认值。

## 权限与隐私模型

- 文件内容下载仅限**文件所有者本人**与**超级管理员**。
- 管理员的文件管理页只显示元数据（文件名、大小、所有者、时间），**没有下载入口**。
- 快速访问码解析出的内容只属于访问码的所有者本人；文本码读取所有者的实时剪贴板，不做快照，也不记录访问次数或访问日志。

## 说明

本项目为小范围自托管设计，实时同步依赖单进程内存。若要支持更大规模或多实例部署，需要引入跨进程消息机制（如 Redis pub/sub）并相应改造 WebSocket 广播层。
