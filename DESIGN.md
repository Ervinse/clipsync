# ClipSync 跨终端剪贴板与文件同步 — 设计文档

> 版本：v0.3（起草阶段）
> 一个自托管的、多用户隔离的跨终端文本/文件实时同步工具，支持文本历史、快速访问码与三级权限。

---

## 1. 项目概述

ClipSync 是一个 B/S 架构的 Web 应用。用户在任意设备的浏览器中登录后：

- **文本同步**：粘贴的文本实时推送到该用户的其他在线终端，无需手动刷新。每个用户只有一段「当前文本」（相当于一个云剪切板），同时保留历史版本可回看。
- **文件同步**：上传的文件实时保存到服务器，其他终端即时可见并下载。
- **快速访问码**：为「自己的最新文本」或「某个文件」生成一个访问码，在**任意终端免登录**输入该码即可快速查看/下载。用途是方便自己跨设备取用，不是分发给他人。
- **多用户隔离**：普通用户只能看到自己的文本和文件。
- **三级权限**：普通用户 / 管理员 / 超级管理员，配套管理后台面板。
- **公网/内网两套部署**：初期纯 HTTP 内网访问，后续一键切换 HTTPS。

### 核心使用场景

在公司电脑复制一段文本/一个文件 → 打开网页粘贴/上传 → 回家用另一台电脑登录即可看到；或者不想登录，事先为文本/文件生成一个快速访问码，在任意浏览器输入码就能立刻看到自己的最新文本或下载文件。

### 范围边界（已确认不做）

- **文件在线预览**：不做，文件仅支持下载。
- **设备列表 / 在线状态**：不做，不展示用户的终端连接情况。

---

## 2. 技术栈

| 层 | 选型 | 说明 |
|----|------|------|
| 后端框架 | Python 3.12+ / FastAPI | 异步、原生支持 WebSocket、自动生成 API 文档 |
| ASGI 服务器 | Uvicorn (+ Gunicorn 多进程) | 生产环境用 Gunicorn 管理 Uvicorn worker |
| 数据库 | MySQL 8.0 | 存用户与元数据 |
| ORM / 驱动 | SQLAlchemy 2.0 (async) + asyncmy | 异步访问 MySQL |
| 迁移工具 | Alembic | 管理表结构版本 |
| 认证 | JWT (python-jose) + passlib[bcrypt] | 无状态令牌 + 密码哈希 |
| 限流 | slowapi | 登录、快速访问等接口限流 |
| 测试 | pytest + pytest-asyncio | 后端单测/异步用例，`pytest 路径::用例名` 跑单个 |
| 前端框架 | Vue 3 + Vite | 组合式 API |
| 状态管理 | Pinia | auth / clipboard / files / admin 多个 store |
| HTTP 客户端 | axios | 统一封装、自动带 token |
| 实时通道 | 原生 WebSocket | 按 user_id 广播 |
| 文件存储 | 服务器本地磁盘 | 按 user_id 分目录 |
| 部署 | systemd + Nginx 反向代理 | HTTP / HTTPS 两套配置，直接部署 |

---

## 3. 系统架构

```
                     内网 / 公网
                          │
                    ┌─────▼─────┐
                    │   Nginx    │  HTTP 或 HTTPS（两套配置切换）
                    │ (80 / 443) │  静态资源 / 反向代理 / WS upgrade
                    └─────┬─────┘
              ┌───────────┼───────────┐
              │           │           │
      静态前端(Vue     REST API     WebSocket
      构建产物)      /api/*        /ws
              │           │           │
              │     ┌─────▼───────────▼─────┐
              └────▶│   FastAPI (Uvicorn)    │
                    │  认证/鉴权 · 角色中间件 │
                    │  路由层 · WS 连接管理器 │
                    └───┬──────────────┬─────┘
                        │              │
                  ┌─────▼────┐   ┌─────▼──────┐
                  │  MySQL   │   │ 本地磁盘    │
                  │ 用户/元数据│   │ storage/   │
                  │ 访问码/邀请│   └────────────┘
                  └──────────┘
```

