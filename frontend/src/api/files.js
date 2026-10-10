/**
 * 文件 API
 */
import request from './request'

export default {
  // 初始化上传
  initUpload(data) {
    return request.post('/files/upload/init', data)
  },

  // 上传分片
  uploadChunk(uploadId, chunkIndex, chunkData) {
    const formData = new FormData()
    formData.append('upload_id', uploadId)
    formData.append('chunk_index', chunkIndex)
    formData.append('chunk_data', chunkData)

    return request.post('/files/upload/chunk', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },

  // 完成上传：服务端要把分片合并成一个文件，大文件在慢磁盘上可能超过默认的 30 秒；
  // 与 Nginx /api 的读超时（600 秒）一致，超时后上传其实已成功却报失败，用户重试会得到重复文件
  completeUpload(uploadId) {
    return request.post('/files/upload/complete', { upload_id: uploadId }, { timeout: 600000 })
  },

  // 取消进行中的上传：删除会话并释放其占用的配额
  cancelUpload(uploadId) {
    return request.delete(`/files/upload/${uploadId}`)
  },

  // 获取文件列表
  list() {
    return request.get('/files')
  },

  // 下载文件：必须带 Authorization 头，不能用裸 <a href>，因此以 blob 方式获取
  download(fileId) {
    return request.get(`/files/${fileId}/download`, {
      responseType: 'blob',
      timeout: 0, // 大文件下载不设超时
    })
  },

  // 删除文件
  delete(fileId) {
    return request.delete(`/files/${fileId}`)
  },
}
