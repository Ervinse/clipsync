/**
 * 认证 API
 */
import request from './request'

export default {
  register(data) {
    return request.post('/auth/register', data)
  },

  login(data) {
    return request.post('/auth/login', data)
  },

  // 获取当前用户信息
  me() {
    return request.get('/auth/me')
  },
}
