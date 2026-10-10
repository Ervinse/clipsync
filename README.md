# ClipSync

自托管的跨终端剪贴板与文件同步工具：粘贴文本即实时同步到你的其他终端，上传文件后其他终端即可下载。适合小范围、自托管的部署场景。

> - 开发环境搭建见第 16 节，配置项见第 17 节，已知限制见第 18 节
> - 部署（Docker Compose）见 [deployment/DEPLOYMENT.md](deployment/DEPLOYMENT.md)
> - 尚未完成的事项见 [TODO.md](TODO.md)
> - 文中标注「**未实现**」的条目是设计中有、代码里还没有的功能

---

## 1. 项目概述

ClipSync 是一个 B/S 架构的 Web 应用。用户在任意设备的浏览器中登录后：

- **文本同步**：粘贴的文本实时推送到该用户的其他在线终端，无需手动刷新。每个用户只有一段「当前文本」（相当于一个云剪切板），同时保留历史版本可回看。
- **文件同步**：上传的文件保存到服务器，其他终端可下载。后端广播 `file_added` / `file_deleted`，其他终端打开的文件页收到后自动刷新列表。
- **快速访问码**：为「自己的最新文本」或「某个文件」生成一个访问码，在**任意终端免登录**输入该码即可快速查看/下载。用途是方便自己跨设备取用，不是分发给他人。
- **文本历史**：每次保存时旧内容进入历史，保留最近 `HISTORY_KEEP` 条（默认 50）；可查看、载入编辑框、恢复为当前文本或删除。
- **多用户隔离**：普通用户只能看到自己的文本和文件。
- **邀请码注册**：一次性邀请码，可设过期时间；系统设置可关闭注册（关闭后持有邀请码也无法注册）。
- **三级权限**：普通用户 / 管理员 / 超级管理员，配套管理后台面板。
- **HTTP / HTTPS**：可以先以 HTTP 部署，切换 HTTPS 时应用代码不用改（见第 11 节）。

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
| ASGI 服务器 | Uvicorn（**单 worker**） | WebSocket 连接表与限流计数在进程内存中，不能多进程 |
| 数据库 | MySQL 8.4 LTS | 存用户与元数据，会话时区固定 UTC；Docker 镜像版本固定在 compose 中 |
| ORM / 驱动 | SQLAlchemy 2.0 (async) + aiomysql | 异步访问 MySQL（连接串 `mysql+aiomysql://`） |
| 迁移工具 | Alembic | 管理表结构版本 |
| 认证 | JWT (python-jose，HS256/384/512) + bcrypt | 无状态令牌 + 密码哈希（直接使用 `bcrypt` 库） |
| 限流 | slowapi | 登录、快速访问等接口限流 |
| 测试 | pytest + pytest-asyncio | 后端用例经 FastAPI `TestClient` 同步调用（pytest-asyncio 在依赖中，目前没有异步用例）；`pytest 路径::用例名` 跑单个 |
| 前端框架 | Vue 3 + Vite 8 | 组合式 API；Vite 8 要求 Node 20.19+ 或 22.12+ |
| 路由 | vue-router | 登录与角色守卫 |
| 状态管理 | Pinia | user / clipboard / files / access / admin 五个 store |
| HTTP 客户端 | axios | 统一封装、自动带 token |
| 实时通道 | 原生 WebSocket | 按 user_id 广播 |
| 文件存储 | 服务器本地磁盘 | 按 user_id 分目录 |
| 部署 | Docker Compose | MySQL、后端、前端（Nginx）三个容器；部署文件在 `deployment/docker/` |

---

## 3. 系统架构

