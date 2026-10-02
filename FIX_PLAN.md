# ClipSync 审查问题修复计划

> 来源：master @ `452cfa4` 的跨模块只读审查（后端生命周期与权限、并发与实时同步、前端状态与部署三份报告，关键结论已对照代码复核）。
> 用法：按阶段顺序推进，每个阶段从最新的 `master` 开一个分支，做完、测试通过、前端能构建后再合并。每条修完在前面的 `[ ]` 打勾。
> 行号以 `452cfa4` 为准，修改后可能漂移，以函数名定位为主。

## 已定的取舍

| 问题 | 决定 | 理由 |
|---|---|---|
| 中断的上传占用配额（C1） | 新增 `DELETE /api/files/upload/{upload_id}` 取消接口，同时在 `/auth/me` 和 `GET /api/files` 返回 `reserved_bytes` | 只加取消接口解决不了「关掉页面后无法取消」；只显示 reserved 又没法主动释放。两者配合，用户既能看见也能释放 |
| 删除用户后其创建的已使用邀请码 `created_by` | 不改数据模型，保持「转记到操作者名下」，写进 DESIGN | 改成可空要动 NOT NULL 外键并写迁移，收益只是审计显示；CLAUDE.md 要求字段不随意改 |
| 全局事务隔离级别 | 保持 REPEATABLE READ，只在需要串行化的写路径里先 `commit()` 结束鉴权阶段的读视图再加锁 | 全局改 READ COMMITTED 会改变所有接口的加锁语义，需要重新推演删除用户、注册等已验证过的路径，风险大于收益 |

---

## 阶段 1：并发与数据一致性（后端）

分支：`fix/concurrency-isolation`

- [x] **1.1 剪贴板并发写重复归档、丢中间版本**
  - 位置：`backend/app/api/clipboard.py` `_write_clipboard`（加锁约第 80 行、读当前文本约第 84 行）；读视图在 `backend/app/core/deps.py:40` 已建立。
  - 原因：RR 下鉴权阶段的普通读固定了读视图，`FOR UPDATE` 之后的普通读仍用旧视图。
  - 做法：`_write_clipboard` 开头先 `await db.commit()`，再对 User 行 `with_for_update()`，然后读 Clipboard。`expire_on_commit=False`，`current_user` 提交后仍可用。
  - 测试：用两个独立 session 模拟并发（一个先锁住提交，另一个随后执行），断言历史里没有重复、中间版本进入历史。

- [x] **1.2 并发 init 绕过会话数上限**
  - 位置：`backend/app/api/files.py` `init_upload`（计数、配额、插入三段）。
  - 做法：同 1.1，先 commit，再锁 User 行，之后计数、算 reserved、插入，锁持有到插入后的 commit。

- [x] **1.3 删除用户时漏清新建会话的 tmp 目录**
  - 位置：`backend/app/api/admin.py` `delete_user` 读取 `upload_ids` 处。
  - 做法：读取前先锁 User 行（或该查询改成 `with_for_update()`），保证与 1.2 的 init 串行。

- [x] **1.4 重传已存在的分片时 StaleDataError 兜底失效**（疑似，先写测试复现）
  - 位置：`backend/app/api/files.py` `upload_chunk` 末尾的 commit。
  - 做法：提交前显式 `UPDATE upload_sessions ... WHERE upload_id=?` 并检查 `rowcount`，为 0 时清理 tmp 返回 404。

- [x] **1.5 分片写到一半 tmp 被删返回 500**（疑似）
  - 做法：`_save_chunk` / `replace` 调用处捕获 `FileNotFoundError`，返回 404「上传会话不存在或已结束」。

验收：`pytest` 全部通过，新增并发测试通过。

---

## 阶段 2：前端会话与账号状态

分支：`fix/frontend-session-state`

- [x] **2.1 多标签页账号串用**
  - 位置：`frontend/src/stores/user.js:10`、`frontend/src/api/request.js:23`、`frontend/src/utils/websocket.js:157`。
  - 做法：在 `main.js` 监听 `storage` 事件，`access_token` 变化时 `location.reload()`；请求拦截器和 WS 重连改为读 `userStore.token`。

- [x] **2.2 账号被禁用后前端无处理**
  - 后端：`backend/app/core/deps.py` 被禁用时的 403 增加响应头 `X-Auth-Error: disabled`（机器可读，避免按中文 detail 匹配）。
  - 前端：`request.js` 遇到带该响应头的 403（且不是 `/auth/login`）按 401 处理；`user.js` 监听 WS 的 `auth_failed`，执行登出并跳转 `/login`。
  - 测试：后端补一个用例断言该响应头存在。

