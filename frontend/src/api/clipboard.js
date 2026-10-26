/**
 * 云剪切板 API
 */
import request from './request'

export default {
  // 获取当前文本
  get() {
    return request.get('/clipboard')
  },

  // 更新文本：baseVersion 为读取时的版本号，与服务端不一致返回 409；传 null 表示直接覆盖
  update(content, baseVersion = null) {
    return request.put('/clipboard', { content, base_version: baseVersion })
  },

  // 获取历史记录（后端返回全部，最多 HISTORY_KEEP 条，不分页；超过 64KB 的条目 content 为 null，只给开头 preview）
  history() {
    return request.get('/clipboard/history')
  },

  // 读取某条历史的全文
  historyItem(historyId) {
    return request.get(`/clipboard/history/${historyId}`)
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