```
                     内网 / 公网
                          │
                    ┌─────▼─────┐
                    │   Nginx    │  frontend 容器：HTTP 或 HTTPS
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
- 快速访问 `/access/<code>`（前端页面，文件码带 `?t=file`）→ 调 `/api/access/<code>` 或 `/api/access/<code>/download`（**免登录**）。

---

## 4. 权限模型（三级角色）

用户表的 `role` 枚举字段（`user` / `admin` / `superadmin`）区分三级角色。

| 能力 | 普通用户 user | 管理员 admin | 超级管理员 superadmin |
|------|:---:|:---:|:---:|
| 管理自己的文本/文件/访问码 | ✓ | ✓ | ✓ |
| 进入管理后台面板 | ✗ | ✓ | ✓ |
| 查看用户列表/详情、系统统计 | ✗ | ✓ | ✓ |
| 生成、查看、删除（未使用的）邀请码 | ✗ | ✓ | ✓ |
| 读取全局系统设置 | ✗ | ✓ | ✓ |
| 查看全站文件的**元数据** | ✗ | ✓ | ✓ |
| 修改用户存储配额 | ✗ | ✗ | ✓ |
| 启用/禁用用户、删除用户 | ✗ | ✗ | ✓ |
| 修改全局系统设置 | ✗ | ✗ | ✓ |
| 查看/下载他人文件**内容** | ✗ | **✗** | ✓ |

**未实现**：直接创建用户（免邀请码）、重置密码、变更角色、超管查看他人文本内容。目前提升管理员只能直接改数据库，超管通过 `scripts/create_superadmin.py` 创建。

> 关键区别：**管理员能看管理数据但看不到用户隐私内容**（只能看文件名、大小、时间等元数据）；**超级管理员才能下载他人文件**。这一约束在后端接口层强制：内容读取接口对 admin 与对普通用户一视同仁地做归属校验，仅 superadmin 可绕过。超管不能禁用或删除自己，也不能禁用或删除**其他** superadmin（返回 403）。

---

## 5. 数据模型

设计原则：**每条隐私数据都归属某个 `user_id`，查询时强制按当前登录用户过滤**。仅 superadmin 可绕过内容过滤。

### 5.1 users — 用户

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT PK | 自增主键 |
| username | VARCHAR(64) UNIQUE | 登录名 |
| password_hash | VARCHAR(255) | bcrypt 哈希，不存明文 |
| role | ENUM('USER','ADMIN','SUPERADMIN') | 角色，默认 USER（库中存枚举名大写，API 返回小写值 `user`/`admin`/`superadmin`） |
| quota_bytes | BIGINT | 存储配额；注册时取系统设置的默认配额（缺省 100MB），仅超管可改，上限 1TB |
| is_active | BOOLEAN | 是否启用（仅超管可禁用） |
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

> 一次性：注册成功即置 `used_by`/`used_at`，之后不可复用。判断「未使用」要求 `used_by` 与 `used_at` 都为 NULL：使用者被删除后 `used_by` 会被置空，但 `used_at` 保留，码仍不能再用。注册时对邀请码行加 `FOR UPDATE`，防止并发重复使用。邀请码为 16 位随机字母数字。

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
> **保留策略**：每用户保留最近 `HISTORY_KEEP` 条（`.env`，默认 50；不能在后台修改），超出部分按时间自动清理最旧记录。
> 文本内容按 UTF-8 编码后不超过 16777215 字节（MEDIUMTEXT 上限，迁移 `3f1c2a9d7b4e`），`ClipboardUpdate` 按字节数校验。

### 5.5 files — 文件元数据

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT PK | |
| user_id | BIGINT FK→users | 归属用户，查询按此过滤 |
| original_name | VARCHAR(255) | 原始文件名（入库前去掉控制字符与路径分隔符） |
| stored_name | VARCHAR(255) | 磁盘存储名（UUID，防冲突/穿越；存储层强制校验为 UUID） |
| size | BIGINT | 字节数 |
| mime_type | VARCHAR(128) | MIME 类型 |
| created_at | DATETIME | 上传完成时间 |

### 5.6 upload_sessions — 分片上传临时状态

| 字段 | 类型 | 说明 |
|------|------|------|
| upload_id | VARCHAR(36) PK | 服务端在 init 时生成的 UUID |
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
| code | VARCHAR(32) UNIQUE | 访问码字符串（12 位随机字母数字，`secrets` 生成，索引） |
| owner_id | BIGINT FK→users | 归属用户 |
| target_type | ENUM('TEXT','FILE') | 指向当前文本或某个文件（库中存大写枚举名，API 返回 `text`/`file`） |
| file_id | BIGINT FK→files NULL | 文件码：引用的文件 id；文本码为 NULL |
| expires_at | DATETIME NULL | 过期时间，NULL 不过期 |
| is_revoked | BOOLEAN | 是否已撤销 |
| created_at | DATETIME | |

> **文本访问码指向「当前最新文本」，不存快照**：每个用户只有一段文本（云剪切板），访问码用于属主在其他设备免登录读取该剪切板的**实时最新内容**；属主更新文本后，访问码解析到的内容随之更新。
> **文件访问码存引用**：记录具体 file_id，源文件删除时指向它的访问码一并删除（应用层显式删除 + 外键 `ON DELETE CASCADE`）。
> **不含访问计数、次数上限、访问日志**：访问码定位为属主跨设备免登录取用的入口，非对外分发功能。

### 5.8 settings — 系统设置（key-value）

| 字段 | 类型 | 说明 |
|------|------|------|
| key | VARCHAR(64) PK | 设置项名 |
| value | TEXT | 设置值（字符串） |
| updated_at | DATETIME | 更新时间 |

目前只使用两个 key：`registration_enabled`（`true`/`false`，缺省视为开放）与 `default_quota_bytes`（缺省回落 `.env` 的 `DEFAULT_QUOTA_BYTES`）。

> **外键无级联**：除 `access_codes.file_id` 外，所有外键都没有 `ON DELETE CASCADE`。删除用户时由 `DELETE /api/admin/users/{id}` 按依赖顺序显式删除访问码、上传会话、文件、历史、当前文本，处理其创建/使用过的邀请码，再删用户与磁盘目录。邀请码规则：该用户**使用过**的码保留记录、`used_by` 置空（`used_at` 保留，码仍不可复用）；该用户**创建的未使用**码直接删除；该用户创建的**已使用**码保留作审计，`created_by` 转记到执行删除的超管名下（`created_by` 为 NOT NULL，不改模型）。删除前锁住被删用户行，与 `upload/init` 串行化，避免新建会话的 tmp 目录成为孤儿；磁盘清理失败只记日志，由定时清理的孤儿扫描兜底。

> **时间约定**：所有 DATETIME 列存 naive UTC；数据库会话时区固定 `+00:00`，代码统一用 `utcnow()`。

---

## 6. API 设计

除注册、登录、快速访问外，`/api/*` 都需 `Authorization: Bearer <token>`。缺少或无效 token 返回 401，用户被禁用返回 403 并带响应头 `X-Auth-Error: disabled`（前端据此与普通「权限不足」的 403 区分并登出）。健康检查为 `GET /`。

限流（slowapi，按客户端 IP，进程内存计数）：注册 5 次/分钟、登录 10 次/分钟、`/api/access/*` 每个接口 30 次/分钟。

### 6.1 认证 `api/auth.py`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | /api/auth/register | 公开 | 用户名（3–64 位，字母数字及 `_.-`）+ 密码（8 位以上、不超过 72 字节）+ 邀请码；注册开关关闭时 403；新用户配额取系统设置的默认配额；返回 JWT |
| POST | /api/auth/login | 公开 | 返回 JWT；用户不存在与密码错误返回同样的 401，耗时一致 |
| GET | /api/auth/me | 登录 | 当前用户信息（含 role、配额、已用空间 `used_bytes`、上传中占用 `reserved_bytes`）；账号被禁用时 403 并带响应头 `X-Auth-Error: disabled` |

### 6.2 文本 `api/clipboard.py`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | /api/clipboard | 登录 | 获取自己的当前文本 |
| PUT | /api/clipboard | 登录 | 更新当前文本（upsert），旧内容入历史，广播 |
| GET | /api/clipboard/history | 登录 | 列出自己的全部文本历史版本（不分页，最多 `HISTORY_KEEP` 条） |
| POST | /api/clipboard/history/{id}/restore | 归属 | 把某历史版本恢复为当前文本，广播 |
| DELETE | /api/clipboard/history/{id} | 归属 | 删除某条历史版本，广播 |

> 前端：点击历史条目只把内容填回编辑框（不保存）；「恢复」按钮调 restore，「删除」按钮调 delete。文本内容按 UTF-8 字节数校验，上限 16777215 字节。

### 6.3 文件 `api/files.py`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | /api/files | 登录 | 列出自己的文件，并返回 `used_bytes`、`reserved_bytes`、`quota_bytes`（前端配额按 已用 + 上传中 计算） |
| POST | /api/files/upload/init | 登录 | 初始化分片上传（先校验配额），返回 upload_id |
| POST | /api/files/upload/chunk | 登录 | 上传单个分片 |
| POST | /api/files/upload/complete | 登录 | 合并分片，写记录，广播 |
| DELETE | /api/files/upload/{upload_id} | 归属 | 取消进行中的上传：删会话（立即释放配额）+ 清理 tmp；他人会话与不存在统一 404，正在合并返回 409 |
| GET | /api/files/{id}/download | 归属或 superadmin | 流式下载；无权限与不存在统一返回 404 |
| DELETE | /api/files/{id} | 归属 | 删文件记录+磁盘+指向它的访问码，广播（superadmin 也不能删他人文件） |

### 6.4 快速访问码 `api/access.py`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | /api/access-codes | 登录 | 为「当前文本」或「某个文件」生成访问码；`expires_at` 必须晚于当前时间，且不超过 8760 小时后；广播 `access_codes_changed` |
| GET | /api/access-codes | 登录 | 列出自己创建的访问码（含已撤销的；已过期的会被定时任务删除） |
| DELETE | /api/access-codes/{id} | 归属 | 撤销访问码（标记 `is_revoked`，记录保留），广播 `access_codes_changed` |
| GET | /api/access/{code} | **公开** | 免登录：**仅文本码**，返回属主当前最新文本 + 属主用户名 |
| GET | /api/access/{code}/download | **公开** | 免登录：**仅文件码**，流式下载文件内容 |

> 访问接口单独挂载在 `/api/access/*`，与需要登录的 `/api/access-codes`（管理自己的码）是两个独立路由，公开处理函数不会出现在 `/api/access-codes` 前缀下。

### 6.5 管理后台 `api/admin.py`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | /api/admin/stats | admin+ | 系统统计（用户总数、活跃用户、文件总数、总存储、访问码总数、有效访问码数） |
| GET | /api/admin/users | admin+ | 用户列表，分页 `skip`/`limit`（≤100），含配额、已用空间、文件数 |
| GET | /api/admin/users/{id} | admin+ | 用户详情（元数据，含剪贴板更新时间，不含内容） |
| PATCH | /api/admin/users/{id}/quota | **superadmin** | 修改配额 `{quota_bytes}`（0 到 1TB），给目标用户广播 `quota_updated` |
| PATCH | /api/admin/users/{id}/status | **superadmin** | 启用/禁用 `{is_active}`；禁用时立即断开其 WebSocket；不能操作自己（400）或其他 superadmin（403） |
| DELETE | /api/admin/users/{id} | **superadmin** | 删除用户及其全部数据并断开其 WebSocket；不能删除自己（400）或其他 superadmin（403） |
| GET | /api/admin/invite-codes | admin+ | 邀请码列表与状态 |
| POST | /api/admin/invite-codes | admin+ | 生成 16 位邀请码 `{expires_at?}`；`expires_at` 必须晚于当前时间 |
| DELETE | /api/admin/invite-codes/{id} | admin+ | 删除未使用的邀请码；已使用的保留作审计记录，返回 409 |
| GET | /api/admin/files | admin+ | 全站文件**元数据**，分页（无下载入口） |
| GET | /api/admin/settings | admin+ | 读取系统设置 `{default_quota_bytes, registration_enabled}` |
| PATCH | /api/admin/settings | **superadmin** | 修改上述两项设置（默认配额 0 到 1TB） |

**未实现**：直接创建用户、重置密码、变更角色、全站访问码管理。

> **隐私红线**：`/api/admin/files` 只返回元数据（属主、文件名、大小、时间），**不提供 admin 下载入口**；文件内容下载统一走 `/api/files/{id}/download`，该接口仅放行归属者与 superadmin。

---

## 7. 实时同步机制

### 连接管理器（core/ws_manager.py）

维护 `dict[user_id, set[WebSocket]]`，同一用户多终端在线时集合里有多条连接。

- **连接**：`/ws`，token 经子协议 `Sec-WebSocket-Protocol: clipsync.v1, bearer.<JWT>` 传递（不放 URL，避免进 access log）→ 校验签名、过期、用户存在且未禁用 → 服务端只回选 `clipsync.v1` → 加入集合。
- **握手被拒**：token 无效、用户不存在或被禁用时，服务端在 accept 之前关闭连接，浏览器只能看到 **1006**（与服务器不可达无法区分）。
- **踢下线**：已连接的用户被禁用或删除时，服务端以 **1008** 主动关闭其全部连接。
- **单进程**：连接表与限流计数都在进程内存中，后端必须单 worker 运行。
- **断开**：从集合移除，空则删 key。
- **广播**：`broadcast_to_user(user_id, message)`，发给该用户的**全部连接（含触发变更的终端）**，并发发送，单个连接超时 5 秒；发送失败或超时的连接会被移出集合。网络卡住的终端不会拖慢触发广播的 HTTP 请求。

### 事件类型

消息只携带轻量信号，不含正文：

```json
{ "type": "clipboard_updated", "data": { "updated_at": "..." } }
{ "type": "file_added",   "data": { "id": 1, "original_name": "...", "size": 123 } }
{ "type": "file_deleted", "data": { "id": 1 } }
{ "type": "access_codes_changed", "data": {} }
{ "type": "quota_updated", "data": { "quota_bytes": 104857600 } }
```

| 事件 | 触发 | 前端处理 |
|------|------|----------|
| `clipboard_updated` | 保存 / 恢复历史 / 删除历史（删除历史时 `data` 为空） | 剪贴板页静默重拉当前文本；历史面板打开时一并重拉历史（按请求序号丢弃过期结果） |
| `file_added` / `file_deleted` | 上传完成 / 删除文件 | 文件页静默重拉列表；访问码页在 `file_deleted` 时重拉（文件码被级联删除）；布局（`Home.vue`）刷新侧栏配额 |
| `access_codes_changed` | 创建 / 撤销访问码 | 访问码页重拉列表 |
| `quota_updated` | 超管修改该用户配额 | 布局刷新侧栏配额 |

- 页面级监听在挂载时注册、卸载时清理；各页面同时订阅 `open`，连接（重新）建立后补拉一次，断线期间的变更不会漏掉。
- 心跳：客户端每 30 秒发 `{"type":"ping"}`，服务端回 `{"type":"pong"}`；单条消息超过 1KB 服务端直接断开。心跳只在连接打开时发送，离线时不排队。
- 前端重连：指数退避（1s、2s、4s…，最长 30s），不限次数；网络恢复（`online`）或页面回到前台时立即重试。收到 1008 时停止重连并登出。连接从未打开就关闭（多为握手被拒的 1006）时，前端调一次 `/api/auth/me` 确认会话：401 / 禁用 403 则登出、不再重连，其他情况继续退避重连。登出时主动断开，不会自动重连。
- 重连只使用本标签页内存中的 token，不读 localStorage；其他标签页换账号改写 localStorage 时，本页整页重载。

### WebSocket 协议自适应（HTTP/HTTPS 通用）

前端不写死协议，根据当前页面协议自动选择，两套部署都无需改代码：

```js
const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
const ws = new WebSocket(`${proto}//${location.host}/ws`, ['clipsync.v1', `bearer.${token}`])
```

---

## 8. 快速访问码机制

> 定位：**供属主本人跨设备免登录取用自己内容的入口**，非对外分发功能。因此不设访问次数、访问日志等分发控制。

### 生成

登录用户调用 `POST /api/access-codes`：

- **文本码** → 只记录 `target_type='text'` 与 `owner_id`，**不存快照**。访问时实时读取属主的当前文本。
- **文件码** → 记录 `target_type='file'` 与 `file_id`。
- 可选 `expires_at`（过期时间，带时区的时间会转为 UTC 存储）。
- 后端响应中的 `access_url` 是按请求 `scheme` + `host` 拼出的**前端访问页地址**：`http(s)://<host>/access/<code>`，文件码追加 `?t=file`。前端「复制链接」直接使用 `access_url`，不自行拼接。
- 开发环境下 Vite 的 `/api` 代理需设 `changeOrigin: false`，保留浏览器的 Host（`localhost:3000`），否则拼出的链接会指向后端端口。

### 访问（免登录）

在任意终端打开 `/access/<code>`（前端访问页），或直接调 API：

```
GET /api/access/<code>            # 仅文本码：实时查属主 clipboard，返回当前最新文本
GET /api/access/<code>/download   # 仅文件码：文件内容流式下载
  校验：存在 / 类型匹配 / 未撤销 / 未过期 / 属主未被禁用 / 文件仍属于属主
```

- 撤销、过期、（文件码）源文件删除或磁盘文件丢失、属主被禁用，都会使访问码失效。属主被禁用只是暂时失效：重新启用后，未撤销、未过期的码自动恢复可用。
- 有效期最长 8760 小时（1 年），前后端都校验。过期的码由定时任务 `cleanup_expired` 删除；撤销的码保留记录，前端分别显示「已撤销」「已过期」。
- 以上任何一种失效情况都统一返回 404「访问码无效或已失效」，不暴露码是否存在。

### 安全考量

- `code` 为 12 位随机串（62^12），并对 `/api/access/*` 限流（30 次/分钟/IP）。
- 免登录接口同样防路径穿越（文件按 file_id 查库拿 stored_name）。
- 访问码遵循「知道码即可查看」模型，界面须提示：访问码等同于对应内容的免登录凭证，应妥善保管；敏感内容可设置过期时间或及时撤销。

---

## 9. 管理后台面板

面向 admin / superadmin 的前端区域：`/admin` 路由，单个页面 `views/Admin.vue`，路由守卫校验 role。

### 页面结构（5 个 tab）

```
/admin
├── 统计      # 总用户、活跃用户、文件总数、总存储
├── 用户      # 分页列表；改配额 / 启用禁用 / 删除 按钮仅超管可见（superadmin 行不显示禁用、删除）
├── 邀请码    # 生成（填有效天数，0 为永久）/ 列表（已使用 / 已过期 / 可用）/ 复制 / 删除（已使用的不显示删除）
├── 文件      # 全站文件【元数据】分页列表（admin 与 superadmin 均可见，无下载入口）
└── 设置      # 开放注册、新用户默认配额：admin 只读，superadmin 可保存
```

**未实现**：全站访问码管理、超管在后台直接下载他人文件的入口（超管可调 `/api/files/{id}/download`）。

### 系统设置（存 DB，可热更新）

后台可修改的只有两项（通过 `PATCH /api/admin/settings`，仅超管）：

- 是否开放注册（`registration_enabled`）
- 新用户默认配额（`default_quota_bytes`，默认 100MB）

单文件上限、分片大小、历史保留条数、上传会话过期时间、每用户并发上传会话数都只能在 `.env` 里配置，改后需重启后端。邀请码没有「默认有效期」设置，由前端按填写的天数换算成 `expires_at`。

### 前端角色控制

- 路由守卫：非 admin/superadmin 访问 `/admin` 直接重定向。
- 组件级：用户管理的修改按钮仅当 `role === 'superadmin'` 时渲染。
- **后端才是权限的最终防线**，前端隐藏只是体验层，所有接口都做服务端角色校验。

---

## 10. 文件分片上传方案

单文件可达上百 MB，必须分片。

```
1. init     → POST /api/files/upload/init  JSON {original_name, total_size, chunk_size}
              清理本用户过期会话 → 校验单文件上限、并发会话数、配额
              chunk_size 取请求值，不超过 CHUNK_SIZE，且分片总数不超过 10000（过小时自动调大）
              → 建 upload_session，返回 {upload_id, total_chunks, chunk_size}（以服务端返回为准）
2. chunk×N  → POST /api/files/upload/chunk  multipart {upload_id, chunk_index, chunk_data}
              校验归属、会话未过期、chunk_index < total_chunks
              每片大小必须等于期望值：非最后一片 = chunk_size，最后一片 = 剩余字节；超出 413，不足 400
              线程池中写 tmp/{upload_id}/{index}.<随机>.part，完成后原子替换为 {index}
              失败可重传该片（断点续传）；同一片并发重传不会互相截断
3. complete → POST /api/files/upload/complete  JSON {upload_id}
              同一 upload_id 并发 complete 返回 409；会话过期返回 404
              校验分片 0..N-1 齐全 → 线程池中按序流式合并到 storage/{user_id}/{uuid}
              实际大小必须等于 total_size → 按实际大小再校验配额
              写 files 记录 → 删会话与 tmp → 广播 file_added
              提交失败时删除已合并的文件，不留孤儿文件
```

- 分片大小：前端请求 1MB，服务端上限 `CHUNK_SIZE`（`.env`，默认 5MB），不能在后台修改。
- 配额：已用 = 已落盘文件 + **进行中会话的声明大小**，防止并发开会话超配；init 预校验，complete 按实际大小最终确认。
- 取消：上传中途失败时前端调 `DELETE /api/files/upload/{upload_id}` 立即释放配额；关掉页面等无法取消的会话，靠 `/auth/me` 与 `GET /api/files` 返回的 `reserved_bytes`（侧栏显示「上传中」）让用户看见，并在 TTL 后清理。
- 每用户进行中的上传会话不超过 `MAX_UPLOAD_SESSIONS_PER_USER`（默认 5），超出返回 429。
- 会话过期：超过 `UPLOAD_SESSION_TTL_HOURS`（默认 24）的会话，在该用户下次 init 时清理；定时任务 `backend/scripts/cleanup_expired.py`（宿主机 cron 经 `docker compose exec` 每小时执行）清理全站过期会话与 tmp 目录，并做孤儿扫描（超过 TTL 且无会话记录的 tmp 目录、用户已不存在的 `storage/<uid>` 目录）。
- 下载：线程池中先打开文件再 `fstat` 取大小，下载途中文件被删也能读完；文件不存在返回 404（公开访问码路径统一提示「访问码无效或已失效」）。
- 应用内磁盘删除失败只记日志（`rmtree` 用 `onexc` 回调），不影响接口结果，残留由孤儿扫描兜底。
- 合并与下载都流式处理，不一次性读入内存。

---

## 11. HTTP / HTTPS 切换

可以先以 HTTP 部署，日后切到 HTTPS。设计目标：**切换只动 Nginx 配置与 `.env` 开关，应用代码零改动**。

### 保障平滑切换的三项设计

1. **前端不写死协议**
   - API 走相对路径（`/api/...`），跟随页面协议。
   - WebSocket 按 `window.location.protocol` 自动选 `ws://`/`wss://`（见第 7 节）。
   - 访问码链接由后端按请求的 `scheme` + `host` 动态拼接，不硬编码。

2. **Nginx 配置可替换**：frontend 容器的 Nginx 读取挂载进去的 `deployment/docker/nginx-docker.conf`（HTTP，监听 80）。切换 HTTPS 时换成带 443 与证书的配置并映射 443 端口，步骤见 [deployment/DEPLOYMENT.md](deployment/DEPLOYMENT.md)「使用 HTTPS」。

3. **环境开关**（`.env`）：

   | 变量 | HTTP 阶段 | HTTPS 阶段 | 作用 |
   |------|:---:|:---:|------|
   | `HSTS_ENABLED` | false | true | 由**后端中间件**下发 `Strict-Transport-Security`（HTTP 阶段不能开） |
   | `CORS_ORIGINS` | `http://` 访问地址 | `https://` 访问地址 | 允许来源白名单，逗号分隔，忽略 `*` |
   | `DEPLOY_SCHEME` | http | https | **预留，代码未读取**；访问码链接按请求的 scheme 拼接 |
   | `COOKIE_SECURE` | false | true | **预留，代码未读取**；当前不使用 cookie |

### 阶段说明与提示

- **HTTP 阶段的风险**：密码、JWT、文本、文件明文传输，网络链路上的任何一方都能看到。HTTP 只适合测试或可信内网；正式使用，尤其是暴露在公网时，应切换 HTTPS（第 17 节也有提示）。
- Token 采用 `Authorization` header + 前端 localStorage，HTTP/HTTPS 行为一致，不依赖 cookie，切换协议无需改动应用代码。
- 升级 HTTPS 时：申请证书（如 Let's Encrypt）→ 换成 HTTPS 版 Nginx 配置并映射 443 → 改 `.env` 开关 → 重建 frontend、backend 容器。无需改动数据库或应用逻辑。

---

## 12. 安全设计

| 项 | 措施 |
|----|------|
| 传输加密 | HTTP（测试 / 可信内网）与 HTTPS（正式使用）可切换，HTTP 下全部内容明文传输（第 11、17 节）。 |
| 密码存储 | bcrypt 哈希，绝不存明文，不在日志/响应回显。 |
| 认证 | JWT，必须带 `exp`（默认 7 天），只允许 HS 系列算法；`JWT_SECRET` 少于 32 位或为示例值时后端拒绝启动；每次请求回库校验用户存在且未禁用。 |
| 角色权限 | 三级角色后端强制校验；admin 看不到文件/文本内容，仅 superadmin 可绕过。 |
| 登录爆破 | 注册、登录、快速访问接口限流；登录在用户不存在时也执行一次 bcrypt，防时序枚举。限流按真实客户端 IP，依赖 uvicorn `--proxy-headers` 信任反代传来的 `X-Forwarded-For`。 |
| 数据隔离 | 隐私查询强制 `WHERE user_id = current_user`，仅 superadmin 例外。 |
| 越权访问 | 下载/删除先校验归属；访问码按 code 查库，不信任客户端传入路径。 |
| 路径穿越 | 磁盘名用 UUID，绝不用用户文件名拼路径。 |
| 访问码 | code 足够随机 + 限流 + 可设过期 + 可撤销；前端提示用户妥善保管。 |
| 上传限制 | Nginx `client_max_body_size`；后端校验单文件上限、单分片字节数、并发会话数与配额。 |
| 响应头 | 下载用 RFC 6266 编码的 `Content-Disposition`，防头注入；全局下发 `X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Referrer-Policy: no-referrer`。 |
| WebSocket | token 走子协议头不进 URL；禁用/删除用户时主动断开其连接。 |
| 错误信息 | 不把底层异常细节（路径等）返回客户端。 |
| 邀请码 | 一次性、可过期、仅管理员生成。 |
| CORS | 按 `.env` 的 `CORS_ORIGINS` 限定，不用通配。 |

---

## 13. 目录结构

```
CodeProject/
└── clipsync/                     # ← 本项目根目录
    ├── README.md                 # 本文档（项目说明与设计）
    ├── TODO.md                   # 尚未完成的事项
    ├── CLAUDE.md                 # 编码硬约束
    ├── test_integration.sh       # 简易连通性检查（curl 后端健康检查、注册、登录与前端首页）
    ├── backend/
    │   ├── app/
    │   │   ├── main.py           # FastAPI 入口，挂载路由、CORS、安全响应头
    │   │   ├── config.py         # 读取 .env，校验 JWT_SECRET 强度
    │   │   ├── database.py       # 异步 engine / session 工厂（会话时区 UTC）
    │   │   ├── rate_limit.py     # slowapi 限流器
    │   │   ├── models/           # user / invite / clipboard / file / access_code / setting
    │   │   ├── schemas/          # Pydantic 请求/响应模型
    │   │   ├── core/
    │   │   │   ├── security.py     # 密码哈希 + JWT
    │   │   │   ├── deps.py         # 依赖注入：当前用户 / 角色校验
    │   │   │   ├── ws_manager.py   # WebSocket 连接管理器
    │   │   │   ├── storage.py      # 磁盘路径（UUID 校验 + 根目录约束）
    │   │   │   ├── http_utils.py   # 文件名清洗 + Content-Disposition
    │   │   │   ├── app_settings.py # 读 settings 表
    │   │   │   └── timeutil.py     # UTC 时间工具
    │   │   └── api/              # auth / clipboard / files / access / admin / ws
    │   ├── alembic/versions/     # 278c88a5f21f 初始表结构；3f1c2a9d7b4e 文本改 MEDIUMTEXT
    │   ├── alembic.ini
    │   ├── scripts/              # create_superadmin.py / cleanup_expired.py（定时清理，由宿主机 cron 经 docker compose exec 调用）
    │   ├── tests/                # pytest 用例：安全边界、并发、实时推送、上传下载等（使用独立库 clipsync_test）
    │   ├── pytest.ini
    │   ├── requirements.txt      # 运行依赖（生产镜像只装这个）
    │   ├── requirements-dev.txt  # 运行依赖 + pytest 等测试依赖
    │   ├── .env.example
    │   └── storage/              # 上传文件落盘（STORAGE_DIR 默认 ./storage，相对 backend/；已 gitignore）
    │       ├── <user_id>/<uuid>
    │       └── tmp/<upload_id>/<chunk_index>
    ├── frontend/
    │   ├── src/
    │   │   ├── main.js
    │   │   ├── App.vue
    │   │   ├── style.css         # 全局样式
    │   │   ├── router/index.js   # 路由 + 登录/角色守卫
    │   │   ├── api/              # request.js(axios 封装) + auth/clipboard/files/access/admin
    │   │   ├── stores/           # user / clipboard / files / access / admin
    │   │   ├── utils/
    │   │   │   ├── websocket.js    # WS 客户端（协议自适应、重连、心跳）
    │   │   │   ├── clipboard.js    # 复制到剪贴板（HTTP 下降级为 execCommand）
    │   │   │   └── format.js       # 文件大小、UTC 时间格式化
    │   │   └── views/
    │   │       ├── Login.vue / Register.vue
    │   │       ├── Home.vue          # 登录后布局（侧边栏）
    │   │       ├── Clipboard.vue     # 文本 + 历史
    │   │       ├── Files.vue         # 文件
    │   │       ├── AccessCodes.vue   # 访问码管理
    │   │       ├── Admin.vue         # 管理后台（5 个 tab）
    │   │       └── PublicAccess.vue  # 凭访问码免登录查看 /access/:code
    │   ├── public/               # favicon.svg / icons.svg
    │   ├── index.html
    │   ├── README.md             # 前端说明
    │   ├── package.json
    │   └── vite.config.js        # 开发端口 3000，代理 /api 与 /ws 到 127.0.0.1:8000
    └── deployment/
        ├── DEPLOYMENT.md              # 部署手册（Docker Compose）
        └── docker/
            ├── docker-compose.yml         # db / backend / frontend，按镜像名启动
            ├── docker-compose.build.yml   # 叠加使用：在服务器上从源码构建镜像
            ├── docker-compose.https.yml   # 叠加使用：映射 443、改用 HTTPS 版 Nginx 配置
            ├── Dockerfile.backend / Dockerfile.frontend
            ├── nginx-common.conf          # Nginx 公共规则（静态文件、/api、/ws、证书验证）
            ├── nginx-docker.conf          # HTTP 站点（默认）
            ├── nginx-https.conf           # HTTPS 站点（80 跳转 443）
            ├── .env.example               # compose 环境变量模板
            ├── backup.sh                  # 备份数据库与上传文件（宿主机 cron 调用）
            ├── health_check.sh            # 版本、容器、接口、数据库、磁盘、备份、证书检查
            ├── cert.sh                    # 用 certbot 申请 / 续期 Let's Encrypt 证书
            ├── clipsync.cron              # 宿主机定时任务模板（清理、备份、证书续期）
            ├── clipsync.logrotate         # 定时任务日志轮转
            ├── build-release.ps1          # 开发机构建镜像并打包（镜像包 + 部署包），按提交号打标签
            └── publish-release.ps1        # 测试通过的构建晋级为正式版本：追加版本号标签并生成发布包，不重新构建
```

---

## 14. 部署方案（Docker Compose）

### 组件

只支持 Docker Compose 部署，完整步骤见 [deployment/DEPLOYMENT.md](deployment/DEPLOYMENT.md)。服务器只需要 x86_64 Linux + Docker，发行版不限。

### 组件（`deployment/docker/docker-compose.yml`，项目名固定为 `clipsync`）

| 服务 | 镜像 | 说明 |
|------|------|------|
| db | `mysql:8.4.x`（版本号固定在 compose 中） | 数据卷 `clipsync_mysql_data`；3306 只绑定宿主机 `127.0.0.1`，供宿主机与 SSH 隧道查询 |
| backend | `clipsync-backend`（`Dockerfile.backend`） | 启动时先 `alembic upgrade head`，再以**单 worker** 运行 uvicorn；非 root 用户；数据卷 `clipsync_storage_data` → `/app/storage`；不对宿主机暴露端口 |
| frontend | `clipsync-frontend`（`Dockerfile.frontend`） | Nginx 托管 Vue 构建产物，反代 `/api`、`/ws` 到 backend；宿主机端口 `HTTP_PORT`（默认 80），HTTPS 时另映射 443 |

- **必须单 worker**：WebSocket 连接表与限流计数都在进程内存中，多进程会导致实时同步与限流失效。
- **真实客户端 IP**：compose 使用固定子网 `172.28.0.0/16`，uvicorn 只信任这个网段发来的 `X-Forwarded-For`；Nginx 用 `$remote_addr` 覆盖该头，客户端自带的值一律丢弃。
- **镜像来源**：默认在开发机用 `build-release.ps1` 构建并打包，服务器 `docker load` 导入后启动，不需要联网下载；网络通畅的服务器也可叠加 `docker-compose.build.yml` 从源码构建。backend、frontend 设 `pull_policy: never`，不会从镜像仓库拉取同名镜像。
- **版本标签**：镜像带 git 提交号标签；只有 master 上的提交额外标 `latest`。测试通过的构建由 `publish-release.ps1` 追加版本号标签（如 `1.0.0-alpha.1`）生成发布包，镜像不重新构建。服务器按 `.env` 的 `CLIPSYNC_TAG` 选用镜像。
- **定时任务**：宿主机 cron 每小时经 `docker compose exec` 执行 `scripts.cleanup_expired`，每天执行 `backup.sh` 备份数据库与上传文件（模板 `clipsync.cron`）。

### Nginx 关注点（`nginx-docker.conf` / `nginx-https.conf`，公共部分在 `nginx-common.conf`）

- `proxy_pass` 用变量 + `resolver 127.0.0.11`：backend 容器重建后 IP 会变，Nginx 运行时重新解析。
- `location /ws` 需 `Upgrade`/`Connection` 头支持 WebSocket。
- `client_max_body_size` 略大于单个分片大小（`CHUNK_SIZE` 默认 5MB，Nginx 限 10MB）。
- `/api` 反代加超时设置适配上传；`Host` 用 `$http_host`（保留端口，访问码链接才正确）。
- 前端页面 `/access/<code>` 是 SPA 路由，由 `try_files` 回落到 `index.html`，**不要**把 `/access` 反代到后端。
- 静态页面由 Nginx 加 `X-Frame-Options`、`X-Content-Type-Options`、`Referrer-Policy`；`index.html` 不缓存，带哈希的 `/assets/` 长期缓存；`/api` 的安全头由后端下发。
- `/.well-known/acme-challenge/` 指向挂载的 `acme/` 目录，供 certbot 以 webroot 方式申请与续期证书。
- HTTPS 配置额外含证书路径、80→443 跳转。**HSTS 只由后端按 `HSTS_ENABLED` 下发**，Nginx 不配置。

---

## 15. 功能模块与实现范围

| 模块 | 已实现 | 未实现 |
|------|------|------|
| 基础 | 配置（含 HTTP/HTTPS 开关）、异步数据库、数据模型、Alembic 迁移 | — |
| 认证与角色 | 邀请码注册、登录、JWT、三级角色校验、存储配额 | 直接创建用户、重置密码、变更角色 |
| 文本同步 | 当前文本读写、历史查看 / 恢复 / 删除、WebSocket 广播 | — |
| 文件 | 分片上传（配额校验、取消）、流式下载、删除、越权与路径穿越防护 | 前端断点续传 |
| 快速访问码 | 生成 / 撤销、免登录访问（文本实时 / 文件下载）、限流 | — |
| 管理后台 | 统计、用户管理（配额 / 启用禁用 / 删除）、邀请码、全站文件元数据、系统设置 | 变更角色、全站访问码管理 |
| 前端 | 登录 / 注册、剪贴板、文件、访问码、管理后台、公开访问页、路由守卫、WebSocket 接入 | 自动化测试 |
| 部署 | Docker Compose（开发机构建离线导入 / 服务器源码构建）、HTTP / HTTPS Nginx 配置、Let's Encrypt 证书申请与续期、备份 / 清理 / 健康检查脚本 | 不使用 Docker 的直接部署（不支持） |

未实现与待验证的事项汇总在 [TODO.md](TODO.md)。

---

## 16. 开发环境快速开始

先决条件：Python 3.12+、Node.js 20.19+ 或 22.12+（Vite 8 的要求）、已运行的 MySQL 8.4（与部署环境一致）。

### 1. 创建数据库

本机没有 MySQL 8.4 时，可以用 Docker 启动一个开发用实例，然后在 `backend/.env` 里设 `DB_HOST=127.0.0.1`、`DB_PORT=3307`、`DB_USER=root`：

```bash
docker run -d --name clipsync-dev-mysql -p 127.0.0.1:3307:3306 \
    -v clipsync_dev_mysql:/var/lib/mysql -e MYSQL_ROOT_PASSWORD=<开发库密码> mysql:8.4.11
```

```sql
CREATE DATABASE clipsync CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 2. 后端

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt   # 运行依赖 + 测试依赖（生产镜像只装 requirements.txt）

cp .env.example .env
# 编辑 .env：填写 DB_* 连接信息；JWT_SECRET 用 `openssl rand -hex 32` 生成
# JWT_SECRET 少于 32 位或含示例占位片段（如 change_this、your_）时后端拒绝启动

alembic upgrade head                 # 建表
python -m scripts.create_superadmin  # 创建第一个超级管理员（交互式）
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
pytest                                   # 全部
pytest tests/test_auth.py::test_name    # 单个
```

测试使用 `.env` 中的 MySQL 账号，每次运行都会 **DROP 并重建** 独立的 `clipsync_test` 库（开发库不受影响），所以该账号需要建库、删库权限。测试会自行生成临时 `JWT_SECRET` 和临时存储目录，不依赖 `.env` 中的这两项。

什么时候需要跑：

| 改动内容 | 验证方式 |
|------|------|
| 只改文档（`*.md`）或注释 | 不跑测试，也不构建前端 |
| `backend/` 的代码、迁移、依赖 | `pytest` |
| `frontend/` 的代码、依赖、`vite.config.js` | `npm run build`，界面行为在浏览器里手动验证（前端没有自动化测试） |
| `deployment/docker/*.sh` | `bash -n` 语法检查；装有 Docker 时在本机 compose 环境实际运行 |
| `deployment/docker/build-release.ps1`、`publish-release.ps1` | PowerShell 语法解析；装有 Docker Desktop 时实际运行一次 |
| compose、Dockerfile、Nginx 配置 | `docker compose config` 校验；装有 Docker 时构建并启动一次 |

完整规则见 CLAUDE.md「按改动范围验证」；尚待手动验证的行为见 [TODO.md](TODO.md)。生产镜像不包含测试代码与测试依赖，生产环境不运行测试。

---

## 17. 配置项（backend/.env）

默认值以 `backend/app/config.py` 为准。本节是后端读取的变量：开发环境写在 `backend/.env`；Docker 部署写在部署目录的 `.env`（模板 `deployment/docker/.env.example`），由 compose 传给 backend 容器，其中 `DB_HOST`、`DB_PORT`、`STORAGE_DIR` 由 compose 固定，另有 `CLIPSYNC_TAG`、`HTTP_PORT`、`DB_HOST_PORT`、`DB_ROOT_PASSWORD`、`COMPOSE_FILE` 等部署专用变量（见 [deployment/DEPLOYMENT.md](deployment/DEPLOYMENT.md)「配置说明」）。

| 变量 | 说明 | 代码默认值 |
|------|------|------|
| `DB_HOST` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` | MySQL 连接 | 必填 |
| `DB_PORT` | MySQL 端口 | 3306 |
| `JWT_SECRET` | JWT 签名密钥，至少 32 位且不含示例占位片段 | 必填 |
| `JWT_ALGORITHM` | 仅允许 HS256 / HS384 / HS512 | HS256 |
| `JWT_EXPIRE_MINUTES` | 令牌有效期 | 10080（7 天） |
| `HSTS_ENABLED` | 是否下发 HSTS（仅 HTTPS 下开启） | false |
| `CORS_ORIGINS` | 允许的前端来源，逗号分隔，忽略 `*` | http://localhost:5173（`.env.example` 按开发端口写为 3000） |
| `DEPLOY_SCHEME` / `COOKIE_SECURE` | 预留，代码未使用 | http / false |
| `STORAGE_DIR` | 文件存储根目录（相对 `backend/`） | ./storage |
| `DEFAULT_QUOTA_BYTES` | 系统设置未配置时的新用户默认配额 | 104857600（100MB） |
| `MAX_FILE_BYTES` | 单文件上限 | 524288000（500MB） |
| `CHUNK_SIZE` | 单分片上限（客户端请求值会被裁剪到此值） | 5242880（5MB） |
| `MAX_UPLOAD_SESSIONS_PER_USER` | 单用户同时进行的上传会话上限 | 5 |
| `HISTORY_KEEP` | 每用户保留的文本历史条数 | 50 |
| `UPLOAD_SESSION_TTL_HOURS` | 未完成上传会话的过期时间 | 24 |

数据库中的系统设置只有两项：**是否开放注册**、**新用户默认配额**，优先于 `.env`，在管理后台「设置」页修改（见第 9 节）。其余各项只能改 `.env` 并重启后端。

> ⚠️ **HTTP 阶段安全提示**：纯 HTTP 下密码、令牌和所有内容都明文传输，只适合测试或可信内网；正式使用应切换 HTTPS（见第 11 节）。

---

## 18. 已知限制

- **单进程**：WebSocket 连接表与限流计数都在进程内存中，后端只能单 worker、单实例运行。多实例需要引入跨进程消息（如 Redis pub/sub）并改造广播层与限流存储。
- **本地磁盘存储**：文件存在服务器本地 `STORAGE_DIR`（Docker 部署为数据卷 `clipsync_storage_data`），没有对象存储支持；`deployment/docker/backup.sh` 分别备份数据库与上传文件，备份默认与服务器在同一块硬盘上，需要定期复制到其他机器。
- **监控**：只有 `deployment/docker/health_check.sh` 的基础检查，没有接入专门的监控系统。
- **部署平台**：只支持 x86_64 Linux 上的 Docker Compose；`build-release.ps1`、`publish-release.ps1` 只能在 Windows 上运行，其他系统用服务器源码构建（方式 B）。
- **测试范围**：后端有 pytest 用例（`backend/tests/`）；前端没有自动化测试，界面行为需手动验证。

