# ClipSync 开发约束

> 本文件是编码时必须遵守的**硬规则**，Claude 每次会话自动读取。
> 文档分工：**规格权威** → README.md（项目说明、技术栈全表、数据模型字段、API 清单、机制、目录树、功能模块与实现范围、开发环境、配置项）；**待办** → TODO.md；**部署** → deployment/DEPLOYMENT.md（只支持 Docker Compose）；**本文件** → 编码硬约束 + 指针。
> 冲突时以本文件为准；本文件未覆盖的细节以 README.md 为准（「第 N 节」指 README.md 章节）。

## 交流语言
- 始终用**简体中文**回复；报错、日志、引用文档为英文也一律用中文解释。
- 代码里的标识符、库名、API 路径、变量名保持英文原样，**不要翻译**。

## 技术栈
- 以 README.md 第 2 节为准，**不得替换**：FastAPI 全异步 + SQLAlchemy 2.0 async + aiomysql + Alembic；MySQL 8.4 LTS；JWT(python-jose) + bcrypt；Uvicorn **单 worker**；Vue 3 组合式 API + Vite + Pinia + axios；原生 WebSocket。

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
- 安全行为读 `.env` 开关：`HSTS_ENABLED`（后端下发 HSTS 头）、`CORS_ORIGINS`（CORS 白名单）已生效；`DEPLOY_SCHEME`、`COOKIE_SECURE` 为预留项，目前代码未使用。Token 走 `Authorization` header + localStorage，不依赖 cookie。

## 目录结构（细节见第 13 节）
- 项目根为 `clipsync/`，**所有文件都在此之下**，不得在根目录之外创建文件。
- 新增文件前先对照第 13 节的落位；**确需新目录，先说明理由再建**。

## 数据模型（字段以第 5 节为准）
- 字段**不要随意增减**；clipboard 一人一条「当前文本」用 upsert，旧内容入 clipboard_history；文本栏目（texts）每人多条，没有历史。
- 快速访问码挂在内容上（clipboard / texts / files 的 `access_code` + `access_expires_at`），每样内容最多一个、可重复；云剪切板的访问码**不存快照**，实时指向当前文本。
- 快速访问凭证（JWT `typ=qa`）与登录凭证**互不通用**；快速访问每个请求都回库校验访问码仍有效，查询限定「属主 + 访问码」。
- 改动任何数据模型，必须**同步写 Alembic 迁移**。

## 测试
- 后端用 `pytest` + `pytest-asyncio`，测试放 `backend/tests/`；现有用例经 FastAPI `TestClient` 同步调用，测试库为独立的 `clipsync_test`（每次运行 DROP 重建）。
- 新增/修复接口后补测试；安全红线（归属校验、角色边界、路径穿越）务必覆盖。
- 何时运行测试见下方「按改动范围验证」：只改文档不跑测试；前端没有自动化测试，改前端只跑 `npm run build` 并手动验证。

## Git 工作流程
- 主线分支是 **`master`**，始终代表项目最新的正式状态；所有功能开发在独立分支完成，**禁止直接提交到 master**。
- 分支命名规范：`feature/功能名`、`fix/问题描述`、`refactor/重构内容`、`docs/文档改动`（仅改文档 `*.md` 或纯注释时用）。
- 提交信息用中文，简明扼要说明改动内容；多文件改动按模块分组描述。
- 提交前按改动范围验证（见下方「按改动范围验证」），不要对无关改动跑全套验证。
- `.gitignore` 已配置排除：虚拟环境、`node_modules/`、`.env`、`backend/storage/`（上传文件）、编译产物、`release/`（镜像包与部署包，见「发布与发布说明」）、`deployment/docker/acme/` 与 `deployment/docker/letsencrypt/`（在该目录直接运行 compose 时生成）。

### 分支生命周期（开分支 → 提交 → 等用户指令合并 → 删分支）
1. **每次新的更新都在 `feature/*`、`fix/*`、`refactor/*` 或 `docs/*` 分支上进行**：从最新的 master 开分支 `git checkout master && git checkout -b <type>/<name>`（仅改文档或注释用 `docs/*`），不要从其他未合并的分支上接着开。
   - 唯一例外：新工作必须依赖某个尚未合并的分支时，先向用户说明并等用户决定。
