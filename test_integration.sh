#!/bin/bash

# ClipSync 集成测试脚本
# 测试前后端是否能正常通信

echo "=== ClipSync 集成测试 ==="
echo

# 1. 测试后端健康检查
echo "1. 测试后端健康检查..."
curl -s http://localhost:8000/api/health || echo "❌ 后端未启动"
echo

# 2. 测试注册接口（需要邀请码）
echo "2. 测试注册接口..."
curl -s -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","password":"testpass123","invite_code":"INVALID"}' \
  | head -c 200
echo
echo

# 3. 测试登录接口（用户不存在）
echo "3. 测试登录接口..."
curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d 'username=testuser&password=testpass123' \
  | head -c 200
echo
echo

# 4. 测试前端页面是否可访问
echo "4. 测试前端页面..."
curl -s -I http://localhost:3000 | head -5
echo

echo "=== 测试完成 ==="
echo
echo "✅ 如果看到响应内容，说明服务正常运行"
echo "📝 完整测试需要："
echo "   1. 后端运行在 http://localhost:8000"
echo "   2. 前端运行在 http://localhost:3000"
echo "   3. 数据库已初始化（alembic upgrade head）"