**四类入口**：
- 浏览器访问 `/` → Nginx 返回 Vue 构建产物。
- 登录用户调用 `/api/*` → 反代到 FastAPI（带 JWT）。
- 实时通道 `/ws` → WebSocket upgrade → 连接管理器。
- 快速访问 `/c/<code>`（前端页面）→ 调 `/api/access/<code>`（**免登录**）。

---

## 4. 权限模型（三级角色）

用 `role` 枚举字段（`user` / `admin` / `superadmin`）区分，取代布尔标记。

| 能力 | 普通用户 user | 管理员 admin | 超级管理员 superadmin |
|------|:---:|:---:|:---:|
| 管理自己的文本/文件/访问码 | ✓ | ✓ | ✓ |
| 进入管理后台面板 | ✗ | ✓ | ✓ |
| 查看用户列表、系统统计 | ✗ | ✓ | ✓ |
| 创建/禁用用户、生成邀请码 | ✗ | ✓ | ✓ |
| 修改用户存储配额 | ✗ | ✓ | ✓ |
| 查看全站文件/文本的**元数据** | ✗ | ✓ | ✓ |
| 查看/下载他人文件**内容** | ✗ | **✗** | ✓ |
| 查看他人文本**内容** | ✗ | **✗** | ✓ |
| 设置其他用户为管理员 | ✗ | ✗ | ✓ |
| 修改全局系统设置 | ✗ | ✓ | ✓ |

> 关键区别：**管理员能管理系统但看不到用户隐私内容**（只能看文件名、大小、时间等元数据用于管理）；**超级管理员才能查看内容**。这一约束在后端接口层强制：内容读取接口对 admin 与对普通用户一视同仁地做归属校验，仅 superadmin 可绕过。

---

## 5. 数据模型

设计原则：**每条隐私数据都归属某个 `user_id`，查询时强制按当前登录用户过滤**。仅 superadmin 可绕过内容过滤。

### 5.1 users — 用户

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT PK | 自增主键 |
| username | VARCHAR(64) UNIQUE | 登录名 |
| password_hash | VARCHAR(255) | bcrypt 哈希，不存明文 |
| role | ENUM('user','admin','superadmin') | 角色，默认 user |
| quota_bytes | BIGINT | 存储配额，默认 100MB（可被管理员改） |
| is_active | BOOLEAN | 是否启用（可被管理员禁用） |
| created_at | DATETIME | 创建时间 |

### 5.2 invite_codes — 邀请码

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT PK | |
| code | VARCHAR(32) UNIQUE | 邀请码字符串 |
| created_by | BIGINT FK→users | 谁创建的（管理员/超管） |
| used_by | BIGINT FK→users NULL | 被谁使用，未用为 NULL |
| expires_at | DATETIME NULL | 过期时间，NULL 不过期 |
| used_at | DATETIME NULL | 使用时间 |
| created_at | DATETIME | |

> 一次性：注册成功即置 `used_by`/`used_at`，之后不可复用。

### 5.3 clipboard — 当前文本（每用户一条）

| 字段 | 类型 | 说明 |
|------|------|------|
| user_id | BIGINT PK / FK→users | 主键即 user_id，保证一人一条「当前文本」 |
| content | MEDIUMTEXT | 当前文本内容 |
| updated_at | DATETIME | 最后更新时间 |

> 该表为用户的「云剪切板」，每用户仅一条当前内容，写入采用 upsert。

### 5.4 clipboard_history — 文本历史版本

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT PK | |
| user_id | BIGINT FK→users | 归属用户，查询按此过滤 |
| content | MEDIUMTEXT | 该版本文本内容 |
| created_at | DATETIME | 该版本产生时间 |

