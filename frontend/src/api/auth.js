/**
 * 认证 API
 */
import request from './request'

export default {
  // 注册
  register(data) {
    return request.post('/auth/register', data)
  },

  // 登录
  login(data) {
    return request.post('/auth/login', data)
  },

  // 获取当前用户信息
  me() {
    return request.get('/auth/me')
  },
}
