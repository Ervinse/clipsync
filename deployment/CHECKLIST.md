# ClipSync 部署检查清单

只列勾选项。系统要求、具体命令与故障排查以 [DEPLOY.md](DEPLOY.md) 为准。

## 部署前准备

### 服务器环境（版本要求见 DEPLOY.md「系统要求」）
- [ ] Ubuntu 22.04 / 24.04、Debian 12，或 Rocky Linux / AlmaLinux / RHEL 9+（CentOS 7 / 8 不支持，改用 Docker）
- [ ] Python 3.12+（Rocky 9 上为 `python3.12` 包，不要改系统的 `python3`）
- [ ] Node.js 20.19+ 或 22.12+（Vite 8 的要求；不要用系统源自带的旧版 Node）
- [ ] RHEL 系：已安装 `cronie`（并启用 `crond`）与 `policycoreutils-python-utils`
- [ ] MySQL 8.0+
- [ ] Nginx 1.18+
- [ ] Git

### 网络与域名（HTTPS 部署）
- [ ] 有公网 IP 或域名，DNS 已配置
- [ ] 防火墙已开放 80/443
- [ ] 已准备 SSL 证书（Let's Encrypt 或购买）

### 数据库（`deploy.sh` 不会建库建用户，需手动完成）
- [ ] MySQL 已启动
- [ ] 已创建 `clipsync` 库（utf8mb4）和专用用户
- [ ] 已测试数据库连接

## 配置文件

### 后端配置（backend/.env）
- [ ] 已复制 `deployment/.env.production.example` 为 `backend/.env`，权限设为 600
- [ ] **必填项**：
  - [ ] `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`
  - [ ] `JWT_SECRET`（`openssl rand -hex 32` 生成，至少 32 位；示例值或过短后端拒绝启动）
  - [ ] `CORS_ORIGINS`（前端域名或 IP，不能用 `*`）
- [ ] **HTTPS 环境**：`HSTS_ENABLED=true`
- [ ] **可选项**：`DEFAULT_QUOTA_BYTES`、`MAX_FILE_BYTES`、`CHUNK_SIZE`、`MAX_UPLOAD_SESSIONS_PER_USER`、`UPLOAD_SESSION_TTL_HOURS`、`HISTORY_KEEP`、`JWT_ALGORITHM`、`JWT_EXPIRE_MINUTES`

### Nginx 配置
- [ ] 已去掉发行版自带的默认站点（否则会抢走 80 端口的请求）：Debian 系删除 `/etc/nginx/sites-enabled/default`；RHEL 系注释掉 `/etc/nginx/nginx.conf` 里的 `server { }` 块
- [ ] HTTP 阶段使用 `deployment/nginx/clipsync.conf`（Debian 系装在 `sites-available/clipsync`，RHEL 系装在 `conf.d/clipsync.conf`）
- [ ] HTTPS 阶段改用 `deployment/nginx/clipsync-https.conf`，并已改 `server_name` 和证书路径
- [ ] `sudo nginx -t` 通过

### Systemd 配置
- [ ] 已核对 `/etc/systemd/system/clipsync.service` 中的路径和用户（Debian 系 `www-data` + `mysql.service`，RHEL 系 `nginx` + `mysqld.service`）
- [ ] 保持 `--workers 1`、`--host 127.0.0.1`（不要改成多 worker）

### SELinux（RHEL 系，`deploy.sh` 自动配置）
- [ ] `getenforce` 为 `Enforcing`（不要关掉 SELinux）
- [ ] `getsebool httpd_can_network_connect` 为 `on`
- [ ] `ls -Z /var/www/clipsync/backend/venv/bin/uvicorn` 为 `bin_t`

## 部署执行

### 自动化部署
- [ ] 项目已放到 `/var/www/clipsync`
- [ ] `backend/.env` 已配置
- [ ] `sudo bash deployment/scripts/deploy.sh` 执行成功