> 用户更新「当前文本」时，旧内容写入本表作为历史版本，供界面查看与恢复。
> **保留策略**：默认保留每用户最近 50 条（系统设置可调），超出部分按时间自动清理最旧记录，防止无限增长。

### 5.5 files — 文件元数据

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT PK | |
| user_id | BIGINT FK→users | 归属用户，查询按此过滤 |
| original_name | VARCHAR(255) | 原始文件名 |
| stored_name | VARCHAR(255) | 磁盘存储名（UUID，防冲突/穿越） |
| size | BIGINT | 字节数 |
| mime_type | VARCHAR(128) | MIME 类型 |
| created_at | DATETIME | 上传完成时间 |

### 5.6 upload_sessions — 分片上传临时状态

| 字段 | 类型 | 说明 |
|------|------|------|
| upload_id | VARCHAR(36) PK | 客户端初始化拿到的 UUID |
| user_id | BIGINT FK→users | 归属用户 |
| original_name | VARCHAR(255) | 原始文件名 |
| total_size | BIGINT | 文件总大小 |
| total_chunks | INT | 分片总数 |
| received_chunks | INT | 已收到的分片数 |
| chunk_size | INT | 每片大小 |
| created_at | DATETIME | 用于清理超时未完成的会话 |

### 5.7 access_codes — 快速访问码

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT PK | |
| code | VARCHAR(32) UNIQUE | 访问码字符串（随机，索引） |
| owner_id | BIGINT FK→users | 归属用户 |
| target_type | ENUM('text','file') | 指向当前文本或某个文件 |
| file_id | BIGINT FK→files NULL | 文件码：引用的文件 id；文本码为 NULL |
| expires_at | DATETIME NULL | 过期时间，NULL 不过期 |
| is_revoked | BOOLEAN | 是否已撤销 |
| created_at | DATETIME | |

> **文本访问码指向「当前最新文本」，不存快照**：每个用户只有一段文本（云剪切板），访问码用于属主在其他设备免登录读取该剪切板的**实时最新内容**；属主更新文本后，访问码解析到的内容随之更新。
> **文件访问码存引用**：记录具体 file_id，源文件删除时级联撤销对应访问码。
> **不含访问计数、次数上限、访问日志**：访问码定位为属主跨设备免登录取用的入口，非对外分发功能。

---

## 6. API 设计

除注册、登录、快速访问外，`/api/*` 都需 `Authorization: Bearer <token>`。

### 6.1 认证 `api/auth.py`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | /api/auth/register | 公开 | 用户名+密码+邀请码，校验后创建用户 |
| POST | /api/auth/login | 公开 | 返回 JWT |
| GET | /api/auth/me | 登录 | 当前用户信息（含 role、配额、已用空间） |

### 6.2 文本 `api/clipboard.py`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | /api/clipboard | 登录 | 获取自己的当前文本 |
| PUT | /api/clipboard | 登录 | 更新当前文本（upsert），旧内容入历史，广播 |
| GET | /api/clipboard/history | 登录 | 列出自己的文本历史版本 |
| POST | /api/clipboard/history/{id}/restore | 登录 | 把某历史版本恢复为当前文本，广播 |
| DELETE | /api/clipboard/history/{id} | 归属 | 删除某条历史版本 |

### 6.3 文件 `api/files.py`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | /api/files | 登录 | 列出自己的文件 |
| POST | /api/files/upload/init | 登录 | 初始化分片上传（先校验配额），返回 upload_id |
| POST | /api/files/upload/chunk | 登录 | 上传单个分片 |
| POST | /api/files/upload/complete | 登录 | 合并分片，写记录，广播 |
| GET | /api/files/{id}/download | 归属或 superadmin | 下载（校验归属+防穿越） |
| DELETE | /api/files/{id} | 归属 | 删文件+磁盘+级联撤销访问码，广播 |