- [x] **2.3 WS 握手被拒收到 1006，无限重连**
  - 位置：`backend/app/api/ws.py:60`（accept 前 close）、`frontend/src/utils/websocket.js` `onclose` / `retryNow`。
  - 做法：前端增加 `authFailed` 标记，`retryNow`、`scheduleReconnect` 都检查它；连接从未 open 就关闭时 emit `handshake_failed`，user store 收到后调一次 `/auth/me`，401/403 则登出、不再重连，其他情况继续退避重连。登录成功后清除 `authFailed`。

- [x] **2.4 登出不清理其他 store**
  - 位置：`frontend/src/stores/user.js` `logout`。
  - 做法：在函数内部取 clipboard、files、access、admin 四个 store，先调各自的 `cleanupWebSocket`（有的话），再 `$reset()`。注意循环引用：在函数内 `useXxxStore()`，不要在模块顶部互相 import。

- [x] **2.5 启动时任何错误都清掉 token**
  - 位置：`frontend/src/stores/user.js` `fetchUserInfo` / `init`。
  - 做法：只在 `status` 为 401 或 403 时登出；网络错误或 5xx 保留 token，提示「暂时无法连接服务器」。

验收：`npm run build` 通过；浏览器手动验证：两个标签页换账号、禁用账号后的跳转、刷新时后端停机不丢登录。

---

## 阶段 3：实时同步覆盖

分支：`fix/realtime-coverage`

- [x] **3.1 断线重连后不补拉**
  - 位置：`frontend/src/stores/clipboard.js`、`frontend/src/stores/files.js` 的 `setupWebSocket` / `cleanupWebSocket`。
  - 做法：同时订阅 `open`，复用已有回调；cleanup 时一并解绑。

- [x] **3.2 删除历史不广播**
  - 位置：`backend/app/api/clipboard.py` `delete_clipboard_history`。
  - 做法：提交后广播 `clipboard_updated`。

- [x] **3.3 历史面板为空时其他终端保存不刷新**
  - 位置：`frontend/src/stores/clipboard.js`（`history.length > 0` 判断）。
  - 做法：store 增加 `historyVisible`，由 `Clipboard.vue` 打开/关闭面板时设置，回调里按它判断是否重拉历史。

- [x] **3.4 访问码变更不同步**
  - 后端：`backend/app/api/access.py` 创建、撤销后广播 `access_codes_changed`；删除文件时已级联删码，`file_deleted` 足够。
  - 前端：`AccessCodes.vue` 挂载时订阅 `access_codes_changed` 和 `file_deleted`，收到后 `fetchCodes()`，卸载时解绑。

- [x] **3.5 侧栏配额刷新不全**
  - 前端：把 `file_added` / `file_deleted` / `quota_updated` 的配额刷新监听放到 `Home.vue`（布局级），收到后调 `userStore.fetchUserInfo()`；`files.js` `deleteFile` 成功后主动 `fetchFiles()`。
  - 后端：`backend/app/api/admin.py` `update_user_quota` 提交后给目标用户广播 `quota_updated`。

- [x] **3.6 WS 刷新导致文件列表闪烁**
  - 位置：`frontend/src/stores/files.js` `fetchFiles`。
  - 做法：增加 `{ silent }` 参数，WS 回调用静默版本，不改 `isLoading`。

- [x] **3.7 剪贴板 WS 拉取乱序**（疑似）
  - 做法：静默刷新带递增序号，只采用最新一次请求的结果。

验收：`pytest`、`npm run build` 通过；两个浏览器窗口手动验证各事件。

---

## 阶段 4：上传配额与文件下载

分支：`fix/upload-quota-download`

- [x] **4.1 中断上传占用配额，无法取消**（按「已定的取舍」）
  - 后端：新增 `DELETE /api/files/upload/{upload_id}`，校验归属后删除会话并在线程池清理 tmp，返回 204；`UserWithStats` 与 `FileListResponse` 增加 `reserved_bytes`（进行中会话的声明大小之和）。
  - 前端：`api/files.js` 封装取消接口；`files.js` `uploadFile` 的 catch 里调用（忽略取消本身的失败）；配额显示改为「已用 + 上传中」。
  - 测试：取消他人会话返回 404；取消后配额释放、可立即 init。
  - 同步 DESIGN 6.3 接口表和第 10 节。

- [x] **4.2 下载时文件被删导致连接截断**
  - 位置：`backend/app/api/files.py` `stream_file_response`。
  - 做法：线程池中先 `open` 再 `os.fstat` 取大小，把句柄交给生成器；`FileNotFoundError` 返回 404。

- [x] **4.3 async 路径里残留的同步文件系统调用**（CLAUDE.md 异步一致性）
  - `files.py`：complete 里的 `iterdir` 排序、upload_chunk 的 `is_dir()`、两处 `ensure_*_dir`、`stream_file_response` 的检查（4.2 一并处理）。
  - 做法：全部改用 `run_in_threadpool`。

