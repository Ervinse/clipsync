# ClipSync 前端

基于 Vue 3 + Vite 构建的跨设备剪贴板与文件同步前端应用。

## 技术栈

- **Vue 3**：组合式 API
- **Vite**：构建工具
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
│   └── websocket.js # WebSocket 管理器
├── App.vue         # 根组件
└── main.js         # 入口文件
```

## 功能模块

### 认证 (Login/Register)
- 用户登录/注册
- JWT Token 管理
- 路由守卫

### 剪贴板 (Clipboard)
- 实时文本同步
- 历史记录查看
- WebSocket 推送

### 文件管理 (Files)
- 分片上传（1MB/片）
- 上传进度显示
- 文件列表与下载
- 配额显示

### 访问码 (AccessCodes)
- 创建文本/文件访问码
- 设置过期时间
- 链接复制与撤销

### 管理后台 (Admin)
- 系统统计（admin 及以上）
- 用户列表（admin 及以上可看；改配额 / 禁用 / 删除按钮仅超管可见，与后端权限一致）
- 邀请码管理（admin 及以上）
- 文件元数据查看（admin 及以上，只有元数据，无下载入口）
- 系统设置（开放注册、新用户默认配额；admin 只读，仅超管可保存）

### 公共访问 (PublicAccess)
- 免登录访问文本
- 免登录下载文件

## 环境配置

### 开发环境

Vite 开发服务器会将 `/api` 和 `/ws` 请求代理到后端（默认 `http://localhost:8000`）。

配置位于 `vite.config.js`：

```js
server: {
  port: 3000,
  proxy: {
    '/api': {
      target: 'http://localhost:8000',
      // 保留浏览器的 Host（localhost:3000），后端据此拼出的访问码链接才指向前端页面
      changeOrigin: false,
    },
    '/ws': {
      target: 'ws://localhost:8000',
      ws: true,
    },
  },
}
```

### 生产环境

生产环境把 `npm run build` 的产物 `dist/` 交给 Nginx 托管，并反代 `/api`、`/ws`。Nginx 配置以 [deployment/nginx/clipsync.conf](../deployment/nginx/clipsync.conf)（HTTP）和 [deployment/nginx/clipsync-https.conf](../deployment/nginx/clipsync-https.conf)（HTTPS）为准，部署步骤见 [deployment/DEPLOY.md](../deployment/DEPLOY.md)。

> 自己写反代时必须设置 `X-Forwarded-For`，否则后端只能看到 127.0.0.1，所有用户会共用一个限流额度。

## API 请求流程

1. **请求拦截**：自动附加 JWT Token（从 `localStorage` 读取）
2. **发起请求**：通过 Axios 发送到后端
3. **响应拦截**：
   - 401 错误：自动跳转到登录页
   - 其他错误：提取 `detail` 字段返回

## WebSocket 连接

- **URL 构建**：根据当前协议（http/https）自动选择 `ws://` 或 `wss://`
- **认证**：Token 通过子协议传递（`new WebSocket(url, ['clipsync.v1', 'bearer.<token>'])`），不放 URL，避免被 access log 记录
- **心跳**：每 30 秒发送一次 ping
- **重连**：断线后最多尝试 5 次，间隔 3 秒
- **消息队列**：离线时消息会加入队列，连接恢复后自动发送

## 状态管理

所有状态通过 Pinia stores 管理，主要包括：

- **用户状态**：登录状态、用户信息、配额
- **剪贴板状态**：当前文本、历史记录
- **文件状态**：文件列表、上传进度
- **访问码状态**：访问码列表
- **管理后台状态**：统计数据、用户列表、邀请码列表

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
2. **Token 管理**：Token 存储在 `localStorage`，通过 `Authorization` header 传递
3. **文件上传**：采用分片上传（1MB/片），支持大文件
4. **WebSocket 事件**：
   - `clipboard_updated`：剪贴板已更新（只带 `updated_at` 信号，前端收到后重新拉取当前文本）
   - `file_added` / `file_deleted`：文件页收到后重新拉取文件列表
5. **剪贴板历史**：点击条目把内容填入编辑框（不保存）；「恢复」按钮直接设为当前文本并同步；「删除」按钮删除该条历史
6. **权限控制**：前端隐藏只是体验层，后端必须做最终校验