### 6.4 快速访问码 `api/access.py`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | /api/access-codes | 登录 | 为「当前文本」或「某个文件」生成访问码 |
| GET | /api/access-codes | 登录 | 列出自己创建的访问码 |
| DELETE | /api/access-codes/{id} | 归属 | 撤销访问码 |
| GET | /api/access/{code} | **公开** | 免登录：文本码返回属主**当前最新文本**；文件码返回文件元信息+下载地址 |
| GET | /api/access/{code}/download | **公开** | 免登录：文件码的内容流式下载 |

> 访问接口在 `/api/access/*`（免登录取用），与需要登录的 `/api/access-codes`（管理自己的码）区分。

### 6.5 管理后台 `api/admin.py`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | /api/admin/stats | admin+ | 系统统计（用户数、文件数、存储占用等） |
| GET | /api/admin/users | admin+ | 用户列表（含配额、已用空间） |
| POST | /api/admin/users | admin+ | 直接创建用户（免邀请码） |
| PATCH | /api/admin/users/{id} | admin+ | 启用/禁用、重置密码、**改配额** |
| PATCH | /api/admin/users/{id}/role | **superadmin** | 变更角色（仅超管可授予管理员） |
| GET | /api/admin/invites | admin+ | 邀请码列表与状态 |
| POST | /api/admin/invites | admin+ | 生成邀请码 |
| GET | /api/admin/files | admin+ | 全站文件**元数据**（无下载入口给 admin） |
| GET | /api/admin/settings | admin+ | 读取全局系统设置 |
| PUT | /api/admin/settings | admin+ | 修改全局系统设置 |

> **隐私红线**：`/api/admin/files` 只返回元数据（属主、文件名、大小、时间），**不提供 admin 下载入口**；文件内容下载统一走 `/api/files/{id}/download`，该接口仅放行归属者与 superadmin。

---

## 7. 实时同步机制

### 连接管理器（core/ws_manager.py）

维护 `dict[user_id, set[WebSocket]]`，同一用户多终端在线时集合里有多条连接。

- **连接**：`/ws?token=<JWT>` 校验 token → 拿 user_id → 加入集合。
- **断开**：从集合移除，空则删 key。
- **广播**：`broadcast_to_user(user_id, message, exclude=触发连接)`，跳过触发本次变更的连接，避免自己收到自己的更新。

### 事件类型

前端按 `type` 决定刷新哪块，消息只携带轻量信号：

```json
{ "type": "clipboard_updated", "data": { "updated_at": "..." } }
{ "type": "file_added",   "data": { "id": 1, "original_name": "..." } }
{ "type": "file_deleted", "data": { "id": 1 } }
```

### WebSocket 协议自适应（HTTP/HTTPS 通用）

前端不写死协议，根据当前页面协议自动选择，两套部署都无需改代码：

```js
const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
const ws = new WebSocket(`${proto}//${location.host}/ws?token=${token}`)
```

---

## 8. 快速访问码机制

> 定位：**供属主本人跨设备免登录取用自己内容的入口**，非对外分发功能。因此不设访问次数、访问日志等分发控制。

### 生成

登录用户调用 `POST /api/access-codes`：

- **文本码** → 只记录 `target_type='text'` 与 `owner_id`，**不存快照**。访问时实时读取属主的当前文本。
- **文件码** → 记录 `target_type='file'` 与 `file_id`。
- 可选 `expires_at`（过期时间）。
- 返回 `code` 与可直接使用的 URL：`http(s)://<host>/c/<code>`。

### 访问（免登录）

在任意终端打开 `/c/<code>`（前端访问页）或直接调 API：

```
GET /api/access/<code>
  ├─ 校验：存在 / 未撤销 / 未过期
  ├─ 文本码 → 实时查属主 clipboard，返回当前最新文本
  └─ 文件码 → 返回文件元信息 + 下载地址
GET /api/access/<code>/download   # 文件内容流式下载
```