2. **对项目的每次操作都必须提交**：每完成一项改动（代码、文档、配置、脚本）就 `git add` 指定文件 + `git commit`，不要让改动停留在未提交状态。
3. **只有用户明确说「合并」才能合并**：分支工作完成后向用户汇报并等待指令，**禁止**自行合并到 master（即便测试已全部通过）。合并时用 `git merge --no-ff`（保留合并节点）。
4. **合并后在 master 上复验**：按本次合并涉及的改动范围复验（见下方「按改动范围验证」）；只含文档的合并不需要复验。
5. **删除已合并的分支**：用 `git branch -d <分支>`（只删已合并分支）；**禁止**用 `-D` 强删，除非用户明确要求。
6. **会话开始时检查分支状态**：若有未合并的分支或未提交的改动，先向用户报告，再开始新工作。
- 删除分支需要先汇报并等用户确认；有冲突时停下来向用户说明，不要自行取舍。
- **远程操作一律由用户执行**（`git push`、推送标签、创建 GitHub Release、上传发布文件等）：Claude 只做本地操作，需要远程操作时给出命令，由用户自己执行。

### 按改动范围验证
提交前与合并后，只跑与改动相关的验证：

| 改动内容 | 需要的验证 |
|------|------|
| 只改文档（`*.md`）或纯注释 | 不跑测试与构建；只检查文中路径、命令、引用与代码一致 |
| `backend/` 代码、迁移、依赖 | `pytest`（在 `backend/`） |
| `frontend/` 代码、依赖、`vite.config.js` | `npm run build`（在 `frontend/`） |
| `deployment/docker/*.sh` | `bash -n` 语法检查；装有 Docker 时在本机 compose 环境实际运行，否则记入 TODO.md |
| `deployment/docker/build-release.ps1`、`publish-release.ps1` | 确认文件带 UTF-8 BOM（PowerShell 5.1 读中文需要）；PowerShell 语法解析（`[System.Management.Automation.Language.Parser]::ParseFile`，用绝对路径）；装有 Docker Desktop 时实际运行一次，否则记入 TODO.md |
| `dev-start.ps1`、`dev-start.bat`（开发环境一键启动） | `.ps1` 带 UTF-8 BOM、PowerShell 语法解析；在开发机实际运行一次；`.bat` 只含 ASCII、CRLF 换行 |
| compose、Dockerfile、Nginx 配置 | `docker compose config` 校验；装有 Docker 时构建并启动一次；只能在真实服务器上验证的（公网证书、cron、防火墙）记入 TODO.md |

改动跨多个范围时，把对应的验证都跑一遍；汇报时写明跑了哪些、按规则跳过了哪些。

### 每次提交 / 合并后必须汇报 git 状态
每次 `commit` 或 `merge` 之后，向用户汇报：
- 当前所在分支，以及本地所有分支列表（`git branch -v`）
- 刚产生的提交 / 合并节点（哈希 + 提交信息）
- 工作区是否干净（`git status --short`）
- 有哪些分支尚未合并回 master（`git branch --no-merged master`）
- 最近的提交图（`git log --oneline --graph -n 10`）

## 部署打包（镜像标签与版本一致性）
- 本项目没有 CI/CD；镜像构建、打提交号与 `latest` 标签、打测试包只在 `deployment/docker/build-release.ps1` 一处完成，它是本规范的权威实现。调整打包策略即改这个脚本，并同步更新本节。
- 版本号标签只由 `deployment/docker/publish-release.ps1` 打（见下方「正式版本晋级」），`build-release.ps1` 不打版本号标签。
- **commit 哈希标签（必打）**：用 `git rev-parse --verify <ref>^{commit}`（`<ref>` 默认 `HEAD`，可用 `-Ref` 指定分支或提交）取完整哈希，截前 12 位作为标签，如 `clipsync-backend:9718d16c4fde`。每个镜像一定有这个标签，用于精确追溯。
- **latest 标签（有条件）**：仅当「要打包的提交哈希」等于「`master` 当前提交哈希」（按哈希比对，非分支名）时，才额外追加 `:latest`；非 master 或旧提交只有 commit 哈希标签。服务器 `.env` 的 `CLIPSYNC_TAG` 默认 `latest`，故测试分支的镜像导入后不会被误用。
- **版本一致性**：同一个 commit 哈希（脚本里的 `$Commit` 变量）必须同时写入这几处，保证永远一致：
  1. 镜像标签（`-t <镜像名>:<commit>`）
  2. 镜像 label `org.opencontainers.image.revision=<commit>`（`health_check.sh` 据此显示运行中的提交）
  3. 部署包内 `VERSION` 文件，含 `commit=` / `branch=` / `latest=` / `built=` 四个字段
  4. 两个产物的文件名：`clipsync-images-<commit>[-app].tar.gz`、`clipsync-deploy-<commit>.tar.gz`
