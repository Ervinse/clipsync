# ClipSync 前端

基于 Vue 3 + Vite 构建的跨设备剪贴板与文件同步前端应用。

## 技术栈

- **Vue 3**：组合式 API
- **Vite 8**：构建工具（要求 Node.js 20.19+ 或 22.12+）
- **Pinia**：状态管理
- **Vue Router**：路由管理
- **Axios**：HTTP 客户端
- **WebSocket**：实时通信

## 开发

### 安装依赖

```bash
npm install
```

### 启动开发服务器

```bash
npm run dev
```

访问 http://localhost:3000

### 构建生产版本

```bash
npm run build
```

构建产物在 `dist/` 目录。

### 测试与验证

前端没有自动化测试。改动前端代码（`src/`、依赖、`vite.config.js`）后运行 `npm run build` 确认能构建，界面行为在浏览器里手动验证，待验证项见 [TODO.md](../TODO.md)。只改文档不需要构建。

## 项目结构

```
src/
├── api/            # API 封装
│   ├── request.js  # Axios 实例与拦截器
│   ├── auth.js     # 认证接口
│   ├── clipboard.js # 剪贴板接口
│   ├── files.js    # 文件接口
│   ├── access.js   # 访问码接口
│   ├── admin.js    # 管理后台接口
│   └── index.js    # 统一导出
├── stores/         # Pinia 状态管理
│   ├── user.js     # 用户状态
│   ├── clipboard.js # 剪贴板状态
│   ├── files.js    # 文件状态
│   ├── access.js   # 访问码状态
│   ├── admin.js    # 管理后台状态
│   └── index.js    # 统一导出
├── router/         # 路由配置
│   └── index.js    # Vue Router 实例
├── views/          # 页面组件
│   ├── Login.vue   # 登录页
│   ├── Register.vue # 注册页
│   ├── Home.vue    # 主布局（含侧边栏）
│   ├── Clipboard.vue # 剪贴板页
│   ├── Files.vue   # 文件管理页
│   ├── AccessCodes.vue # 访问码管理页
│   ├── Admin.vue   # 管理后台页
│   └── PublicAccess.vue # 公共访问页
├── utils/          # 工具函数
│   ├── websocket.js # WebSocket 管理器
│   ├── clipboard.js # 复制到剪贴板（HTTP 下降级为 execCommand）
│   └── format.js    # 文件大小、UTC 时间格式化
├── App.vue         # 根组件（全局基础样式与深色主题）
├── style.css       # 全局样式入口（目前为空，全局样式写在 App.vue）
└── main.js         # 入口文件（先恢复登录状态再挂载路由，监听跨标签页 token 变化）
```

## 功能模块

### 认证 (Login/Register)
- 用户登录/注册
- JWT Token 管理
- 路由守卫

### 剪贴板 (Clipboard)
- 实时文本同步（本地有未保存编辑时，远端更新不覆盖编辑框）
- 历史记录：查看、载入编辑框、恢复为当前文本、删除
- WebSocket 推送

### 文件管理 (Files)
- 分片上传（1MB/片），同一时间只允许一个上传；中途失败自动取消会话、释放配额
- 「完成上传」请求的超时为 600 秒（服务端要合并分片，大文件可能超过默认的 30 秒）；完成后刷新列表失败不算上传失败，列表由随后的 `file_added` 推送补上
- 上传进度显示
- 文件列表与下载
- 配额显示（已用 + 上传中）

### 访问码 (AccessCodes)
- 创建文本/文件访问码；选择文件的下拉随 `file_added` / `file_deleted` 推送刷新，打开弹窗时也刷新一次
- 设置有效期（小时，0 为永久，最长 8760 小时，前后端都校验）
- 链接复制与撤销；状态分别显示「有效」「已撤销」「已过期」

### 管理后台 (Admin)
- 系统统计（admin 及以上）
- 用户列表，分页（admin 及以上可看；改配额 / 禁用 / 删除按钮仅超管可见，superadmin 行不显示禁用和删除）
- 邀请码管理（admin 及以上；状态分「已使用」「已过期」「可用」，已使用的不显示删除）
- 文件元数据查看，分页（admin 及以上，只有元数据，无下载入口）
- 系统设置（开放注册、新用户默认配额；admin 只读，仅超管可保存）；设置没加载成功时表单显示的是默认值而不是真实设置，此时提示并禁用保存，避免覆盖真实设置

### 公共访问 (PublicAccess)
- 免登录访问文本
- 免登录下载文件：先探测一次链接状态，失效或被限流时在页面内提示，正常时交给浏览器原生下载

## 环境配置

### 开发环境

Vite 开发服务器会将 `/api` 和 `/ws` 请求代理到后端（`http://127.0.0.1:8000`）。

配置位于 `vite.config.js`：

```js
server: {
  port: 3000,
  proxy: {
    '/api': {
      // 用 127.0.0.1：后端只监听 IPv4，localhost 可能先解析成 ::1 导致代理失败
      target: 'http://127.0.0.1:8000',
      // 保留浏览器的 Host（localhost:3000），后端据此拼出的访问码链接才指向前端页面
      changeOrigin: false,
    },
    '/ws': {
      target: 'ws://127.0.0.1:8000',
      ws: true,
    },
  },
}
```

### 生产环境

