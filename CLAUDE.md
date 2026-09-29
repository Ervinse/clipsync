# ClipSync 开发约束

> 本文件是编码时必须遵守的**硬规则**，Claude 每次会话自动读取。
> 三份文档各司其职：**规格权威** → DESIGN.md（技术栈全表、数据模型字段、API 清单、目录树、机制、分阶段计划、已确认决策）；**运行 / 部署** → README.md（完整 setup、部署、配置项表、面向用户的权限说明）；**本文件** → 编码硬约束 + 指针。
> 冲突时以本文件为准；本文件未覆盖的细节以 DESIGN.md 为准（「第 N 节」指 DESIGN.md 章节）。

## 交流语言
- 始终用**简体中文**回复；报错、日志、引用文档为英文也一律用中文解释。
- 代码里的标识符、库名、API 路径、变量名保持英文原样，**不要翻译**。

## 技术栈
- 以 DESIGN.md 第 2 节为准，**不得替换**：FastAPI 全异步 + SQLAlchemy 2.0 async + asyncmy + Alembic；MySQL 8.0；JWT(python-jose) + passlib[bcrypt]；Vue 3 组合式 API + Vite + Pinia + axios；原生 WebSocket。

## 🔴 安全红线（违反即为 bug，背景见第 4、12 节）
1. **数据隔离**：隐私数据查询强制 `WHERE user_id == 当前用户`，唯一例外是 superadmin。
2. **三级角色**：admin 只能看**元数据**，**绝不**查看/下载他人文件或文本内容；仅 superadmin 可绕过内容归属校验。
3. 文件下载统一走 `/api/files/{id}/download`，仅放行**归属者与 superadmin**；`/api/admin/files` 只返元数据、**无下载入口**。
4. **路径穿越防护**：磁盘名一律用 UUID（stored_name），**绝不**用用户传入名拼路径；下载按 file_id 查库拿 stored_name。
5. **后端才是权限最终防线**——每个接口都做服务端角色 + 归属校验，前端隐藏只是体验层。
6. 密码只存 bcrypt 哈希，**绝不**写入日志或 API 响应。
7. 免登录接口（`/api/access/*`）与登录接口必须**限流**。
8. CORS 按 `.env` 的 `CORS_ORIGINS` 限定，**不用通配符**。

## 异步一致性
- DB 访问全程 async；禁止在异步路径里调用同步阻塞操作。
- 文件合并与下载一律**流式**处理，禁止一次性读入内存。

## HTTP / HTTPS 双部署（编码要点，机制见第 11 节）
- 前端 API 用**相对路径**（`/api/...`）；WebSocket 按 `window.location.protocol` 自动选 `ws://`/`wss://`，**禁止写死协议**。
- 访问码链接由后端按请求的 `scheme` + `host` **动态拼接**，禁止硬编码协议或域名。
- 安全行为读 `.env` 开关（`DEPLOY_SCHEME`/`COOKIE_SECURE`/`HSTS_ENABLED`/`CORS_ORIGINS`）；Token 走 `Authorization` header + localStorage，不依赖 cookie。

## 目录结构（细节见第 13 节）
- 项目根为 `clipsync/`，**所有文件都在此之下**，不得在根目录之外创建文件。
- 新增文件前先对照第 13 节的落位；**确需新目录，先说明理由再建**。

## 数据模型（字段以第 5 节为准）
- 字段**不要随意增减**；clipboard 一人一条「当前文本」用 upsert，旧内容入 clipboard_history。
- 文本访问码**不存快照**，实时指向属主当前文本；文件访问码存 file_id 引用。
- 改动任何数据模型，必须**同步写 Alembic 迁移**。

## 测试
- 后端用 `pytest` + `pytest-asyncio`，测试放 `backend/tests/`。
- 新增/修复接口后补测试；安全红线（归属校验、角色边界、路径穿越）务必覆盖。

## 工作方式
- 按第 15 节的 8 个阶段推进，**不要跳阶段**。
- 新增/修改接口后，同步更新前端 api 封装与对应 store。
- 安全红线关键代码处（deps.py 角色校验、文件下载接口等）留简短中文注释标明约束意图。
- 不确定的设计取舍先问，不要自行更改第 16 节「已确认的设计决策」。

## 常用命令（速查；完整 setup 与部署见 README.md）
- 后端启动：`uvicorn app.main:app --reload`（在 `backend/`）
- 应用迁移：`alembic upgrade head`；改模型后生成迁移：`alembic revision --autogenerate -m "描述"`
- 跑单个测试：`pytest tests/test_xxx.py::test_name`
- 初始化首个超管：`python -m scripts.create_superadmin`
- 前端：`npm run dev`（开发）/ `npm run build`（构建），在 `frontend/`
