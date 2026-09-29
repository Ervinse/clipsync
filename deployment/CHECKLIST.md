# ClipSync 部署检查清单

使用此清单确保部署过程中不遗漏关键步骤。

## 部署前准备

### 服务器环境
- [ ] 服务器系统：Ubuntu 20.04+ / CentOS 7+
- [ ] CPU: 2核+，内存: 2GB+，磁盘: 20GB+
- [ ] 已安装 Python 3.9+
- [ ] 已安装 Node.js 16+
- [ ] 已安装 MySQL 8.0+
- [ ] 已安装 Nginx 1.18+
- [ ] 已安装 Git

### 网络与域名（HTTPS 部署）
- [ ] 有公网 IP 或域名
- [ ] 防火墙已开放 80/443 端口
- [ ] DNS 记录已配置
- [ ] 已准备 SSL 证书（Let's Encrypt 或购买）

### 数据库
- [ ] MySQL 已启动并运行
- [ ] 已创建数据库和用户
- [ ] 已测试数据库连接

## 配置文件

### 后端配置（backend/.env）
- [ ] 已复制 `.env.production.example` 为 `.env`
- [ ] **必填项**：
  - [ ] `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`
  - [ ] `JWT_SECRET_KEY`（用 `openssl rand -hex 32` 生成）
  - [ ] `CORS_ORIGINS`（前端域名或 IP）
  - [ ] `DEPLOY_SCHEME`（http 或 https）
- [ ] **安全项**（HTTPS 环境）：
  - [ ] `COOKIE_SECURE=true`
  - [ ] `HSTS_ENABLED=true`
- [ ] **可选项**：
  - [ ] `DEFAULT_USER_QUOTA`（默认配额）
  - [ ] `JWT_EXPIRE_MINUTES`（Token 有效期）
  - [ ] 限流配置

### Nginx 配置
- [ ] 已复制 `deployment/nginx/clipsync.conf` 到 `/etc/nginx/sites-available/`
- [ ] 已更新配置中的路径
- [ ] **HTTPS**：已更新 `server_name` 和 SSL 证书路径
- [ ] 已创建软链接到 `sites-enabled/`
- [ ] 已测试配置：`sudo nginx -t`

### Systemd 配置
- [ ] 已复制 `deployment/systemd/clipsync.service` 到 `/etc/systemd/system/`
- [ ] 已更新配置中的路径和用户
- [ ] 已执行：`sudo systemctl daemon-reload`

## 部署执行

### 自动化部署
- [ ] 已将项目上传到 `/var/www/clipsync`
- [ ] 已配置 `.env` 文件
- [ ] 已执行：`sudo bash deployment/scripts/deploy.sh`
- [ ] 部署脚本执行成功，无错误

### 或手动部署
- [ ] 已创建虚拟环境：`python3 -m venv venv`
- [ ] 已安装后端依赖：`pip install -r requirements.txt`
- [ ] 已执行数据库迁移：`alembic upgrade head`
- [ ] 已创建超级管理员：`python -m scripts.create_superadmin`
- [ ] 已安装前端依赖：`npm install`
- [ ] 已构建前端：`npm run build`
- [ ] 已设置文件权限：`chown -R www-data:www-data /var/www/clipsync`

## 服务启动

- [ ] 已启动 ClipSync：`sudo systemctl start clipsync`
- [ ] 已启用开机自启：`sudo systemctl enable clipsync`
- [ ] 已重启 Nginx：`sudo systemctl restart nginx`
- [ ] ClipSync 状态正常：`sudo systemctl status clipsync`
- [ ] Nginx 状态正常：`sudo systemctl status nginx`

## 功能验证

### API 测试
- [ ] 健康检查通过：`curl http://localhost:8000/api/health`
- [ ] 返回 `{"status":"ok"}`

### 前端测试
- [ ] 前端页面可访问：`curl http://your-domain.com`
- [ ] 浏览器能打开登录页
- [ ] 静态资源加载正常（检查浏览器控制台）

### 功能测试
- [ ] 使用超级管理员账号登录成功
- [ ] 能访问管理后台
- [ ] 能创建邀请码
- [ ] 能注册新用户
- [ ] 能更新剪贴板文本
- [ ] 能上传文件
- [ ] 能创建访问码
- [ ] WebSocket 连接正常（查看浏览器 Network 标签）

### HTTPS 验证（如启用）
- [ ] HTTPS 页面可访问
- [ ] 浏览器地址栏显示锁图标
- [ ] SSL 证书有效
- [ ] HTTP 重定向到 HTTPS（如配置）
- [ ] WebSocket 使用 wss:// 协议