- 撤销、（文件码）源文件删除、过期都会使访问码失效。

### 安全考量

- `code` 用足够长的随机串（避免遍历猜测），并对 `/api/access/*` 做限流。
- 免登录接口同样防路径穿越（文件按 file_id 查库拿 stored_name）。
- 访问码遵循「知道码即可查看」模型，界面须提示：访问码等同于对应内容的免登录凭证，应妥善保管；敏感内容可设置过期时间或及时撤销。

---

## 9. 管理后台面板

面向 admin / superadmin 的独立前端区域（`/admin` 路由，登录守卫校验 role）。

### 页面结构

```
/admin
├── 概览 Dashboard      # 用户数、文件数、存储总占用、活跃访问码数
├── 用户管理 Users      # 列表 / 新建 / 禁用 / 重置密码 / 改配额 / 改角色(仅超管)
├── 邀请码 Invites      # 生成 / 列表 / 状态（已用/未用/过期）
├── 文件总览 Files      # 全站文件【元数据】列表，可按用户筛选
│                        # admin：只读元数据，无下载
│                        # superadmin：额外提供内容查看/下载入口
├── 访问码管理 Codes    # 全站访问码列表【元数据】、可强制撤销
└── 系统设置 Settings   # 全局配置（见下）
```

### 全局系统设置（存 DB，可热更新）

- 是否开放邀请码注册
- 单文件大小上限
- **默认用户存储配额（默认 100MB）**
- 文本历史保留条数（默认 50）
- 分片大小默认值
- 邀请码默认有效期

### 前端角色控制

- 路由守卫：非 admin/superadmin 访问 `/admin` 直接重定向。
- 组件级：文件内容查看/下载按钮仅当 `role === 'superadmin'` 时渲染。
- **后端才是权限的最终防线**，前端隐藏只是体验层，所有接口都做服务端角色校验。

---

## 10. 文件分片上传方案

单文件可达上百 MB，必须分片。

```
1. init     → POST /upload/init {name,size,total_chunks,chunk_size}
              先校验配额（已用+本次 ≤ quota）→ 建 upload_session，返回 upload_id
2. chunk×N  → POST /upload/chunk {upload_id, index, <binary>}
              落盘 tmp/{upload_id}/{index}，received_chunks++
              可并发；失败仅重传该片（断点续传）
3. complete → POST /upload/complete {upload_id}
              校验 received==total → 按序流式合并到 storage/{user_id}/{uuid}
              写 files 记录 → 删 tmp → 广播 file_added
```

- 分片大小默认 5MB（系统设置可调）。
- 合并流式追加，避免一次性读入内存。
- 定时任务清理超时未完成的 upload_session 与 tmp 目录。
- **配额**：init 阶段预校验，complete 阶段按实际大小最终确认，避免超配额写入。

---

## 11. HTTP / HTTPS 双方案（快速切换）

初期纯 HTTP 内网访问，后续平滑切到 HTTPS。设计目标：**切换只动 Nginx 配置与一个环境开关，应用代码零改动**。

### 保障平滑切换的三项设计

1. **前端不写死协议**
   - API 走相对路径（`/api/...`），跟随页面协议。
   - WebSocket 按 `window.location.protocol` 自动选 `ws://`/`wss://`（见第 7 节）。
   - 访问码链接由后端按请求的 `scheme` + `host` 动态拼接，不硬编码。

2. **两份 Nginx 配置文件**，切换即换软链/重载：
   - `deploy/nginx.http.conf` —— 监听 80，直接反代，无证书。
   - `deploy/nginx.https.conf` —— 监听 443 + TLS 证书，80 端口 301 跳转 443。
   ```bash
   # 内网 HTTP 阶段
   ln -sf nginx.http.conf  /etc/nginx/conf.d/clipsync.conf && nginx -s reload
   # 升级到 HTTPS（证书就位后）
   ln -sf nginx.https.conf /etc/nginx/conf.d/clipsync.conf && nginx -s reload
   ```

