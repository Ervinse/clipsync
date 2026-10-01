# ClipSync 开发约束

> 本文件是编码时必须遵守的**硬规则**，Claude 每次会话自动读取。
> 三份文档各司其职：**规格权威** → DESIGN.md（技术栈全表、数据模型字段、API 清单、目录树、机制、分阶段计划）；**运行 / 部署** → README.md（完整 setup、部署、配置项表、面向用户的权限说明）；**本文件** → 编码硬约束 + 指针。
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

## Git 工作流程
- 主线分支是 **`master`**，始终代表项目最新的正式状态；所有功能开发在独立分支完成，**禁止直接提交到 master**。
- 分支命名规范：`feature/功能名`、`fix/问题描述`、`refactor/重构内容`。
- 提交信息用中文，简明扼要说明改动内容；多文件改动按模块分组描述。
- 提交前必须确保代码能运行（后端能启动、前端能构建）；测试相关改动需确保测试通过。
- `.gitignore` 已配置排除：虚拟环境、`node_modules/`、`.env`、`backend/uploads/`、编译产物。

### 分支生命周期（开分支 → 提交 → 等用户指令合并 → 删分支）
1. **每次新的更新都在 `feature/*` 或 `fix/*` 分支上进行**：从最新的 master 开分支 `git checkout master && git checkout -b <type>/<name>`，不要从其他未合并的分支上接着开。
   - 唯一例外：新工作必须依赖某个尚未合并的分支时，先向用户说明并等用户决定。
2. **对项目的每次操作都必须提交**：每完成一项改动（代码、文档、配置、脚本）就 `git add` 指定文件 + `git commit`，不要让改动停留在未提交状态。
3. **只有用户明确说「合并」才能合并**：分支工作完成后向用户汇报并等待指令，**禁止**自行合并到 master（即便测试已全部通过）。合并时用 `git merge --no-ff`（保留合并节点）。
4. **合并后在 master 上复验**：重跑 `pytest`（`backend/`）和 `npm run build`（`frontend/`），确认主线可用。
5. **删除已合并的分支**：用 `git branch -d <分支>`（只删已合并分支）；**禁止**用 `-D` 强删，除非用户明确要求。
6. **会话开始时检查分支状态**：若有未合并的分支或未提交的改动，先向用户报告，再开始新工作。
- 删除分支、推送远端同样需要先汇报并等用户确认；有冲突时停下来向用户说明，不要自行取舍。

### 每次提交 / 合并后必须汇报 git 状态
每次 `commit` 或 `merge` 之后，向用户汇报：
- 当前所在分支，以及本地所有分支列表（`git branch -v`）
- 刚产生的提交 / 合并节点（哈希 + 提交信息）
- 工作区是否干净（`git status --short`）
- 有哪些分支尚未合并回 master（`git branch --no-merged master`）
- 最近的提交图（`git log --oneline --graph -n 10`）

## 工作方式
- 按第 15 节的 8 个阶段推进，**不要跳阶段**。
- 新增/修改接口后，同步更新前端 api 封装与对应 store。
- 安全红线关键代码处（deps.py 角色校验、文件下载接口等）留简短中文注释标明约束意图。
- 不确定的设计取舍先问，不要自行更改 DESIGN.md 中已定的设计。
- **执行任何操作前，必须向用户汇报将要做什么；操作完成后，汇报实际做了什么、结果如何**。

## 常用命令（速查；完整 setup 与部署见 README.md）
- 后端启动：`uvicorn app.main:app --reload`（在 `backend/`）
- 应用迁移：`alembic upgrade head`；改模型后生成迁移：`alembic revision --autogenerate -m "描述"`
- 跑单个测试：`pytest tests/test_xxx.py::test_name`
- 初始化首个超管：`python -m scripts.create_superadmin`
- 前端：`npm run dev`（开发）/ `npm run build`（构建），在 `frontend/`
- Git 操作：开分支 `git checkout master && git checkout -b feature/功能名`；提交用 `git add` + `git commit -m "描述"`；收口（**仅在用户说合并后**）`git checkout master && git merge --no-ff feature/功能名 && git branch -d feature/功能名`；汇报状态 `git branch -v && git status --short && git branch --no-merged master && git log --oneline --graph -n 10`
