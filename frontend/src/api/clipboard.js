/**
 * 剪贴板 API
 */
import request from './request'

export default {
  // 获取当前文本
  get() {
    return request.get('/clipboard')
  },

  // 更新文本
  update(content) {
    return request.put('/clipboard', { content })
  },

  // 获取历史记录
  history(skip = 0, limit = 20) {
    return request.get('/clipboard/history', { params: { skip, limit } })
  },
}