3. **一个环境开关控制安全相关行为**（`.env`）：

   | 变量 | HTTP 阶段 | HTTPS 阶段 | 作用 |
   |------|:---:|:---:|------|
   | `DEPLOY_SCHEME` | http | https | 拼访问码链接、cookie 策略判断 |
   | `COOKIE_SECURE` | false | true | 若用 cookie，HTTPS 才加 Secure |
   | `HSTS_ENABLED` | false | true | 仅 HTTPS 下由 Nginx 启用 HSTS |
   | `CORS_ORIGINS` | 内网 IP | 域名 | 允许来源 |

### 阶段说明与提示

- **HTTP 阶段的风险**：密码、JWT、文本、文件在内网明文传输，可被同网段嗅探。仅限**可信内网**使用，切勿在此阶段暴露公网；README 中须显著标注。
- Token 采用 `Authorization` header + 前端 localStorage，HTTP/HTTPS 行为一致，不依赖 cookie，切换协议无需改动应用代码。
- 升级 HTTPS 时：申请证书（Let's Encrypt）→ 换 Nginx 软链 → 改 `.env` 开关 → 重载。无需改动数据库或应用逻辑。

---

## 12. 安全设计

| 项 | 措施 |
|----|------|
| 传输加密 | 两套方案：HTTP（内网临时）/ HTTPS（正式）。README 明确 HTTP 阶段仅限可信内网。 |
| 密码存储 | bcrypt 哈希，绝不存明文，不在日志/响应回显。 |
| 认证 | JWT，合理过期时间。 |
| 角色权限 | 三级角色后端强制校验；admin 看不到文件/文本内容，仅 superadmin 可绕过。 |
| 登录爆破 | 登录、快速访问接口限流。 |
| 数据隔离 | 隐私查询强制 `WHERE user_id = current_user`，仅 superadmin 例外。 |
| 越权访问 | 下载/删除先校验归属；访问码按 code 查库，不信任客户端传入路径。 |
| 路径穿越 | 磁盘名用 UUID，绝不用用户文件名拼路径。 |
| 访问码 | code 足够随机 + 限流 + 可设过期 + 可撤销；前端提示用户妥善保管。 |
| 上传限制 | Nginx `client_max_body_size`；后端校验单文件上限与配额。 |
| 邀请码 | 一次性、可过期、仅管理员生成。 |
| CORS | 按 `.env` 的 `CORS_ORIGINS` 限定，不用通配。 |

---

## 13. 目录结构

