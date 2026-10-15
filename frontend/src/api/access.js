/**
 * 访问码 API（需登录）：给内容设置访问码、按访问码查看总览
 */
import request from './request'

export default {
  // 设置 / 修改 / 清除访问码：{ target_type: 'clipboard' | 'text' | 'file', target_id, code（null 为清除）, expires_at }
  setCode(data) {
    return request.put('/access-codes', data)
  },

  // 按访问码分组的总览：{ username, groups: [{ code, items }], total }
  overview() {
    return request.get('/access-codes')
  },
}