生产环境由 frontend 容器（[Dockerfile.frontend](../deployment/docker/Dockerfile.frontend)）在镜像内执行 `npm ci && npm run build`，产物 `dist/` 由容器里的 Nginx 托管，并反代 `/api`、`/ws` 到 backend 容器。Nginx 规则以 [deployment/docker/nginx-common.conf](../deployment/docker/nginx-common.conf) 为准（HTTP 站点 `nginx-docker.conf`、HTTPS 站点 `nginx-https.conf` 都引用它），部署步骤见 [deployment/DEPLOYMENT.md](../deployment/DEPLOYMENT.md)。

> 自己写反代时必须设置 `X-Forwarded-For`，否则后端只能看到 127.0.0.1，所有用户会共用一个限流额度。

## API 请求流程

1. **请求拦截**：自动附加 JWT Token（读本标签页 user store 里的 token，不读 localStorage，避免多标签页串号）
2. **发起请求**：通过 Axios 发送到后端
3. **响应拦截**：
   - 401，或带响应头 `X-Auth-Error: disabled` 的 403（账号被禁用）：登出并跳转登录页（登录 / 注册接口本身、登录页、注册页与公开访问页除外：带着过期 token 打开邀请链接时留在注册页）
   - 普通 403（权限不足）与其他错误：提取 `detail` 字段返回

其他标签页登录、登出或换账号会改写 localStorage 中的 token，本页监听 `storage` 事件后整页重载。启动时只有 401 / 403 才清掉 token，网络错误或 5xx 保留登录状态并在登录页提示「暂时无法连接服务器」。

## WebSocket 连接

- **URL 构建**：根据当前协议（http/https）自动选择 `ws://` 或 `wss://`
- **认证**：Token 通过子协议传递（`new WebSocket(url, ['clipsync.v1', 'bearer.<token>'])`），不放 URL，避免被 access log 记录
- **心跳**：每 30 秒发送一次 ping；发出后 10 秒内没收到任何消息，就认为连接已半断（休眠、切网络后浏览器可能还没察觉）并立即重建
- **重连**：指数退避（1s、2s、4s…，最长 30s），不限次数；网络恢复或页面回到前台时立即重试：已断开的直接重连，看起来仍连着的先发一次 ping 探测，没有回应就重建；重连只用本标签页内存里的 token
- **关闭码**：已连接后被踢下线（账号被禁用或删除）为 1008，停止重连并登出；握手被拒时浏览器只能看到 1006，此时调一次 `/api/auth/me` 确认会话，401 / 禁用 403 则登出、不再重连，其他情况继续重连
- **补拉**：各页面同时订阅 `open`，连接（重新）建立后重拉一次数据，断线期间的变更不会漏掉
- **广播范围**：后端发给该用户的全部连接，触发变更的终端自己也会收到
- **离线发送**：连接未打开时 `send` 直接返回 false，不排队（客户端只发心跳，积压没有意义）

## 状态管理

所有状态通过 Pinia stores 管理，主要包括：

- **用户状态**：token、用户信息、登录状态、配额（已用 + 上传中）、启动时的连接错误提示
- **剪贴板状态**：当前文本、历史记录、历史面板是否打开
- **文件状态**：文件列表、上传进度、是否正在上传
- **访问码状态**：访问码列表（含已撤销 / 已过期标记）
- **管理后台状态**：统计数据、用户列表与分页、邀请码列表、文件元数据列表与分页、系统设置

登出时会清理各 store 的 WebSocket 监听并重置状态，下一个登录的账号看不到上一个账号的数据。

## 路由守卫

- **未登录**：自动跳转到 `/login`
- **已登录访问登录页**：跳转到 `/clipboard`
- **非管理员访问管理后台**：跳转到 `/clipboard`

## 样式规范

- **颜色方案**：深色主题
  - 背景：`#0B0E14` / `#1E293B`
  - 边框：`#334155`
  - 主色：`#38BDF8`（天蓝色）
  - 文字：`#F8FAFC` / `#CBD5E1` / `#94A3B8`
- **字体**：`Inter`, `-apple-system`, `BlinkMacSystemFont`
- **圆角**：`8px` / `12px`
- **过渡**：`all 0.2s`

## 注意事项

1. **协议无关**：前端使用相对路径和动态协议选择，同时支持 HTTP 和 HTTPS
2. **Token 管理**：Token 存在 `localStorage`（刷新后恢复登录、跨标签页感知），请求与 WebSocket 使用本标签页 store 中的副本，分别经 `Authorization` header 与子协议传递
3. **文件上传**：采用分片上传（1MB/片），支持大文件
4. **WebSocket 事件**（只带信号，不含正文）：
   - `clipboard_updated`：保存、恢复或删除历史后触发；剪贴板页静默重拉当前文本，历史面板打开时一并重拉历史
   - `file_added` / `file_deleted`：文件页静默重拉列表；访问码页在 `file_deleted` 时重拉访问码，并静默重拉文件列表（供创建弹窗的文件下拉使用）；侧栏配额由 `Home.vue` 统一刷新（连接重新建立 `open` 时也刷新一次）
   - `access_codes_changed`：创建或撤销访问码后触发，访问码页重拉列表
   - `quota_updated`：超管修改配额后触发，侧栏刷新配额
5. **剪贴板历史**：点击条目把内容填入编辑框（不保存）；「恢复」按钮直接设为当前文本并同步；「删除」按钮删除该条历史
6. **权限控制**：前端隐藏只是体验层，后端必须做最终校验