- 打包只取**已提交**的代码（`git archive`），工作区未提交的改动不进镜像；打包的不是 master 最新提交或工作区不干净时，脚本要求确认。

## 正式版本晋级（publish-release.ps1）
用户要求「把某个提交 / 测试构建晋级为版本 X」时，按以下步骤做。核心原则：**不重新构建**，只给测试过的同一份镜像追加版本号标签。
1. **确认对象**：要晋级的提交必须在 master 上，且用户确认该提交的测试构建（`release/<commit>/`）已测试通过。版本号按 SemVer，带 `-` 后缀的是预发布版。
2. **Git 标签**：`git rev-parse --verify v<版本号>^{commit}` 检查标签。没有时在该提交上建附注标签 `git tag -a v<版本号> <commit> -m "说明"`（本地操作）；已有但指向别的提交时停下来问用户，不要移动标签。
3. **镜像**：本机须有 `clipsync-backend:<commit>`、`clipsync-frontend:<commit>`。被清理过时用 `docker load -i release/<commit>/clipsync-images-<commit>.tar.gz` 导回，**禁止**用 `build-release.ps1` 重新构建来代替（重新构建得到的是另一份镜像）。
4. **运行**：`powershell -ExecutionPolicy Bypass -File deployment\docker\publish-release.ps1 -Version <版本号>`（不带 `v`）。脚本会校验镜像 label 里的提交号、追加 `<版本号>` 标签、导出镜像包（backend / frontend 各带 `<版本号>` 与 `<commit>` 标签 + compose 里的 MySQL，**不含 `latest`**）、生成部署包与 `SHA256SUMS`，产物在 `release/<版本号>/`。
5. **发布包与测试包的唯一差别**：部署包里 `.env.example` 的 `CLIPSYNC_TAG` 预填 `<版本号>`；`VERSION` 增加 `version=` 与 `published=`，`latest=no`。`docker-compose.yml` 等其他文件与该提交完全相同，**不修改 compose**。
6. **核对产物**（全部做完再汇报）：`sha256sum -c SHA256SUMS`；SHA256SUMS 无 BOM、只用 LF；部署包内 `VERSION` 与 `.env.example` 的 `CLIPSYNC_TAG`；镜像包 `manifest.json` 的 `RepoTags`。装有 Docker 时在临时目录解压部署包、用发布包 `docker load` 后以版本号 `docker compose up -d` 启动一次，`health_check.sh` 显示版本号与运行中的提交，用完 `docker compose down -v` 并删除临时目录（先确认没有同名 `clipsync` 项目的容器和数据卷）。
7. **镜像 ID**：开发机启用 containerd 镜像存储时，本机 `docker images` 的 IMAGE ID 与服务器上的不同；与服务器测试版本核对时以脚本最后打印的镜像 ID（导出包 `manifest.json` 的配置摘要）为准。
8. **notes**：按「发布与发布说明」更新 `release-notes/v<版本号>.md` 与 `.internal.md`，把三个文件的 SHA-256 与镜像 ID 记入 `.internal.md`。
9. **远程操作交给用户**：给出 `git push origin master v<版本号>`，以及在 GitHub 网页创建 Release 的步骤（选标签、贴 notes、预发布版勾选 Set as a pre-release、上传 `release/<版本号>/` 的三个文件）。

## 发布与发布说明（产物与 notes 的存放、写 notes 的规矩）
- **版本号**：按 SemVer（如 `1.0.0`、`1.0.0-alpha.1`）。Git 标签带 `v`（`v1.0.0-alpha.1`，附注标签）；目录名、镜像版本号标签不带 `v`。
- **产物目录 `release/`**（`.gitignore` 排除）：只放镜像包与部署包，按版本分子目录，不放任何其他文件。
  - 测试构建：`release/<commit>/`，由 `build-release.ps1` 直接输出。
  - 正式版本：`release/<版本号>/`，由 `publish-release.ps1` 输出，放发布到 GitHub Release 的三个文件。
  - 清理磁盘时按子目录删除；已发布版本的目录与其对应的测试构建目录保留到下一个正式版发布后。
- **发布说明目录 `release-notes/`**（`.git/info/exclude` 本地忽略，不进 git，与 `release/` 分开，不随产物清理）。每个版本两个文件：
  - `v<版本号>.md`：发布页正文，原样粘贴到 GitHub Release。
  - `v<版本号>.internal.md`：内部记录，不发布。内容：标签对应的完整提交、对应测试构建目录及其 SHA-256、正式发布文件的 SHA-256、测试情况、改动范围、遗留事项。
