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

  // 获取历史记录（后端返回全部，最多 HISTORY_KEEP 条，不分页）
  history() {
    return request.get('/clipboard/history')
  },

  // 把某条历史恢复为当前文本（后端会把旧的当前文本归档并广播）
  restoreHistory(historyId) {
    return request.post(`/clipboard/history/${historyId}/restore`)
  },

  // 删除某条历史
  deleteHistory(historyId) {
    return request.delete(`/clipboard/history/${historyId}`)
  },
}