## 定时任务

- [ ] Cron 任务已配置：`ls /etc/cron.d/clipsync`
- [ ] 备份脚本可执行：`sudo bash deployment/scripts/backup_database.sh`
- [ ] 清理脚本可执行：`sudo bash deployment/scripts/cleanup_expired.sh`
- [ ] 日志目录存在：`ls /var/log/clipsync/`

## 监控与日志

- [ ] 能查看应用日志：`sudo journalctl -u clipsync -f`
- [ ] 能查看 Nginx 日志：`sudo tail -f /var/log/nginx/access.log`
- [ ] 能查看备份日志：`sudo tail -f /var/log/clipsync/backup.log`
- [ ] 健康检查脚本运行正常：`sudo bash deployment/scripts/health_check.sh`

## 安全加固

- [ ] 已更换所有默认密码
- [ ] JWT 密钥是随机生成的（非示例值）
- [ ] 数据库只监听 localhost
- [ ] 防火墙已配置：`sudo ufw status`
- [ ] SSH 密钥认证已启用（可选）
- [ ] 已禁用 root 远程登录（可选）
- [ ] 已设置 fail2ban（可选）

## 备份验证

- [ ] 手动执行一次备份：`sudo bash deployment/scripts/backup_database.sh`
- [ ] 备份文件已生成：`ls /var/backups/clipsync/database/`
- [ ] 备份文件不为空
- [ ] 能解压备份文件：`gunzip -t <backup-file>`

## 性能优化（可选）

- [ ] 已根据 CPU 核心数调整 Uvicorn workers
- [ ] 已优化 MySQL 配置（innodb_buffer_pool_size 等）
- [ ] 已配置 Nginx 静态资源缓存
- [ ] 已设置合理的文件上传大小限制

## 文档与记录

- [ ] 已记录超级管理员账号（安全存储）
- [ ] 已记录数据库密码（安全存储）
- [ ] 已记录 JWT 密钥（安全存储）
- [ ] 已记录服务器 IP/域名
- [ ] 已记录 SSL 证书过期时间（如使用）
- [ ] 已记录紧急联系人和操作流程

## 上线后检查

### 第一天
- [ ] 检查服务运行状态
- [ ] 检查日志有无异常
- [ ] 检查资源使用（CPU、内存、磁盘）
- [ ] 检查用户注册和登录功能
- [ ] 检查 WebSocket 连接稳定性

### 第一周
- [ ] 检查数据库备份是否自动执行
- [ ] 检查过期数据清理是否正常
- [ ] 检查磁盘空间是否充足
- [ ] 检查访问日志是否正常
- [ ] 收集用户反馈

### 定期维护（每月）
- [ ] 更新系统软件包
- [ ] 检查 SSL 证书有效期
- [ ] 检查备份文件可用性
- [ ] 检查日志是否有异常模式
- [ ] 检查存储空间使用趋势

## 常见问题排查

如果遇到问题，按以下顺序检查：

1. **服务无法启动**
   - 查看日志：`sudo journalctl -u clipsync -n 50`
   - 检查配置：`.env` 文件语法
   - 检查数据库：能否连接
   - 检查权限：uploads 目录权限

2. **前端无法访问**
   - 检查 Nginx：`sudo nginx -t`
   - 查看错误日志：`sudo tail -f /var/log/nginx/error.log`
   - 检查防火墙：端口是否开放
   - 检查 DNS：域名是否解析

3. **WebSocket 连接失败**
   - 检查 Nginx WebSocket 配置
   - 确认 Upgrade 和 Connection header
   - 检查超时设置
   - 查看浏览器控制台错误

4. **数据库连接失败**
   - 确认 MySQL 运行：`sudo systemctl status mysql`
   - 测试连接：`mysql -u clipsync -p clipsync`
   - 检查 .env 配置

5. **文件上传失败**
   - 检查 uploads 目录权限
   - 检查磁盘空间
   - 检查 Nginx client_max_body_size
   - 检查用户配额

## 紧急回滚

如果部署出现严重问题，按以下步骤回滚：

1. 停止服务：`sudo systemctl stop clipsync`
2. 恢复数据库备份（见 DEPLOY.md）
3. 切换到上一个版本的代码
4. 重启服务：`sudo systemctl start clipsync`

## 完成

- [ ] 所有检查项已完成
- [ ] 部署文档已更新
- [ ] 团队已通知部署完成
- [ ] 监控已设置（如有）

---

**部署日期**：____________________

**部署人员**：____________________

**备注**：