- [x] **4.4 磁盘删除失败无日志、孤儿文件无人清理**
  - `backend/app/core/storage.py`：`rmtree` 去掉 `ignore_errors`，改用 `onexc`/`onerror` 回调记日志；`admin.py` `delete_user` 删磁盘处 `try/except OSError` 记日志。
  - `deployment/scripts/cleanup_expired.sh`：增加孤儿扫描——`storage/tmp/*` 中 mtime 超过 TTL 且不在 `upload_sessions` 的目录、`storage/<uid>` 中 uid 不在 `users` 表的目录，删除并记录。

- [x] **4.5 公开下载「文件已丢失」暴露码有效**
  - 位置：`stream_file_response` 被公开路径调用时。
  - 做法：公开路径统一返回「访问码无效或已失效」。

- [x] **4.6 剪贴板长度按字符校验、库按字节存**（疑似）
  - 位置：`backend/app/schemas/clipboard.py`。
  - 做法：validator 按 `len(value.encode("utf-8")) <= 16777215` 校验，补测试。

验收：`pytest`、`npm run build` 通过。

---

## 阶段 5：管理后台与界面细节

分支：`fix/admin-ui-details`

- [x] **5.1 必然失败的按钮**（`frontend/src/views/Admin.vue`）
  - 禁用按钮对 superadmin 行隐藏（`v-if="user.role !== 'superadmin'"`）。
  - 已使用邀请码隐藏删除按钮（`v-if="!invite.used_at && !invite.used_by"`）。
- [x] **5.2 邀请码状态**：「未使用/有效」同时判断 `expires_at`（`stores/admin.js` `validInviteCount`、`Admin.vue` 显示处），区分已用 / 已过期 / 可用。
- [x] **5.3 配额输入校验**：`handleUpdateQuota` 参照 `handleSaveSettings` 做非负整数校验，默认值取整。
- [x] **5.4 列表只显示前 50 条**：用户和文件列表保存 `total`，加分页控件。
- [x] **5.5 删除/禁用用户后统计过期**：操作成功后重新拉取 `stats`、`files`。
- [x] **5.6 访问码状态显示**：`stores/access.js` 拆分 `revoked` 与 `expired`；8760 小时上限前后端都加校验。
- [x] **5.7 空文件上传提示英文**：`stores/files.js` 上传前检查 `file.size === 0`。
- [x] **5.8 上传期间离开文件页再回来可并发上传**：`isUploading` 改为放在 files store。
- [x] **5.9 `/api/admin/files` 排序缺次键**：`admin.py` `list_all_files` 加 `File.id.desc()`。
- [x] **5.10 残留代码清理**：删除 `HelloWorld.vue` 及 `hero.png`、`vite.svg`、`vue.svg`；删除未使用的 `api/admin.js` `users.get`、access store 的 `textCodes`/`fileCodes`、admin store 的 3 个 getter、clipboard store 的 `historyTotal`；`AccessFileResponse` 改为在公开页提供文件名和大小的元数据接口，或直接删除（倾向删除，公开页文件名展示不是必需）。

验收：`npm run build` 通过，浏览器手动过一遍管理后台。

---

## 阶段 6：部署

分支：`fix/docker-deploy`

- [x] **6.1 compose 命令被 YAML 折叠截断，代理头参数未生效**（违反红线 7）
  - 位置：`deployment/docker/docker-compose.yml` backend `command`。
  - 做法：`command: ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips '<compose 网段>'"]`。