- **写 notes 的规矩**：
  - 动笔前先读上一版的 `.internal.md`，用 `git log v<上一版>..v<新版> --first-parent --oneline` 查本版改动范围。
  - 发布页正文的读者是下载部署的使用者：不提开发者本人、开发机或某台服务器，不写内部流程。
  - **首个版本（alpha.1）写完整**：功能、部署、安全、已知限制。**之后的版本只写相比上一版的变化**，简明扼要，不复述项目介绍、功能清单和未变的部署说明。
  - **发布页格式**：标题只用中文，不加英文，按以下结构写；没有内容的节整节省略：
    ```markdown
    # ClipSync v<版本号>：<本版主题>

    ## 新增

    ## 改进

    ## 修复

    ## 升级注意

    ## 下载

    | 文件 | 说明 |
    |------|------|
    | `clipsync-images-<版本号>.tar.gz` | 镜像包：backend、frontend、MySQL <MySQL 版本> |
    | `clipsync-deploy-<版本号>.tar.gz` | 部署包：compose 文件、Nginx 配置、运维脚本、部署手册 |
    | `SHA256SUMS` | 校验文件，执行 `sha256sum -c SHA256SUMS` |

    两个包来自提交 `<提交号>`，镜像标签为 `<版本号>`（不带 `latest`）。
    ```
  - 打包脚本、CLAUDE.md、测试等开发流程上的改动不进发布页，只记入 `.internal.md`。
  - 文件名、标签、提交号、校验值必须对照实际产物核对后再写（`sha256sum` 实算、部署包内 `VERSION` 实读），不凭记忆填写。
- 发布到 GitHub（推送标签、创建 Release、上传文件）由用户执行，见「Git 工作流程」中的远程操作规则。

## 工作方式
- 新功能先对照第 15 节的实现范围与 TODO.md，确认不与已有设计冲突再动手。
- 新增/修改接口后，同步更新前端 api 封装与对应 store。
- 安全红线关键代码处（deps.py 角色校验、文件下载接口等）留简短中文注释标明约束意图。
- 不确定的设计取舍先问，不要自行更改 README.md 中已定的设计。
- **执行任何操作前，必须向用户汇报将要做什么；操作完成后，汇报实际做了什么、结果如何**。

## 文档与注释同步
- **每次修改代码后，必须检查对应的文档、说明与注释**，与代码不一致的在同一次提交里一起改，不允许出现「代码改了、文档没改」。至少检查：
  - README.md 中受影响的章节：API 表（第 6 节）、数据模型（第 5 节）、WebSocket 事件（第 7 节）、配置项（第 17 节）、目录树（第 13 节）、实现范围（第 15 节）
  - frontend/README.md（前端行为、store、事件处理）；deployment/ 下的文档与 `.env` 模板（部署、脚本、配置变量）
  - 被修改函数 / 模块自身的 docstring 与注释，以及相关测试文件的 docstring
  - TODO.md：完成的事项删掉，新发现的未完成事项补上
- 汇报时写明检查了哪些文档、改了哪些、哪些确认无需修改。
- **文档与注释只描述当前状态**：README、各说明文档、代码注释的读者是使用和维护这份代码的人，只写代码现在是什么、为什么这样做；不写修改历史（如「原先…」「已改为…」「不再…」「已合并」「阶段 N 修复」）。修改历史写在 git 提交信息里。

## 常用命令（速查；完整 setup 见 README.md 第 16 节，部署见 deployment/DEPLOYMENT.md）
- 开发环境一键启动：双击根目录 `dev-start.bat`（数据库容器 + 迁移 + 后端 + 前端 + 浏览器）
- 后端启动：`uvicorn app.main:app --reload`（在 `backend/`）
- 应用迁移：`alembic upgrade head`；改模型后生成迁移：`alembic revision --autogenerate -m "描述"`
- 跑单个测试：`pytest tests/test_xxx.py::test_name`
- 初始化首个超管：`python -m scripts.create_superadmin`
- 前端：`npm run dev`（开发）/ `npm run build`（构建），在 `frontend/`
- Git 操作：开分支 `git checkout master && git checkout -b feature/功能名`；提交用 `git add` + `git commit -m "描述"`；收口（**仅在用户说合并后**）`git checkout master && git merge --no-ff feature/功能名 && git branch -d feature/功能名`；汇报状态 `git branch -v && git status --short && git branch --no-merged master && git log --oneline --graph -n 10`
