/**
 * 访问码 API
 */
import request from './request'

export default {
  // 创建访问码
  create(data) {
    return request.post('/access-codes', data)
  },

  // 获取访问码列表
  list() {
    return request.get('/access-codes')
  },

  // 撤销访问码
  revoke(id) {
    return request.delete(`/access-codes/${id}`)
  },

  // 免登录访问文本（公开接口）
  accessText(code) {
    return request.get(`/access/${code}`)
  },
}
