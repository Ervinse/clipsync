/**
 * 管理后台 API
 */
import request from './request'

export default {
  // 统计数据
  stats() {
    return request.get('/admin/stats')
  },

  // 用户管理
  users: {
    list(skip = 0, limit = 50) {
      return request.get('/admin/users', { params: { skip, limit } })
    },
    updateQuota(id, quotaBytes) {
      return request.patch(`/admin/users/${id}/quota`, { quota_bytes: quotaBytes })
    },
    updateStatus(id, isActive) {
      return request.patch(`/admin/users/${id}/status`, { is_active: isActive })
    },
    delete(id) {
      return request.delete(`/admin/users/${id}`)
    },
  },

  // 邀请码管理
  inviteCodes: {
    create(data) {
      return request.post('/admin/invite-codes', data)
    },
    list() {
      return request.get('/admin/invite-codes')
    },
    delete(id) {
      return request.delete(`/admin/invite-codes/${id}`)
    },
  },

  // 系统设置
  settings: {
    get() {
      return request.get('/admin/settings')
    },
    update(data) {
      return request.patch('/admin/settings', data)
    },
  },

  // 文件管理（仅元数据）
  files: {
    list(skip = 0, limit = 50) {
      return request.get('/admin/files', { params: { skip, limit } })
    },
  },
}