### 或手动部署
- [ ] 已创建虚拟环境并 `pip install -r requirements.txt`
- [ ] 已执行 `alembic upgrade head`
- [ ] 已执行 `python -m scripts.create_superadmin`
- [ ] 已执行 `npm ci && npm run build`
- [ ] 已设置权限：`chown -R www-data:www-data /var/www/clipsync`（RHEL 系为 `nginx:nginx`）
- [ ] RHEL 系：已按 DEPLOY.md 第 5 步配置 SELinux（`setsebool`、`semanage fcontext`、`restorecon`）

## 服务启动

- [ ] `sudo systemctl enable --now clipsync`
- [ ] `sudo systemctl enable nginx && sudo systemctl restart nginx`（RHEL 系装完 Nginx 不会自动启动，也不会开机自启）
- [ ] `systemctl status clipsync` 与 `systemctl status nginx` 均正常
- [ ] RHEL 系：`firewall-cmd` 已放行 http / https

## 功能验证

以下都是上线后的手动检查。生产环境不运行 `pytest`（原因见 DEPLOY.md「7. 验证」）。

### API 检查
- [ ] 健康检查：`curl http://127.0.0.1:8000/` 返回 `{"status":"ok",...}`（后端没有 `/api/health`）

### 前端检查
- [ ] 浏览器能打开登录页，控制台无资源加载错误

### 功能检查（手动）
- [ ] 超级管理员登录成功，能进入管理后台
- [ ] 能创建邀请码，并用它注册新用户
- [ ] 能更新剪贴板文本，另一终端实时同步
- [ ] 能上传、下载文件
- [ ] 能创建访问码，并在未登录的浏览器里打开 `/access/<code>`
- [ ] WebSocket 连接正常（浏览器 Network 标签可见 `/ws`）

### HTTPS 验证（如启用）
- [ ] HTTPS 页面可访问，证书有效
- [ ] HTTP 自动跳转到 HTTPS
- [ ] WebSocket 使用 `wss://`
- [ ] `/api/...` 的响应头包含 `Strict-Transport-Security`（HSTS 由后端下发，静态页面不带；例如 `curl -sI https://your-domain.com/api/auth/me | grep -i strict`）

## 定时任务

- [ ] `/etc/cron.d/clipsync` 已存在
- [ ] `sudo bash deployment/scripts/backup_database.sh` 能产出**非空**备份
- [ ] `sudo bash deployment/scripts/cleanup_expired.sh` 执行无报错
- [ ] `/var/log/clipsync/` 目录存在

## 监控与日志

- [ ] 能查看应用日志：`sudo journalctl -u clipsync -f`
- [ ] 能查看 Nginx 日志
- [ ] `sudo bash deployment/scripts/health_check.sh` 能完整跑完所有检查项

## 安全加固

- [ ] 已更换所有默认密码
- [ ] `JWT_SECRET` 为随机生成值
- [ ] MySQL 只监听 localhost
- [ ] 后端 8000 端口只监听 127.0.0.1
- [ ] 防火墙已配置：`sudo ufw status`（RHEL 系 `sudo firewall-cmd --list-all`）
- [ ] SSH 密钥认证、禁用 root 远程登录、fail2ban（可选）

## 备份验证

- [ ] 手动执行一次备份
- [ ] 备份文件已生成且不为空：`ls -lh /var/backups/clipsync/database/`
- [ ] 能解压备份文件：`gunzip -t <backup-file>`
- [ ] 已单独备份文件存储目录 `backend/storage/`（数据库备份不包含上传的文件）

## 上线后检查

### 第一天
- [ ] 服务运行状态、日志、资源使用正常
- [ ] 注册、登录、WebSocket 连接稳定

### 第一周
- [ ] 数据库备份自动执行，备份非空
- [ ] 过期数据清理正常
- [ ] 磁盘空间充足

### 定期维护（每月）
- [ ] 更新系统软件包
- [ ] 检查 SSL 证书有效期
- [ ] 检查备份文件可用性
- [ ] 检查存储空间使用趋势

## 文档与记录

- [ ] 已安全存储：超级管理员账号、数据库密码、JWT 密钥
- [ ] 已记录服务器 IP/域名、SSL 证书过期时间
- [ ] 已记录紧急联系人，熟悉回滚流程（见 DEPLOY.md「回滚」）

---

**部署日期**：____________________

**部署人员**：____________________

**备注**：
