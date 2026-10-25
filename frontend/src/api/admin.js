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
    // role: 'user' | 'admin'（仅超管）
    updateRole(id, role) {
      return request.patch(`/admin/users/${id}/role`, { role })
    },
    delete(id) {
      return request.delete(`/admin/users/${id}`)
    },
  },

  // 查看用户的文本内容（仅超管，只读）
  userContent: {
    clipboard(userId) {
      return request.get(`/admin/users/${userId}/clipboard`)
    },
    clipboardHistory(userId) {
      return request.get(`/admin/users/${userId}/clipboard/history`)
    },
    clipboardHistoryItem(userId, historyId) {
      return request.get(`/admin/users/${userId}/clipboard/history/${historyId}`)
    },
    texts(userId) {
      return request.get(`/admin/users/${userId}/texts`)
    },
    text(userId, textId) {
      return request.get(`/admin/users/${userId}/texts/${textId}`)
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

  // 系统信息：运行的版本、启动时间与部署记录（admin 及以上可看）
  deployInfo() {
    return request.get('/admin/deploy-info')
  },

  // 部署记录备注（仅超管可改）
  deployments: {
    updateNote(id, note) {
      return request.patch(`/admin/deployments/${id}`, { note })
    },
  },

  // 文件管理（仅元数据）
  files: {
    list(skip = 0, limit = 50) {
      return request.get('/admin/files', { params: { skip, limit } })
    },
  },
}