- [x] **6.2 内网可伪造 XFF**：`nginx-docker.conf` 改为 `X-Forwarded-For $remote_addr`；compose 定义自定义网络并固定子网，`--forwarded-allow-ips` 只信任该子网。
- [x] **6.3 没有 `.dockerignore`**：在 `backend/`、`frontend/` 下新建，排除 `.env`、`.venv`、`venv`、`__pycache__`、`.pytest_cache`、`storage`、`node_modules`、`dist`。（新增文件，属于已有目录内的配置文件）
- [x] **6.4 compose 缺少可配置变量**：补传 `JWT_ALGORITHM`、`DEFAULT_QUOTA_BYTES`、`MAX_FILE_BYTES`、`CHUNK_SIZE`、`MAX_UPLOAD_SESSIONS_PER_USER`、`HISTORY_KEEP`、`UPLOAD_SESSION_TTL_HOURS`，同步 `docker/.env.example`。
- [x] **6.5 数据库密码留空静默回落弱默认值**：改为 `${DB_PASSWORD:?DB_PASSWORD 未设置}`、`${DB_ROOT_PASSWORD:?...}`。
- [x] **6.6 update.sh 失败后服务停着**：`trap` 保证退出时 `systemctl start clipsync`；git 操作用 `sudo -u www-data git -C ...`；用 `git update-index --chmod=+x` 把 5 个脚本提交为 `100755`。
- [x] **6.7 cron 依赖可执行位**：`deploy.sh` 生成的 cron 行改为 `bash /path/xxx.sh`。
- [x] **6.8 backup_database.sh 缺键静默退出**：`read_env` 末尾 `|| true`；临时 cnf 的 `password` 加引号。
- [x] **6.9 Nginx `Host $host` 丢端口**：三份配置改为 `$http_host`。
- [x] **6.10 SPA 页面缺安全头**：三份 Nginx 的 `location /` 加 `X-Frame-Options DENY`、`X-Content-Type-Options nosniff`、`Referrer-Policy no-referrer`；`index.html` 加 `Cache-Control: no-cache`。HSTS 仍只由后端下发，CHECKLIST 改为检查 `/api/...`。
- [x] **6.11 deploy.sh 用 `python3` 建 venv**：检测版本 ≥ 3.12，否则提示先用 `python3.12 -m venv backend/venv` 预建。
- [x] **6.12 Docker 下没有定时清理与备份**：docker/README 写明宿主机 cron 的配置方式（`docker compose exec backend ...`），并修正备份命令（在容器内用 `$MYSQL_USER`/`$MYSQL_PASSWORD`）。
- [x] **6.13 小问题**：`health_check.sh` HTTPS 阶段 301 误报、未用 `DB_PORT`、WS 连接数统计不准；`clipsync.service` 删除无效的 `PATH=...:$PATH` 行；`vite.config.js` 代理目标改为 `127.0.0.1:8000`。
- [ ] **6.14 待验证**：全新卷 `compose up` 时 healthcheck 过早通过；重建 backend 后 frontend Nginx 缓存旧 IP（如复现，加 `resolver 127.0.0.11` 与变量式 `proxy_pass`）。
  - 已做预防性修改（healthcheck 改走 TCP 并加 `start_period`；nginx-docker.conf 加 resolver 与变量式 proxy_pass），但未在 Linux 上实际复现验证，保持未勾选。

验收：脚本 `bash -n` 通过；有条件时在 Linux 上实际执行一次 deploy / update / compose up。

---

## 阶段 7：文档同步

分支：`fix/docs-sync`（放在最后，覆盖前面各阶段带来的变化）

- [ ] DESIGN 第 7 节、frontend/README：握手被拒为 1006、踢下线为 1008；广播发给用户全部连接（含触发方），删掉「exclude=触发连接」；补充新事件 `access_codes_changed`、`quota_updated`，以及重连后补拉。
- [ ] DESIGN 第 9 节与目录树：管理后台 5 个 tab（含设置）。
- [ ] DESIGN 6.2：删除「恢复/删除历史前端未接入」。
- [ ] DESIGN 第 4 节：superadmin 也不能禁用或删除其他 superadmin。
- [ ] DESIGN 第 5 节：删除用户时邀请码处理规则（未使用删除、已使用转记到操作者）。
- [ ] DESIGN 第 8 节：属主禁用期间访问码失效，重新启用后恢复。
- [ ] DESIGN 第 10 节、6.3：取消上传接口、`reserved_bytes`、显示口径。
- [ ] DESIGN 6.4：过期访问码会被定时任务删除。
- [ ] DESIGN 第 14 节：deploy.sh 自动执行第 2–5 步，服务需手动 enable；HSTS 由后端按 `HSTS_ENABLED` 下发。
- [ ] CLAUDE.md:31：`HSTS_ENABLED`、`CORS_ORIGINS` 生效，`DEPLOY_SCHEME`、`COOKIE_SECURE` 为预留。
- [ ] CLAUDE.md:4、:78：部署指针改为 `deployment/DEPLOY.md`。
- [ ] CLAUDE.md:51：`.gitignore` 排除 `backend/storage/`。
- [ ] docker/README：代理信任网段与 XFF 说明、定时任务、备份命令。
- [ ] CHECKLIST：回滚章节（DEPLOY.md 补写）或删掉引用；统一 `npm ci`；HSTS 检查改查 `/api`。
- [ ] DESIGN 目录树、frontend/README：补上 `utils/clipboard.js`、`utils/format.js` 等。
- [ ] 本文件：全部完成后标注完成日期，或删除。

---

## 不在本计划内

- 断点续传的前端实现（后端已支持重传分片），属于新功能，需要时另开 `feature/*`。
- 有未保存编辑时远端更新被覆盖的提示条，属于交互设计取舍，需要时另议。
- 大文件下载改为短时效下载票据（之前已决定先不做）。
