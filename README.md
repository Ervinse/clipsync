# ClipSync

自托管的跨终端剪贴板与文件同步工具：粘贴文本即实时同步到你的其他终端，上传文件后其他终端即可下载。适合小范围、自托管的部署场景。

> - 开发环境搭建见第 16 节，配置项见第 17 节，已知限制见第 18 节
> - 部署（Docker Compose）见 [deployment/DEPLOYMENT.md](deployment/DEPLOYMENT.md)
> - 尚未完成的事项见 [TODO.md](TODO.md)
> - 文中标注「**未实现**」的条目是设计中有、代码里还没有的功能

---

## 1. 项目概述

ClipSync 是一个 B/S 架构的 Web 应用。用户在任意设备的浏览器中登录后：

- **云剪切板**：粘贴的文本实时推送到该用户的其他在线终端，无需手动刷新。每个用户只有一段「当前文本」，同时保留历史版本可回看。
- **文本栏目**：与云剪切板分开的多段独立文本（每人最多 200 段，可选标题），每段可以单独设置访问码。
- **文件同步**：上传的文件保存到服务器，其他终端可下载。后端广播 `file_added` / `file_deleted`，其他终端打开的文件页收到后自动刷新列表。
- **快速访问码**：用户自己给云剪切板、某段文本或某个文件设置访问码（每样内容最多一个，多样内容可以用同一个）。在任意设备的登录页输入「用户名@访问码」即可**免登录**进入，看到该访问码下的全部内容：文本可查看与修改，文件可下载；不能新建、删除、上传。用途是方便自己跨设备取用，不是分发给他人。
- **文本历史**：每次保存时旧内容进入历史，保留最近 `HISTORY_KEEP` 条（默认 50）；可查看、载入编辑框、恢复为当前文本或删除。
- **多用户隔离**：普通用户只能看到自己的文本和文件。
- **邀请码注册**：一次性邀请码，一次可生成 1–20 个，每次生成是一批、可写备注；可设过期时间、生成后可批量修改；后台按批次列出，可搜索、按状态筛选，随时重新复制一批里可用的码组成的邀请信息；系统设置可关闭注册（关闭后持有邀请码也无法注册）。
- **三级权限**：普通用户 / 管理员 / 超级管理员，配套管理后台面板。
- **HTTP / HTTPS**：可以先以 HTTP 部署，切换 HTTPS 时应用代码不用改（见第 11 节）。

### 核心使用场景

在公司电脑复制一段文本/一个文件 → 打开网页粘贴/上传 → 回家用另一台电脑登录即可看到；或者不想登录，事先给文本/文件设置一个访问码（如 `work`），在任意浏览器的登录页输入 `用户名@work` 就能查看、修改这些文本或下载文件。

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
| 测试 | pytest + httpx | 后端用例经 FastAPI `TestClient`（基于 httpx）同步调用；`pytest 路径::用例名` 跑单个 |
| 前端框架 | Vue 3 + Vite 8 | 组合式 API；Vite 8 要求 Node 20.19+ 或 22.12+ |
| 路由 | vue-router | 登录与角色守卫 |
| 状态管理 | Pinia | user / clipboard / texts / files / access / quick / admin 七个 store |
| HTTP 客户端 | axios | 统一封装、自动带 token |
| 图标 / 字体 | @lucide/vue + @fontsource-variable/inter | 细线图标；Inter 字体随前端打包，不依赖外网字体服务 |
| 实时通道 | 原生 WebSocket | 按 user_id 广播；快速访问页按「属主 + 访问码」推送 |
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
                  │ 文本/邀请码│   └────────────┘
                  └──────────┘
