/**
 * 快速访问 API（凭「用户名@访问码」进入，免登录）
 */
import quickRequest from './quickRequest'

export default {
  // 换取快速访问凭证：{ access_token, owner_username, code, expires_in }
  login(fullCode) {
    return quickRequest.post('/login', { full_code: fullCode })
  },

  // 该访问码下的全部内容：{ owner_username, code, clipboard, texts, files }
  items() {
    return quickRequest.get('/items')
  },

  getClipboard() {
    return quickRequest.get('/clipboard')
  },

  // baseVersion 为 null 表示不检查冲突、直接覆盖
  updateClipboard(content, baseVersion) {
    return quickRequest.put('/clipboard', { content, base_version: baseVersion })
  },

  getText(id) {
    return quickRequest.get(`/texts/${id}`)
  },

  // data：{ title, content, base_version }
  updateText(id, data) {
    return quickRequest.put(`/texts/${id}`, data)
  },

  // 以 blob 方式下载（要带凭证，不能用裸 <a href>）；onProgress 参数含 loaded / total
  downloadFile(id, onProgress) {
    return quickRequest.get(`/files/${id}/download`, {
      responseType: 'blob',
      timeout: 0,
      onDownloadProgress: onProgress,
    })
  },
}