```
CodeProject/
└── clipsync/                     # ← 本项目根目录
    ├── DESIGN.md                 # 本文档
    ├── README.md                 # 快速开始（含 HTTP/HTTPS 切换说明）
    ├── backend/
    │   ├── app/
    │   │   ├── main.py           # FastAPI 入口，挂载路由/中间件
    │   │   ├── config.py         # 读取 .env（含 DEPLOY_SCHEME 等开关）
    │   │   ├── database.py       # 异步 engine / session 工厂
    │   │   ├── models/           # SQLAlchemy 表模型
    │   │   │   ├── user.py
    │   │   │   ├── invite.py
    │   │   │   ├── clipboard.py  # 当前文本 + 历史
    │   │   │   ├── file.py
    │   │   │   ├── access_code.py
    │   │   │   └── setting.py
    │   │   ├── schemas/          # Pydantic 请求/响应模型
    │   │   ├── core/
    │   │   │   ├── security.py   # 密码哈希 + JWT
    │   │   │   ├── deps.py       # 依赖注入：当前用户 / 角色校验
    │   │   │   └── ws_manager.py # WebSocket 连接管理器
    │   │   └── api/
    │   │       ├── auth.py
    │   │       ├── clipboard.py
    │   │       ├── files.py
    │   │       ├── access.py
    │   │       ├── admin.py
    │   │       └── ws.py
    │   ├── alembic/              # 数据库迁移
    │   ├── alembic.ini
    │   ├── scripts/
    │   │   └── create_superadmin.py  # 初始化首个超级管理员
    │   ├── requirements.txt
    │   └── .env.example
    ├── frontend/
    │   ├── src/
    │   │   ├── main.js
    │   │   ├── App.vue
    │   │   ├── router/index.js   # 路由 + 登录/角色守卫
    │   │   ├── stores/
    │   │   │   ├── auth.js
    │   │   │   ├── clipboard.js
    │   │   │   ├── files.js
    │   │   │   └── admin.js
    │   │   ├── api/index.js      # axios 封装
    │   │   ├── ws/index.js       # WS 客户端（协议自适应）
    │   │   └── views/
    │   │       ├── LoginView.vue
    │   │       ├── RegisterView.vue
    │   │       ├── HomeView.vue          # 文本(+历史) + 文件主界面
    │   │       ├── AccessView.vue        # 凭访问码免登录查看
    │   │       └── admin/
    │   │           ├── AdminLayout.vue
    │   │           ├── DashboardView.vue
    │   │           ├── UsersView.vue
    │   │           ├── InvitesView.vue
    │   │           ├── FilesView.vue
    │   │           ├── CodesView.vue
    │   │           └── SettingsView.vue
    │   ├── index.html
    │   ├── package.json
    │   └── vite.config.js
    ├── storage/                  # 上传文件落盘，按 user_id 分目录
    │   └── <user_id>/<uuid>
    └── deploy/
        ├── nginx.http.conf       # HTTP 阶段
        ├── nginx.https.conf      # HTTPS 阶段
        └── clipsync.service      # systemd 单元
```

---

## 14. 部署方案（直接部署）

### 组件

- **MySQL**：建库建用户，配置到 `.env`。
- **后端**：`gunicorn -k uvicorn.workers.UvicornWorker`，systemd 托管。
- **前端**：`npm run build` 产出静态文件，Nginx 托管。
- **Nginx**：静态文件 + `/api`、`/ws` 反代，HTTP/HTTPS 两套配置切换。

### 上线步骤（概要）

```
1. 建 MySQL 库/用户，填 backend/.env（DEPLOY_SCHEME=http 起步）
2. cd backend && pip install -r requirements.txt && alembic upgrade head
3. python scripts/create_superadmin.py   # 创建首个超级管理员
4. cd frontend && npm install && npm run build
5. Nginx 用 nginx.http.conf 软链，reload
6. systemctl enable --now clipsync
7. （日后）证书就位 → 换 nginx.https.conf → 改 .env 开关 → reload
```

### Nginx 关注点

- `location /ws` 需 `Upgrade`/`Connection` 头支持 WebSocket。
- `client_max_body_size` 略大于单个分片大小。
- `/api` 反代加超时设置适配上传。
- HTTPS 配置额外含证书路径、80→443 跳转、可选 HSTS。

---

## 15. 分阶段实现计划

1. **地基**：目录结构、config（含开关）、database、models、Alembic 首次迁移。
2. **认证与角色**：security、注册（邀请码）、登录、当前用户/角色依赖、配额字段。
3. **文本同步 + 历史**：当前文本读写、历史记录/恢复、WS 管理器 + 广播。
4. **文件**：分片上传三步（含配额校验）、下载、删除、越权与穿越防护。
5. **快速访问码**：生成/撤销、免登录访问（文本实时/文件下载）、限流。
6. **管理后台**：统计、用户管理（含配额/角色）、邀请码、文件元数据总览、访问码管理、系统设置。
7. **前端**：登录/注册、主界面（文本+历史+文件）、访问码页、管理面板、WS 接入、路由守卫。
8. **部署**：Nginx 双配置、systemd、超管初始化脚本、README 切换说明。