```

**四类入口**：
- 浏览器访问 `/` → Nginx 返回 Vue 构建产物。
- 登录用户调用 `/api/*` → 反代到 FastAPI（带 JWT）。
- 实时通道 `/ws` → WebSocket upgrade → 连接管理器。
- 快速访问：登录页输入「用户名@访问码」→ `POST /api/access/login` 换取快速访问凭证 → 前端页面 `/quick` 调 `/api/access/*` 与 `/ws`（**免登录**，凭证只对这些接口有效）。

---

## 4. 权限模型（三级角色）

用户表的 `role` 枚举字段（`user` / `admin` / `superadmin`）区分三级角色。

| 能力 | 普通用户 user | 管理员 admin | 超级管理员 superadmin |
|------|:---:|:---:|:---:|
| 管理自己的云剪切板/文本/文件/访问码 | ✓ | ✓ | ✓ |
| 进入管理后台面板 | ✗ | ✓ | ✓ |
| 查看用户列表/详情、系统统计 | ✗ | ✓ | ✓ |
| 生成、查看邀请码；修改备注与有效期、删除（未使用的）邀请码 | ✗ | ✓ | ✓ |
| 读取全局系统设置 | ✗ | ✓ | ✓ |
| 查看全站文件的**元数据** | ✗ | ✓ | ✓ |
| 修改用户存储配额 | ✗ | ✗ | ✓ |
| 启用/禁用用户、删除用户 | ✗ | ✗ | ✓ |
| 修改全局系统设置 | ✗ | ✗ | ✓ |
| 查看/下载他人文件**内容** | ✗ | **✗** | ✓ |

**未实现**：直接创建用户（免邀请码）、重置密码、变更角色、超管查看他人文本内容。目前提升管理员只能直接改数据库，超管通过 `scripts/create_superadmin.py` 创建（用户名规则与注册一致：3–64 位，只含字母、数字和 `_ . -`，不能含 `@`，否则「用户名@访问码」无法拆分）。

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

### 5.2 invite_batches / invite_codes — 邀请码批次与邀请码

每次生成的邀请码是一批（只生成 1 个也算一批），备注写在批次上。

**invite_batches**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT PK | |
| note | VARCHAR(100) | 备注，可为空字符串；生成后可修改 |
| created_by | BIGINT FK→users | 谁生成的（管理员/超管） |
| created_at | DATETIME | 生成时间 |

> 批次里的码被删光时批次一起删除，不留空批次；还剩已使用的码时批次与备注保留。有效期不放在批次上：同一批生成时共用一个有效期，之后可以单独修改某个码。

**invite_codes**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT PK | |
| batch_id | BIGINT FK→invite_batches | 所属批次 |
| code | VARCHAR(32) UNIQUE | 邀请码字符串 |
| created_by | BIGINT FK→users | 谁创建的（管理员/超管） |
| used_by | BIGINT FK→users NULL | 被谁使用，未用为 NULL |
| expires_at | DATETIME NULL | 过期时间，NULL 不过期 |
| used_at | DATETIME NULL | 使用时间 |
| created_at | DATETIME | |

> 一次性：注册成功即置 `used_by`/`used_at`，之后不可复用。判断「未使用」要求 `used_by` 与 `used_at` 都为 NULL：使用者被删除后 `used_by` 会被置空，但 `used_at` 保留，码仍不能再用。注册时对邀请码行加 `FOR UPDATE`，防止并发重复使用。邀请码为 12 位，每 4 位一组用短横线分隔（如 `K7QM-3XPD-9RWT`），只用大写字母和数字并去掉易混的 `0 O 1 I L`，生成与规范化在 `core/invite_code.py`；注册时输入不区分大小写、可不带短横线或夹空格，规范化后再查库；早期生成的 16 位大小写混合码原样匹配，仍可使用。

### 5.3 clipboard — 当前文本（每用户一条）

| 字段 | 类型 | 说明 |
|------|------|------|
| user_id | BIGINT PK / FK→users | 主键即 user_id，保证一人一条「当前文本」 |
| content | MEDIUMTEXT | 当前文本内容 |
| updated_at | DATETIME | 最后更新时间 |
| version | INT | 每次写入内容加 1，用于保存冲突检测（没有记录时接口返回 0） |
| access_code | VARCHAR(32) NULL | 快速访问码（小写），NULL 表示没有设置（见 5.8） |
| access_expires_at | DATETIME NULL | 访问码过期时间，NULL 不过期 |

> 该表为用户的「云剪切板」，每用户仅一条当前内容，写入采用 upsert。还没保存过内容就先设置访问码时，会建一条内容为空、version 为 0 的记录。

### 5.4 clipboard_history — 文本历史版本

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT PK | |
| user_id | BIGINT FK→users | 归属用户，查询按此过滤 |
| content | MEDIUMTEXT | 该版本文本内容 |
| created_at | DATETIME | 该版本产生时间 |

> 用户更新「当前文本」时，旧内容非空且与新内容不同才写入本表作为历史版本，供界面查看与恢复。恢复某条历史时，该条在同一事务里删除（它已成为当前文本）。索引 `user_id`。
> **保留策略**：每用户保留最近 `HISTORY_KEEP` 条（`.env`，默认 50；不能在后台修改），超出部分按时间自动清理最旧记录。
> 文本内容按 UTF-8 编码后不超过 8MB（8388608 字节），`ClipboardUpdate` 按字节数校验。列类型 MEDIUMTEXT 容量 16MB（迁移 `3f1c2a9d7b4e`）；应用层上限必须小于 Nginx 的 `client_max_body_size`（10m），否则超限请求在 Nginx 就被 413 拒绝。

### 5.5 texts — 文本栏目

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT PK | |
| user_id | BIGINT FK→users | 归属用户，查询按此过滤 |
| title | VARCHAR(100) | 标题，可为空字符串（入库前去掉首尾空白） |
| content | MEDIUMTEXT | 文本内容，上限与云剪切板相同（8MB） |
| version | INT | 每次保存加 1，用于保存冲突检测 |
| access_code / access_expires_at | VARCHAR(32) NULL / DATETIME NULL | 快速访问码与过期时间（见 5.8） |
| created_at / updated_at | DATETIME | 创建 / 最后保存时间 |

> 索引 `(user_id, access_code)`。每人最多 200 段（`api/texts.py` 的 `MAX_TEXTS_PER_USER`），没有历史版本。

### 5.6 files — 文件元数据

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT PK | |
| user_id | BIGINT FK→users | 归属用户，查询按此过滤 |
| original_name | VARCHAR(255) | 原始文件名（入库前去掉控制字符与路径分隔符） |
| stored_name | VARCHAR(255) | 磁盘存储名（UUID，防冲突/穿越；存储层强制校验为 UUID） |
| size | BIGINT | 字节数 |
| mime_type | VARCHAR(128) | MIME 类型 |
| created_at | DATETIME | 上传完成时间 |
| access_code / access_expires_at | VARCHAR(32) NULL / DATETIME NULL | 快速访问码与过期时间（见 5.8） |

> 索引 `user_id`、`(user_id, access_code)`。

### 5.7 upload_sessions — 分片上传临时状态

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

### 5.8 快速访问码（挂在内容上，没有单独的表）

访问码是 `clipboard`、`texts`、`files` 三张表上的 `access_code` + `access_expires_at` 两列：

- **每样内容最多一个访问码**，再设置一次就是修改；`access_code` 置 NULL 即清除。
- **访问码可以重复**：同一用户的多样内容可以用同一个码，凭这个码进入能看到它们全部；不同用户的同名码互不相干（完整访问码是「用户名@访问码」）。
- 格式：4–32 位字母、数字与 `_ - .`，不区分大小写，统一按小写存储；不校验复杂度。
- 内容删除时访问码随之消失；过期的访问码由定时任务 `cleanup_expired` 清空（内容保留）。
- **云剪切板访问码实时指向当前文本，不存快照**：属主更新文本后，访问码看到的内容随之更新。
- **不含访问计数、访问日志**：访问码定位为属主跨设备免登录取用的入口，非对外分发功能。

### 5.9 settings — 系统设置（key-value）

| 字段 | 类型 | 说明 |
|------|------|------|
| key | VARCHAR(64) PK | 设置项名 |
| value | TEXT | 设置值（字符串） |
| updated_at | DATETIME | 更新时间 |

目前使用三个 key：`registration_enabled`（`true`/`false`，缺省视为开放）、`show_github_link`（`true`/`false`，缺省视为显示；库里是其他值按关闭处理）与 `default_quota_bytes`（缺省、无法解析、为负数或超过 1TB 时回落 `.env` 的 `DEFAULT_QUOTA_BYTES`）。

> **外键无级联**：所有外键都没有 `ON DELETE CASCADE`。删除用户时由 `DELETE /api/admin/users/{id}` 按依赖顺序显式删除上传会话、文件、文本栏目、历史、当前文本（访问码挂在这些内容上，随之删除），处理其创建/使用过的邀请码，再删用户与磁盘目录。邀请码规则：该用户**使用过**的码保留记录、`used_by` 置空（`used_at` 保留，码仍不可复用）；该用户**创建的未使用**码直接删除；该用户创建的**已使用**码保留作审计，`created_by` 转记到执行删除的超管名下（`created_by` 为 NOT NULL，不改模型）。该用户创建的批次：码被删光的批次删除，还剩已使用码的批次同样转记到执行删除的超管名下，备注保留。删除前锁住被删用户行，与 `upload/init` 串行化，避免新建会话的 tmp 目录成为孤儿；磁盘清理失败只记日志，由定时清理的孤儿扫描兜底。

> **时间约定**：所有 DATETIME 列存 naive UTC；数据库会话时区固定 `+00:00`，代码统一用 `utcnow()`。

---

## 6. API 设计

除注册、登录、快速访问外，`/api/*` 都需 `Authorization: Bearer <token>`（登录凭证）。快速访问接口 `/api/access/*` 用快速访问凭证（见 6.5），两种凭证互不通用。缺少或无效 token 返回 401，用户被禁用返回 403 并带响应头 `X-Auth-Error: disabled`（前端据此与普通「权限不足」的 403 区分并登出）。健康检查为 `GET /`。

限流（slowapi，按客户端 IP，进程内存计数）：注册 5 次/分钟、登录 10 次/分钟、快速访问换取凭证 `POST /api/access/login` 30 次/分钟、其余 `/api/access/*` 每个接口 120 次/分钟。快速访问另有按用户名的输错锁定（第 8 节）。

### 6.1 认证 `api/auth.py`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | /api/auth/register | 公开 | 用户名（3–64 位，字母数字及 `_.-`）+ 密码（8 位以上、不超过 72 字节）+ 邀请码（不区分大小写，可不带短横线）；注册开关关闭时 403；先验邀请码（无效、已用、过期均 400），邀请码有效后才检查用户名是否被占用（400，邀请码不消耗），所以没有有效邀请码的人无法探测用户名是否存在；新用户配额取系统设置的默认配额；成功返回 201 与 JWT |
| POST | /api/auth/login | 公开 | 返回 JWT；用户不存在与密码错误返回同样的 401，耗时一致；密码正确但账号被禁用返回 403「用户已被禁用」 |
| GET | /api/auth/me | 登录 | 当前用户信息（含 role、配额、已用空间 `used_bytes`、上传中占用 `reserved_bytes`，以及站点显示开关 `show_github_link`：普通用户读不了 `/api/admin/settings`，前端靠它决定侧栏是否显示 GitHub 链接）；账号被禁用时 403 并带响应头 `X-Auth-Error: disabled` |

### 6.2 云剪切板 `api/clipboard.py`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | /api/clipboard | 登录 | 获取自己的当前文本（含 `version`、`access_code`、`access_expires_at`） |
| PUT | /api/clipboard | 登录 | 更新当前文本 `{content, base_version?}`（upsert），旧内容入历史，广播；`base_version` 与当前版本不一致返回 409，省略则直接覆盖 |
| GET | /api/clipboard/history | 登录 | 列出自己的全部文本历史版本（不分页，最多 `HISTORY_KEEP` 条）；不超过 64KB 的条目带全文 `content`，更长的 `content` 为 null、只给开头 `preview`，`size` 为 UTF-8 字节数 |
| GET | /api/clipboard/history/{id} | 归属 | 读取某条历史的全文（他人的与不存在的统一 404） |
| POST | /api/clipboard/history/{id}/restore | 归属 | 把某历史版本恢复为当前文本：该条历史随之删除，当前内容非空且与之不同时另存为一条新历史；广播 |
| DELETE | /api/clipboard/history/{id} | 归属 | 删除某条历史版本，广播 |

> 前端：点击历史条目只把内容填回编辑框（不保存，长条目先按 id 取全文）；「恢复」按钮调 restore，「删除」按钮调 delete。文本内容按 UTF-8 字节数校验，上限 8MB（8388608 字节）。

### 6.3 文本栏目 `api/texts.py`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | /api/texts | 登录 | 列出自己的全部文本 `{items, total, max_texts}`；不超过 64KB 的文本带全文 `content`，更长的 `content` 为 null，只给开头 200 字 `preview` 与字节数 `size` |
| POST | /api/texts | 登录 | 新建 `{title?, content?}`；已有 200 段返回 400；广播 `texts_changed` |
| GET | /api/texts/{id} | 归属 | 读取全文；他人文本与不存在统一 404 |
| PUT | /api/texts/{id} | 归属 | 保存 `{title?, content?, base_version?}`：省略的字段保持原值；版本不一致返回 409；广播 `texts_changed` |
| DELETE | /api/texts/{id} | 归属 | 删除（访问码随之消失），广播 `texts_changed`；带访问码的另广播 `access_codes_changed` |

### 6.4 文件 `api/files.py`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | /api/files | 登录 | 列出自己的文件（含 `access_code`、`access_expires_at`），并返回 `used_bytes`、`reserved_bytes`、`quota_bytes`（前端配额按 已用 + 上传中 计算） |
| POST | /api/files/upload/init | 登录 | 初始化分片上传 `{original_name, total_size, chunk_size}`，返回 `{upload_id, total_chunks, chunk_size}`（分片大小以返回值为准）；超过单文件上限或配额不足 413，分片数过多 400，进行中的会话过多 429 |
| POST | /api/files/upload/chunk | 登录 | 上传单个分片，multipart `{upload_id, chunk_index, chunk_data}`；分片过大 413、过小 400 |
| POST | /api/files/upload/complete | 登录 | 合并分片 `{upload_id}`，写记录，广播 `file_added`；流程与失败处理见第 10 节 |
| DELETE | /api/files/upload/{upload_id} | 归属 | 取消进行中的上传：删会话（立即释放配额）+ 清理 tmp；他人会话与不存在统一 404，正在合并返回 409 |
| GET | /api/files/{id}/download | 归属或 superadmin | 流式下载；无权限与不存在统一返回 404 |
| DELETE | /api/files/{id} | 归属 | 删文件记录（访问码随之消失）+ 磁盘，广播（superadmin 也不能删他人文件） |

### 6.5 快速访问码 `api/access.py`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| PUT | /api/access-codes | 登录 | 设置 / 修改 / 清除访问码 `{target_type: clipboard 或 text 或 file, target_id?, code（null 为清除）, expires_at?}`；text、file 必须带 `target_id`（否则 400），且只能是自己的（否则 404）；访问码格式不对 422；`expires_at` 必须晚于当前时间且不超过 8760 小时后（服务端多留 1 分钟余量，容忍前后端时钟误差）；广播 `access_codes_changed`，并通知凭旧码、新码进入的快速访问页 |
| GET | /api/access-codes | 登录 | 按访问码分组的总览 `{username, groups: [{code, items}], total}`，每项含类型、id、名称（文本标题或开头 / 文件名）、过期时间 |
| POST | /api/access/login | **公开** | `{full_code: "用户名@访问码"}` 换取快速访问凭证 `{access_token, token_type, owner_username, code, expires_in}`（2 小时）；格式不对 400；用户名不存在、码不对、已过期、属主被禁用统一 404；锁定中 429 |
| GET | /api/access/items | 快速访问 | 该访问码下的全部内容 `{owner_username, code, clipboard, texts, files}`；长文本只给开头 |
| GET / PUT | /api/access/clipboard | 快速访问 | 读取 / 修改云剪切板（剪切板须挂着这个码）；修改与登录编辑相同：旧内容进历史、`base_version` 冲突检测、广播 |
| GET / PUT | /api/access/texts/{id} | 快速访问 | 读取全文 / 修改标题与内容（请求体与 `PUT /api/texts/{id}` 相同；文本须属于属主且挂着这个码，否则 404） |
| GET | /api/access/files/{id}/download | 快速访问 | 流式下载（文件须挂着这个码）；磁盘文件丢失与内容被删提示相同 |

> 快速访问凭证是 `typ=qa` 的 JWT，`sub` 为属主、另带访问码；它只能用于 `/api/access/*` 与 `/ws`，登录接口拒绝带 `typ` 的 token，登录凭证也不能当快速访问凭证用。每次请求都回库确认属主未禁用、访问码下仍有未过期的内容，所以访问码被清除、修改、过期后凭证立即失效（返回 401）。快速访问没有新建、删除、上传、修改访问码的接口。
> 公开接口单独挂载在 `/api/access/*`，与需要登录的 `/api/access-codes` 是两个独立路由。

### 6.6 管理后台 `api/admin.py`

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | /api/admin/stats | admin+ | 系统统计（用户总数、活跃用户、文件总数、总存储、访问码总数、有效访问码数；访问码按「属主 + 访问码」去重计数，同一个码挂在多样内容上算一个；有效 = 至少有一样内容未过期且属主未被禁用，与快速访问的判定一致） |
| GET | /api/admin/users | admin+ | 用户列表，分页 `skip`/`limit`（≤100），含配额、已用空间、文件数 |
| GET | /api/admin/users/{id} | admin+ | 用户详情（元数据，含剪贴板更新时间，不含内容） |
| PATCH | /api/admin/users/{id}/quota | **superadmin** | 修改配额 `{quota_bytes}`（0 到 1TB），给目标用户广播 `quota_updated` |
| PATCH | /api/admin/users/{id}/status | **superadmin** | 启用/禁用 `{is_active}`；禁用时立即断开其 WebSocket；不能操作自己（400）或其他 superadmin（403） |
| DELETE | /api/admin/users/{id} | **superadmin** | 删除用户及其全部数据并断开其 WebSocket；不能删除自己（400）或其他 superadmin（403） |
| GET | /api/admin/invite-batches | admin+ | 邀请码批次列表 `{items, total}`，按生成时间倒序；每批含 `id, note, created_by, created_by_username, created_at, codes`，`codes` 按生成顺序列出该批全部邀请码（`id, code, used_by, used_by_username, expires_at, used_at`） |
| POST | /api/admin/invite-batches | admin+ | 生成一批邀请码 `{count?, expires_at?, note?}`：`count` 1–20（默认 1，超出 422），同一批共用 `expires_at` 与 `note`（去首尾空格，最多 100 字，超出 422），全部成功或全部不生成（与已有码重复时重新生成，重试仍冲突返回 500）；返回新批次，格式同列表项；`expires_at` 必须晚于当前时间，换算成 UTC 后超出可表示范围（如 `9999-12-31T23:59:59-05:00`）返回 400 |
| PATCH | /api/admin/invite-batches/{id} | admin+ | 修改批次备注 `{note}`（空字符串为清空，校验同上）；码已全部用掉的批次也能改；批次不存在 404；返回该批次 |
| DELETE | /api/admin/invite-batches/{id} | admin+ | 删除批次里所有未使用的码（含已过期未使用的），已使用的保留；批次里不剩码时批次一起删除；行锁与注册互斥；返回 `{deleted, batch_deleted}`；批次不存在 404 |
| PATCH | /api/admin/invite-codes/expiry | admin+ | 批量修改有效期 `{ids, expires_at}`（`ids` 1–500 个，`expires_at` 为 null 表示永久有效，校验同上）；只能改未使用的码（已过期未使用的可续期）；任何一个 id 不存在返回 404、已使用返回 409，整批不改；行锁与注册互斥；返回 `{updated, expires_at}` |
| DELETE | /api/admin/invite-codes/{id} | admin+ | 删除单个未使用的邀请码；已使用的保留作审计记录，返回 409；所属批次删空时一起删除 |
| GET | /api/admin/files | admin+ | 全站文件**元数据**，分页（无下载入口） |
| GET | /api/admin/settings | admin+ | 读取系统设置 `{default_quota_bytes, registration_enabled, show_github_link}` |
| PATCH | /api/admin/settings | **superadmin** | 修改上述设置，字段都可选，只改传入的（默认配额 0 到 1TB） |

**未实现**：直接创建用户、重置密码、变更角色、全站访问码管理。

> **隐私红线**：`/api/admin/files` 只返回元数据（属主、文件名、大小、MIME 类型、时间），**不提供 admin 下载入口**；文件内容下载统一走 `/api/files/{id}/download`，该接口仅放行归属者与 superadmin。

---

## 7. 实时同步机制

### 连接管理器（core/ws_manager.py）

维护两张表：`dict[user_id, set[WebSocket]]` 存登录终端的连接（同一用户多终端在线时集合里有多条）；`dict[属主 user_id, dict[WebSocket, 访问码]]` 存快速访问页的连接。

- **连接**：`/ws`，token 经子协议 `Sec-WebSocket-Protocol: clipsync.v1, bearer.<JWT>` 传递（不放 URL，避免进 access log）→ 校验签名、过期、用户存在且未禁用 → 服务端只回选 `clipsync.v1` → 加入集合。
- **握手被拒**：token 无效、用户不存在或被禁用时，服务端在 accept 之前关闭连接，浏览器只能看到 **1006**（与服务器不可达无法区分）。
- **快速访问连接**：用快速访问凭证连接，握手时同样校验访问码有效；只接收 `access_items_changed`（该访问码下的内容有变化），不接收属主的其他推送。访问码被清除 / 修改或其下内容删光时服务端以 1008 断开；不经过接口的变化（定时清理清掉过期码、凭证到期）在下一次心跳时发现并断开。
- **踢下线**：已连接的用户被禁用或删除时，服务端以 **1008** 主动关闭其全部连接（含凭其访问码进入的快速访问页）；每个连接最多等 5 秒，网络卡住的终端不会拖住禁用 / 删除请求。
- **单进程**：连接表与限流计数都在进程内存中，后端必须单 worker 运行。
- **断开**：从集合移除，空则删 key。
- **广播**：`broadcast_to_user(user_id, message)`，发给该用户的**全部连接（含触发变更的终端）**，并发发送，单个连接超时 5 秒；发送失败或超时的连接会被移出集合并由服务端关闭（关闭后前端重连并补拉；只移出不关闭的话，接收循环仍会回心跳，客户端不会察觉连接已失效）。网络卡住的终端不会拖慢触发广播的 HTTP 请求。

### 事件类型

消息只携带轻量信号，不含正文：

```json
{ "type": "clipboard_updated", "data": { "updated_at": "..." } }
{ "type": "texts_changed", "data": { "id": 1 } }
{ "type": "file_added",   "data": { "id": 1, "original_name": "...", "size": 123 } }
{ "type": "file_deleted", "data": { "id": 1 } }
{ "type": "access_codes_changed", "data": {} }
{ "type": "quota_updated", "data": { "quota_bytes": 104857600 } }
{ "type": "access_items_changed", "data": {} }   // 只发给快速访问页
```

| 事件 | 触发 | 前端处理 |
|------|------|----------|
| `clipboard_updated` | 保存（含快速访问修改）/ 恢复历史 / 删除历史（删除历史时 `data` 为空） | 云剪切板页静默重拉当前文本；历史面板打开时一并重拉历史（按请求序号丢弃过期结果） |
| `texts_changed` | 新建 / 保存（含快速访问修改）/ 删除文本 | 文本页静默重拉列表；访问码页重拉总览 |
| `file_added` / `file_deleted` | 上传完成 / 删除文件 | 文件页静默重拉列表；访问码页在 `file_deleted` 时重拉总览；布局（`Home.vue`）刷新侧栏配额 |
| `access_codes_changed` | 设置 / 修改 / 清除访问码，删除带访问码的文本或文件 | 访问码页重拉总览；云剪切板、文本、文件页重拉以显示最新的访问码 |
| `access_items_changed` | 快速访问页所用访问码下的内容被修改、增删，或访问码被改动 | 快速访问页静默重拉内容 |
| `quota_updated` | 超管修改该用户配额 | 布局刷新侧栏配额 |

- 页面级监听在挂载时注册、卸载时清理；各页面同时订阅 `open`，连接（重新）建立后补拉一次，断线期间的变更不会漏掉。
- 心跳：客户端每 30 秒发 `{"type":"ping"}`，服务端回 `{"type":"pong"}`；单条消息超过 1024 个字符时服务端以 1009 断开。心跳只在连接打开时发送，离线时不排队。客户端发出 ping 后 10 秒内没收到任何消息，就认为连接已半断并重建。
- 前端重连：指数退避（1s、2s、4s…，最长 30s），不限次数；网络恢复（`online`）或页面回到前台时立即重试（已断开的直接重连；看起来仍连着的先探测一次，没有回应就重建）。收到 1008 时停止重连并登出。连接从未打开就关闭（多为握手被拒的 1006）时，前端调一次 `/api/auth/me` 确认会话：401 / 禁用 403 则登出、不再重连，其他情况继续退避重连。登出时主动断开，不会自动重连。
- 重连只使用本标签页内存中的 token，不读 localStorage；其他标签页换账号改写 localStorage 时，本页整页重载。
- 快速访问页用单独的 WebSocket 实例（`stores/quick.js` 的 `quickWs`），重连规则相同；收到 1008 时提示访问码已失效。

### WebSocket 协议自适应（HTTP/HTTPS 通用）

前端不写死协议，根据当前页面协议自动选择，两套部署都无需改代码：

```js
const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
const ws = new WebSocket(`${proto}//${location.host}/ws`, ['clipsync.v1', `bearer.${token}`])
```

---

## 8. 快速访问码机制

> 定位：**供属主本人跨设备免登录取用自己内容的入口**，非对外分发功能。因此不设访问次数、访问日志等分发控制。

### 设置

登录用户在云剪切板、文本、文件页面的条目旁点「访问码」，调用 `PUT /api/access-codes` 设置、修改或清除（数据结构见 5.8）。可选有效期，最长 8760 小时（1 年），前后端都校验。访问码页按访问码分组显示总览，可逐项清除。

### 进入（免登录）

1. 在登录页的「快速访问码」输入框输入 `用户名@访问码`（用户名不含 `@`，按 `@` 拆分没有歧义；访问码不区分大小写）。
2. `POST /api/access/login` 校验通过后返回 2 小时的快速访问凭证，前端存在 sessionStorage（刷新页面仍在，关掉标签页即失效），跳到 `/quick`。
3. 快速访问页列出该访问码下的云剪切板、文本、文件：文本可查看与修改（含标题），文件可下载；不能新建、删除、上传，也不能设置或修改访问码。
4. 用访问码修改云剪切板时，旧内容同样进历史；保存都带版本号，内容已在别处改过时返回 409，页面让用户选择「载入最新内容」或「仍然覆盖」（登录编辑同样如此）。
5. 页面经 WebSocket 实时刷新；访问码失效时提示并禁止保存与下载，未保存的内容留在页面上可以先复制。

### 失效

- 访问码被清除或修改、过期、其下内容全部删除、属主被禁用、凭证满 2 小时，都会使快速访问失效。每个请求都回库校验，失效后接口立即返回 401。
- WebSocket：经接口发生的变化（清除、修改访问码，删除内容，禁用属主）立即断开连接；访问码过期、凭证满 2 小时不经过接口，在下一次心跳（最多约 30 秒）时发现并断开。
- 定时任务 `cleanup_expired` 每小时把过期的访问码清空（内容保留），访问码总览里随之消失。
- 属主被禁用只是暂时失效：重新启用后，访问码未过期的可以重新进入。
- 进入时的各种失败（用户名不存在、码不对、已过期、属主被禁用）统一返回 404「访问码无效或已失效」，不暴露用户名或访问码是否存在；格式不对（缺 `@` 等）返回 400，锁定期间返回 429。

### 安全考量

- 访问码由用户自定，不校验复杂度（太复杂就不「快速」了），只校验长度与字符。防猜测靠两层：
  - **按用户锁定**：同一用户连续输错 10 次，暂停其快速访问 15 分钟（锁定期间输对也不放行）；输对一次清零。数据库比较用户名时忽略大小写、重音和零宽字符，计数按查到的用户归并，换一种写法不能重新计数。不存在的用户名按小写用户名计数，响应一致。账号密码登录不受影响。代价是别人故意输错可以让某个用户名的快速访问暂时不可用。计数在进程内存中，后端重启后清零。
  - **按 IP 限流**：换取凭证 30 次/分钟/IP；持有凭证后的读写、下载接口每个 120 次/分钟/IP。
- 快速访问凭证与登录凭证互不通用，见 6.5。
- 免登录接口同样防路径穿越（文件按 file_id 查库拿 stored_name），所有查询都限定「属主 + 访问码」。
- 界面提示：知道完整访问码的人无需登录就能查看和修改其中的文本、下载其中的文件，应妥善保管；敏感内容可设置过期时间或及时清除。

---

## 9. 管理后台面板

面向 admin / superadmin 的前端区域：`/admin` 路由，单个页面 `views/Admin.vue`，路由守卫校验 role。

### 页面结构（5 个 tab）

```
/admin
├── 概览      # 用户总数、活跃用户、文件总数、总存储、访问码总数、有效访问码（口径见 6.6 的 stats）
├── 用户      # 分页列表；改配额 / 启用禁用 / 删除 按钮仅超管可见（superadmin 行不显示禁用、删除）
├── 邀请码    # 生成一批（数量 1–20 + 有效天数，0 为永久，可点 7 天 / 14 天 / 30 天 / 90 天 / 半年 / 一年 / 永久快捷填入 + 选填备注）→ 生成结果页（复制邀请码 / 复制邀请信息）；
│             #   按批次列出：备注、生成时间、生成人、个数、有效期概要、可用 / 已过期 / 已使用各几个，只有 1 个码的批次直接显示码；
│             #   每批可复制邀请信息（只含可用的码）、改备注、删除其中未使用的码；点开看每个码：状态、使用者、复制、
│             #   修改有效期（单个或勾选批量，可跨批次）、删除；已使用的不能勾选、改有效期或删除；
│             #   搜索（备注、生成人、邀请码，邀请码不分大小写、可不带短横线，命中的批次自动展开并高亮该码）
│             #   与状态筛选（全部 / 有可用的 / 有已过期的 / 已用完，按批次判断），都在前端完成
├── 文件      # 全站文件【元数据】分页列表（admin 与 superadmin 均可见，无下载入口）
└── 设置      # 开放注册、显示 GitHub 链接、新用户默认配额：admin 只读，superadmin 可保存
```

**未实现**：全站访问码管理、超管在后台直接下载他人文件的入口（超管可调 `/api/files/{id}/download`）。

### 系统设置（存 DB，可热更新）

后台可修改的只有三项（通过 `PATCH /api/admin/settings`，仅超管）：

- 是否开放注册（`registration_enabled`）
- 是否在登录后的侧栏底部显示项目的 GitHub 链接（`show_github_link`，默认显示）：一行灰色小字，链接地址写在前端 `Home.vue` 里，不可配置；开关值随 `GET /api/auth/me` 下发给所有登录用户，用户刷新页面或重新登录后生效，超管在后台保存后本页侧栏立即更新
- 新用户默认配额（`default_quota_bytes`，默认 100MB）

单文件上限、分片大小、历史保留条数、上传会话过期时间、每用户并发上传会话数都只能在 `.env` 里配置，改后需重启后端。邀请码没有「默认有效期」设置，由前端按填写的天数换算成 `expires_at`（生成与修改有效期都从操作的这一刻开始算）。

### 邀请信息

生成结果页的「复制邀请信息」复制一段可以直接发出去的文字，格式写在 `Admin.vue` 的 `buildInviteMessage`：标题 `ClipSync · 注册邀请`，标签统一三个字（邀请码、有效期），只用空行分组，不加装饰符号。只有一个码时末行是带 `?code=` 的注册链接，注册页打开后自动填好邀请码；多个码时逐行列出，末行是不带码的注册链接。链接取打开管理页时浏览器里的地址（`window.location.origin`），用局域网地址打开管理页时复制出的也是局域网地址。「复制邀请码」只复制码，每行一个。批次列表里的「复制邀请信息」用同一个格式，但只放这批里还能用的码（已使用、已过期的不放）；这些码的有效期各不相同时，有效期一行写最早的那个。

### 前端角色控制

- 路由守卫：非 admin/superadmin 访问 `/admin` 直接重定向。
- 组件级：用户管理的修改按钮仅当 `role === 'superadmin'` 时渲染。
- **后端才是权限的最终防线**，前端隐藏只是体验层，所有接口都做服务端角色校验。

---

## 10. 文件分片上传方案

单文件可达上百 MB，必须分片。

```
1. init     → POST /api/files/upload/init  JSON {original_name, total_size, chunk_size}
              校验单文件上限（413）→ 定分片大小：取请求值，不超过 CHUNK_SIZE，
              且分片总数不超过 10000（过小时自动调大，仍超出返回 400）
              → 清理本用户过期会话 → 锁用户行，校验并发会话数（429）、配额（413）
              → 先建 tmp/{upload_id} 目录，再写 upload_session 行并提交（顺序不能反：建目录失败时不会留下客户端拿不到
                 upload_id、无法取消的会话；提交失败时删掉刚建的目录）
              → 返回 {upload_id, total_chunks, chunk_size}（以服务端返回为准）
2. chunk×N  → POST /api/files/upload/chunk  multipart {upload_id, chunk_index, chunk_data}
              校验归属、会话未过期、chunk_index < total_chunks
              每片大小必须等于期望值：非最后一片 = chunk_size，最后一片 = 剩余字节；超出 413，不足 400
              线程池中写 tmp/{upload_id}/{index}.<随机>.part，完成后原子替换为 {index}
              失败可重传该片（断点续传）；同一片并发重传不会互相截断
3. complete → POST /api/files/upload/complete  JSON {upload_id}
              同一 upload_id 并发 complete 返回 409；会话过期返回 404
              校验分片 0..N-1 齐全 → 先提交结束事务（合并耗时长，期间不占着数据库连接）
              → 线程池中按序流式合并到 storage/{user_id}/{uuid}
              实际大小必须等于 total_size → 按实际大小再校验配额
              写 files 记录 → 删会话与 tmp → 广播 file_added
              失败处理：
                · 合并出错（磁盘写满等，500）、实际大小不符或配额不足（413）：删除已合并的文件、会话与分片，不能重试
                · 写记录时的意外失败（数据库死锁、连接断开、用户被并发删除）：删除已合并的文件，
                  会话行与分片保留，可以再次 complete，不留不计配额的孤儿文件
```

- 分片大小：前端请求 1MB，服务端上限 `CHUNK_SIZE`（`.env`，默认 5MB），不能在后台修改。
- 配额：已用 = 已落盘文件 + **进行中会话的声明大小**，防止并发开会话超配；init 预校验，complete 按实际大小最终确认。
- 取消：上传中途任何一步失败（含 complete）时，前端不重试，直接调 `DELETE /api/files/upload/{upload_id}` 立即释放配额；关掉页面等无法取消的会话，靠 `/auth/me` 与 `GET /api/files` 返回的 `reserved_bytes`（侧栏显示「上传中」）让用户看见，并在 TTL 后清理。
- 每用户进行中的上传会话不超过 `MAX_UPLOAD_SESSIONS_PER_USER`（默认 5），超出返回 429。
- 会话过期：超过 `UPLOAD_SESSION_TTL_HOURS`（默认 24）的会话，在该用户下次 init 时清理；定时任务 `backend/scripts/cleanup_expired.py`（宿主机 cron 经 `docker compose exec` 每小时执行）清理全站过期会话与 tmp 目录，并做孤儿扫描（超过 TTL 且无会话记录的 tmp 目录、用户已不存在的 `storage/<uid>` 目录；删用户目录前会针对该 id 再查一次 users 表，扫描期间新注册的用户不会被误删）。
- 下载：线程池中先打开文件再 `fstat` 取大小，下载途中文件被删也能读完；文件不存在返回 404（快速访问路径与内容被删时提示相同）。
- `upload_id` 必须是服务端生成的标准小写 UUID：chunk、complete 的 `upload_id` 长度不是 36 时参数校验返回 422；长度对但写法不同（含大写）以及 DELETE 路径里的任何其他写法，一律按「会话不存在」返回 404。
- 应用内磁盘删除失败只记日志（`rmtree` 用 `onexc` 回调），不影响接口结果。残留的目录（临时分片目录、已删用户的目录）由孤儿扫描兜底；删除单个文件失败时，磁盘上会留下没有记录的文件，孤儿扫描不处理（见 TODO.md）。
- 写分片遇到磁盘写满等 IO 错误时，半截的 `.part` 文件会被删除。
- 合并与下载都流式处理，不一次性读入内存。

---

## 11. HTTP / HTTPS 切换

可以先以 HTTP 部署，日后切到 HTTPS。设计目标：**切换只动 Nginx 配置与 `.env` 开关，应用代码零改动**。

### 保障平滑切换的三项设计

1. **前端不写死协议**
   - API 走相对路径（`/api/...`），跟随页面协议。
   - WebSocket 按 `window.location.protocol` 自动选 `ws://`/`wss://`（见第 7 节）。

2. **Nginx 配置可替换**：frontend 容器的 Nginx 默认读取挂载进去的 `deployment/docker/nginx-docker.conf`（HTTP，监听 80）。切换 HTTPS 时在 `.env` 设 `COMPOSE_FILE=docker-compose.yml:docker-compose.https.yml`，叠加的 compose 文件映射 443 并改挂 `nginx-https.conf`：80 端口只保留证书验证，其余请求 301 跳转到 HTTPS。两份站点配置都 include 公共规则 `nginx-common.conf`。步骤见 [deployment/DEPLOYMENT.md](deployment/DEPLOYMENT.md)「使用 HTTPS」。

3. **环境开关**（`.env`）：

   | 变量 | HTTP 阶段 | HTTPS 阶段 | 作用 |
   |------|:---:|:---:|------|
   | `HSTS_ENABLED` | false | true | 由**后端中间件**下发 `Strict-Transport-Security`（HTTP 阶段不能开） |
   | `CORS_ORIGINS` | `http://` 访问地址 | `https://` 访问地址 | 允许来源白名单，逗号分隔，忽略 `*` |

### 阶段说明与提示

- **HTTP 阶段的风险**：密码、JWT、文本、文件明文传输，网络链路上的任何一方都能看到。HTTP 只适合测试或可信内网；正式使用，尤其是暴露在公网时，应切换 HTTPS（第 17 节也有提示）。
- Token 采用 `Authorization` header + 前端 localStorage，HTTP/HTTPS 行为一致，不依赖 cookie，切换协议无需改动应用代码。
- 升级 HTTPS 时：用 `cert.sh` 申请 Let's Encrypt 证书 → `.env` 设 `COMPOSE_FILE` 叠加 HTTPS 配置、改 `CORS_ORIGINS` → 重建 frontend、backend 容器 → HTTPS 稳定后再开 `HSTS_ENABLED`。无需改动数据库或应用逻辑。

---

## 12. 安全设计

| 项 | 措施 |
|----|------|
| 传输加密 | HTTP（测试 / 可信内网）与 HTTPS（正式使用）可切换，HTTP 下全部内容明文传输（第 11、17 节）。 |
| 密码存储 | bcrypt 哈希，绝不存明文，不在日志/响应回显。 |
| 认证 | JWT，必须带 `exp`（默认 7 天），只允许 HS 系列算法；`JWT_SECRET` 少于 32 位或为示例值时后端拒绝启动；每次请求回库校验用户存在且未禁用。 |
| 角色权限 | 三级角色后端强制校验；admin 看不到文件/文本内容，仅 superadmin 可绕过。 |
| 登录爆破 | 注册、登录、快速访问接口限流（数值见第 6 节开头）；登录在用户不存在时也执行一次 bcrypt，防时序枚举。限流按真实客户端 IP，依赖 uvicorn `--proxy-headers` 信任反代传来的 `X-Forwarded-For`。 |
| 数据隔离 | 隐私查询强制 `WHERE user_id = current_user`，仅 superadmin 例外。 |
| 越权访问 | 读写、下载、删除、设置访问码前先校验归属；快速访问的查询限定「属主 + 访问码」，不信任客户端传入路径。 |
| 路径穿越 | 磁盘名用 UUID，绝不用用户文件名拼路径。 |
| 访问码 | 用户自定、不校验复杂度；按用户名输错锁定 + 按 IP 限流 + 可设过期 + 可随时清除且立即生效；快速访问凭证与登录凭证互不通用；前端提示用户妥善保管（第 8 节）。 |
| 上传限制 | Nginx `client_max_body_size`；后端校验单文件上限、单分片字节数、并发会话数与配额。 |
| 响应头 | 下载用 RFC 6266 编码的 `Content-Disposition`，防头注入；全局下发 `X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Referrer-Policy: no-referrer`（接口由后端下发，静态页由 Nginx 下发）；`HSTS_ENABLED=true` 时后端另下发 `Strict-Transport-Security: max-age=31536000; includeSubDomains`；Nginx `server_tokens off` 不暴露版本号。 |
| WebSocket | token 走子协议头不进 URL；禁用/删除用户时主动断开其连接；快速访问连接只收相关信号，访问码失效即断开。 |
| 错误信息 | 不把底层异常细节（路径等）返回客户端。 |
| 邀请码 | 一次性、可过期、仅管理员生成；12 位去易混字符（约 7.9×10^17 种组合），注册接口限流。 |
| CORS | 按 `.env` 的 `CORS_ORIGINS` 限定，不用通配。 |

---

## 13. 目录结构

```
CodeProject/
└── clipsync/                     # ← 本项目根目录
    ├── README.md                 # 本文档（项目说明与设计）
    ├── TODO.md                   # 尚未完成的事项
    ├── CLAUDE.md                 # 编码硬约束
    ├── .gitignore
    ├── dev-start.bat             # 双击启动开发环境（调用 dev-start.ps1）
    ├── dev-start.ps1             # 启动开发库容器 → 升级表结构 → 后端、前端各开一个窗口 → 打开浏览器
    ├── backend/
    │   ├── app/
    │   │   ├── main.py           # FastAPI 入口，挂载路由、CORS、安全响应头
    │   │   ├── config.py         # 读取 .env，校验 JWT_SECRET 强度与 JWT_ALGORITHM
    │   │   ├── database.py       # 异步 engine / session 工厂（会话时区 UTC）
    │   │   ├── rate_limit.py     # slowapi 限流器
    │   │   ├── models/           # user / invite / clipboard / text / file / setting
    │   │   ├── schemas/          # Pydantic 请求/响应模型
    │   │   ├── core/
    │   │   │   ├── security.py     # 密码哈希 + JWT
    │   │   │   ├── invite_code.py  # 邀请码格式：生成 + 注册时输入规范化
    │   │   │   ├── deps.py         # 依赖注入：当前用户 / 角色校验
    │   │   │   ├── ws_manager.py   # WebSocket 连接管理器（登录终端 + 快速访问页）
    │   │   │   ├── quick_access.py # 访问码格式、输错锁定、快速访问凭证、通知快速访问页
    │   │   │   ├── storage.py      # 磁盘路径（UUID 校验 + 根目录约束）
    │   │   │   ├── http_utils.py   # 文件名清洗 + Content-Disposition
    │   │   │   ├── app_settings.py # 读 settings 表
    │   │   │   └── timeutil.py     # UTC 时间工具
    │   │   └── api/              # auth / clipboard / texts / files / access / admin / ws
    │   ├── alembic/
    │   │   ├── env.py            # 迁移入口：连接串取自 app/config.py
    │   │   ├── script.py.mako    # 新迁移文件的模板
    │   │   └── versions/         # 278c88a5f21f 初始表结构；3f1c2a9d7b4e 文本改 MEDIUMTEXT；7c2d4e6f8a1b 访问码挂到内容上、新增 texts；9e3b5d7f1a2c 邀请码批次（已有的码按创建人 + 创建时间归批）
    │   ├── alembic.ini
    │   ├── scripts/              # create_superadmin.py / cleanup_expired.py（定时清理，由宿主机 cron 经 docker compose exec 调用）
    │   ├── tests/                # pytest 用例：安全边界、并发、实时推送、上传下载等（使用独立库 clipsync_test）
    │   ├── pytest.ini
    │   ├── requirements.txt      # 运行依赖（生产镜像只装这个）
    │   ├── requirements-dev.txt  # 运行依赖 + pytest、httpx 测试依赖
    │   ├── .env.example
    │   ├── .dockerignore         # 构建镜像时排除 .env、虚拟环境、测试与上传数据
    │   └── storage/              # 上传文件落盘（STORAGE_DIR 默认 ./storage，相对启动后端时的当前目录，按文档在 backend/ 下启动；已 gitignore）
    │       ├── <user_id>/<uuid>
    │       └── tmp/<upload_id>/<chunk_index>
    ├── frontend/
    │   ├── src/
    │   │   ├── main.js
    │   │   ├── App.vue
    │   │   ├── style.css         # 设计变量与全局组件样式
    │   │   ├── router/index.js   # 路由 + 登录/角色守卫
    │   │   ├── api/              # request.js / quickRequest.js(axios 封装) + auth/clipboard/texts/files/access/quick/admin，index.js 汇总导出
    │   │   ├── stores/           # user / clipboard / texts / files / access / quick / admin，index.js 汇总导出
    │   │   ├── utils/
    │   │   │   ├── websocket.js    # WS 客户端（协议自适应、重连、心跳）
    │   │   │   ├── clipboard.js    # 复制到剪贴板（HTTP 下降级为 execCommand）
    │   │   │   ├── format.js       # 文件大小、UTC 时间解析与格式化、相对时间
    │   │   │   ├── toast.js        # 轻提示
    │   │   │   ├── dialog.js       # 确认 / 输入 / 手动复制 / 多选一对话框
    │   │   │   ├── conflict.js     # 保存冲突时的选择对话框
    │   │   │   ├── textDrafts.js   # 多段文本的编辑草稿（文本页与快速访问页共用）
    │   │   │   ├── accessCode.js   # 访问码规则与过期判断
    │   │   │   ├── theme.js        # 主题（跟随系统 / 浅色 / 深色，记在本浏览器）
    │   │   │   ├── glass.js        # 玻璃质感（液态折射的启用判断、悬停高光跟随鼠标）
    │   │   │   └── download.js     # Blob 交给浏览器保存
    │   │   ├── components/       # AuthLayout / BrandMark / ThemeToggle / ToastHost / DialogHost / TextEditorCard / AccessCodeButton / AccessCodeDialog / LoadingSkeleton
    │   │   └── views/
    │   │       ├── Login.vue / Register.vue
    │   │       ├── Home.vue          # 登录后布局（侧边栏）
    │   │       ├── Clipboard.vue     # 云剪切板 + 历史
    │   │       ├── Texts.vue         # 文本栏目
    │   │       ├── Files.vue         # 文件
    │   │       ├── AccessCodes.vue   # 访问码总览
    │   │       ├── Admin.vue         # 管理后台（5 个 tab）
    │   │       └── QuickAccess.vue   # 凭「用户名@访问码」免登录进入 /quick
    │   ├── public/               # favicon.svg
    │   ├── index.html
    │   ├── README.md             # 前端说明
    │   ├── package.json / package-lock.json
    │   ├── .gitignore
    │   ├── .dockerignore         # 构建镜像时排除 node_modules、dist
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

只支持 Docker Compose 部署，完整步骤见 [deployment/DEPLOYMENT.md](deployment/DEPLOYMENT.md)。服务器只需要 x86_64 Linux + Docker，发行版不限。

### 组件（`deployment/docker/docker-compose.yml`，项目名固定为 `clipsync`）

| 服务 | 镜像 | 说明 |
|------|------|------|
| db | `mysql:8.4.x`（版本号固定在 compose 中） | 数据卷 `clipsync_mysql_data`；端口只绑定宿主机 `127.0.0.1`（宿主机端口 `DB_HOST_PORT`，默认 3306），供宿主机与 SSH 隧道查询 |
| backend | `clipsync-backend`（`Dockerfile.backend`） | 启动时先 `alembic upgrade head`，再以**单 worker** 运行 uvicorn；非 root 用户；数据卷 `clipsync_storage_data` → `/app/storage`；不对宿主机暴露端口 |
| frontend | `clipsync-frontend`（`Dockerfile.frontend`） | Nginx 托管 Vue 构建产物，反代 `/api`、`/ws` 到 backend；宿主机端口 `HTTP_PORT`（默认 80），HTTPS 时另映射 443 |

- **必须单 worker**：WebSocket 连接表与限流计数都在进程内存中，多进程会导致实时同步与限流失效。
- **真实客户端 IP**：compose 使用固定子网 `172.28.0.0/16`，uvicorn 只信任这个网段发来的 `X-Forwarded-For`；Nginx 用 `$remote_addr` 覆盖该头，客户端自带的值一律丢弃。
- **镜像来源**：默认在开发机用 `build-release.ps1` 构建并打包，服务器 `docker load` 导入后启动，不需要联网下载；网络通畅的服务器也可叠加 `docker-compose.build.yml` 从源码构建。backend、frontend 设 `pull_policy: never`，不会从镜像仓库拉取同名镜像。
- **版本标签**：镜像带 git 提交号标签；只有 master 上的提交额外标 `latest`。测试通过的构建由 `publish-release.ps1` 追加版本号标签（如 `1.0.0-alpha.1`）生成发布包，镜像不重新构建。服务器按 `.env` 的 `CLIPSYNC_TAG` 选用镜像。
- **定时任务**：宿主机 cron 每小时经 `docker compose exec` 执行 `scripts.cleanup_expired`，每天执行 `backup.sh` 备份数据库与上传文件、执行 `cert.sh renew` 检查证书续期（模板 `clipsync.cron`）。

### Nginx 关注点（`nginx-docker.conf` / `nginx-https.conf`，公共部分在 `nginx-common.conf`）

- `proxy_pass` 用变量 + `resolver 127.0.0.11`：backend 容器重建后 IP 会变，Nginx 运行时重新解析。
- `location /ws` 需 `Upgrade`/`Connection` 头支持 WebSocket。
- `client_max_body_size` 略大于单个分片大小（`CHUNK_SIZE` 默认 5MB，Nginx 限 10MB），同时大于剪贴板文本上限（8MB，云剪切板与文本栏目相同；请求体含 JSON 外壳与转义，需要留余量）。
- `/api` 反代加超时设置适配上传；`Host` 用 `$http_host`（保留端口）。
- 前端页面（含快速访问页 `/quick`）是 SPA 路由，由 `try_files` 回落到 `index.html`。
- 静态页面由 Nginx 加 `X-Frame-Options`、`X-Content-Type-Options`、`Referrer-Policy`；`index.html` 不缓存，带哈希的 `/assets/` 长期缓存；`/api` 的安全头由后端下发。
- `/.well-known/acme-challenge/` 指向挂载的 `acme/` 目录，供 certbot 以 webroot 方式申请与续期证书。
- HTTPS 配置额外含证书路径、80→443 跳转。**HSTS 只由后端按 `HSTS_ENABLED` 下发**，Nginx 不配置。

---

## 15. 功能模块与实现范围

| 模块 | 已实现 | 未实现 |
|------|------|------|
| 基础 | 配置（含 HTTP/HTTPS 开关）、异步数据库、数据模型、Alembic 迁移 | — |
| 认证与角色 | 邀请码注册、登录、JWT、三级角色校验、存储配额 | 直接创建用户、重置密码、变更角色 |
| 云剪切板 | 当前文本读写（冲突检测）、历史查看 / 恢复 / 删除、WebSocket 广播 | — |
| 文本栏目 | 多段文本新建 / 编辑 / 删除（冲突检测，长文本按需载入）、WebSocket 广播 | 文本历史版本 |
| 文件 | 分片上传（配额校验、取消）、流式下载、删除、越权与路径穿越防护 | 前端断点续传 |
| 快速访问码 | 自定访问码设置 / 修改 / 清除、按访问码总览、「用户名@访问码」免登录进入（改文本 / 下载文件）、实时刷新、输错锁定与限流 | — |
| 管理后台 | 概览统计、用户管理（配额 / 启用禁用 / 删除）、邀请码、全站文件元数据、系统设置 | 变更角色、全站访问码管理 |
| 前端 | 登录 / 注册（含快速访问入口）、云剪切板、文本、文件、访问码、管理后台、快速访问页、路由守卫、WebSocket 接入、浅色 / 深色主题 | 自动化测试 |
| 部署 | Docker Compose（开发机构建离线导入 / 服务器源码构建）、HTTP / HTTPS Nginx 配置、Let's Encrypt 证书申请与续期、备份 / 清理 / 健康检查脚本 | 不使用 Docker 的直接部署（不支持） |

未实现与待验证的事项汇总在 [TODO.md](TODO.md)。

---

## 16. 开发环境快速开始

先决条件：Python 3.12+、Node.js 20.19+ 或 22.12+（Vite 8 的要求）、Docker Desktop（开发库用 MySQL 8.4 容器，与部署环境一致）。

### 1. 创建数据库

开发库是名为 `clipsync-dev-mysql` 的容器，下文的一键启动 `dev-start` 按这个名字启动它，找不到就退出。创建容器并建库，然后在 `backend/.env` 里设 `DB_HOST=127.0.0.1`、`DB_PORT=3307`、`DB_USER=root`、`DB_PASSWORD=<开发库密码>`：

```bash
docker run -d --name clipsync-dev-mysql -p 127.0.0.1:3307:3306 \
    -v clipsync_dev_mysql:/var/lib/mysql -e MYSQL_ROOT_PASSWORD=<开发库密码> mysql:8.4.11
# 等容器初始化完成（约半分钟），在容器里建库，按提示输入开发库密码
docker exec -it clipsync-dev-mysql mysql -uroot -p \
    -e "CREATE DATABASE clipsync CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
```

排序规则与部署环境一致：docker compose 由 `MYSQL_DATABASE` 自动建库，用 MySQL 8.4 的服务器默认规则 `utf8mb4_0900_ai_ci`。该规则不区分大小写与重音，行尾空格有意义（`utf8mb4_unicode_ci` 会忽略行尾空格）。测试库 `clipsync_test` 同样用这个规则。

### 2. 后端

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt   # 运行依赖 + 测试依赖（生产镜像只装 requirements.txt）

cp .env.example .env                 # Windows 的 cmd 用 copy
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

### 日常启动（Windows）

完成以上一次性准备后，日常双击项目根目录的 `dev-start.bat` 即可（实际步骤在 `dev-start.ps1`）：

1. Docker 未运行时打开 Docker Desktop 并等待就绪
2. 启动 `clipsync-dev-mysql` 容器，等到可连接
3. `alembic upgrade head`（已是最新时不做任何改动）
4. 新窗口启动后端（`uvicorn --reload`，端口 8000）
5. 新窗口启动前端（`npm run dev`，端口 3000），两个端口都就绪后打开浏览器

8000 或 3000 端口已被占用时视为对应程序已在运行，跳过该步，重复双击不会多开。关闭「ClipSync backend」「ClipSync frontend」窗口即停止对应程序；数据库容器留在后台，数据保存在数据卷 `clipsync_dev_mysql` 中，重启电脑不会丢失。

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
| `deployment/docker/build-release.ps1`、`publish-release.ps1` | 文件带 UTF-8 BOM；PowerShell 语法解析；装有 Docker Desktop 时实际运行一次 |
| `dev-start.ps1`、`dev-start.bat` | `.ps1` 带 UTF-8 BOM、PowerShell 语法解析，`.bat` 只含 ASCII、CRLF 换行；在开发机实际运行一次 |
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
| `STORAGE_DIR` | 文件存储根目录；相对路径按启动后端时的当前目录解析（开发环境在 `backend/` 下启动） | ./storage |
| `DEFAULT_QUOTA_BYTES` | 系统设置未配置时的新用户默认配额 | 104857600（100MB） |
| `MAX_FILE_BYTES` | 单文件上限 | 524288000（500MB） |
| `CHUNK_SIZE` | 单分片上限（客户端请求值会被裁剪到此值） | 5242880（5MB） |
| `MAX_UPLOAD_SESSIONS_PER_USER` | 单用户同时进行的上传会话上限 | 5 |
| `HISTORY_KEEP` | 每用户保留的云剪切板历史条数 | 50 |
| `UPLOAD_SESSION_TTL_HOURS` | 未完成上传会话的过期时间 | 24 |

数据库中的系统设置只有三项：**是否开放注册**、**是否显示 GitHub 链接**、**新用户默认配额**，其中配额在 `.env` 里有对应的默认值，其余两项没有；数据库里有值时优先于 `.env`，在管理后台「设置」页修改（见第 9 节）。其余各项只能改 `.env` 并重启后端。

> ⚠️ **HTTP 阶段安全提示**：纯 HTTP 下密码、令牌和所有内容都明文传输，只适合测试或可信内网；正式使用应切换 HTTPS（见第 11 节）。

---

## 18. 已知限制

- **单进程**：WebSocket 连接表、限流计数与快速访问输错计数都在进程内存中（后端重启后计数清零），后端只能单 worker、单实例运行。多实例需要引入跨进程消息（如 Redis pub/sub）并改造广播层与限流存储。
- **本地磁盘存储**：文件存在服务器本地 `STORAGE_DIR`（Docker 部署为数据卷 `clipsync_storage_data`），没有对象存储支持；`deployment/docker/backup.sh` 分别备份数据库与上传文件，备份默认与服务器在同一块硬盘上，需要定期复制到其他机器。
- **监控**：只有 `deployment/docker/health_check.sh` 的基础检查，没有接入专门的监控系统。
- **部署平台**：只支持 x86_64 Linux 上的 Docker Compose；`build-release.ps1`、`publish-release.ps1` 只能在 Windows 上运行，其他系统用服务器源码构建（方式 B）。
- **测试范围**：后端有 pytest 用例（`backend/tests/`）；前端没有自动化测试，界面行为需手动验证。

