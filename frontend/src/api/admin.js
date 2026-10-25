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

  // 邀请码批次：每次生成是一批（1 个也算），批次带备注
  inviteBatches: {
    // data: { count, expires_at, note }，返回新批次 { id, note, created_by_username, created_at, codes }
    create(data) {
      return request.post('/admin/invite-batches', data)
    },
    // 返回 { items, total }，按创建时间倒序，每批带全部邀请码
    list() {
      return request.get('/admin/invite-batches')
    },
    updateNote(id, note) {
      return request.patch(`/admin/invite-batches/${id}`, { note })
    },
    // 删除批次里未使用的码，返回 { deleted, batch_deleted }
    deleteUnused(id) {
      return request.delete(`/admin/invite-batches/${id}`)
    },
  },

  // 单个邀请码
  inviteCodes: {
    // 批量修改有效期（单个也走这里）：只能改未使用的码
    updateExpiry(ids, expiresAt) {
      return request.patch('/admin/invite-codes/expiry', { ids, expires_at: expiresAt })
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
