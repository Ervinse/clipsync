/**
 * 管理后台状态管理
 */
import { defineStore } from 'pinia'
import api from '../api'

export const useAdminStore = defineStore('admin', {
  state: () => ({
    stats: null,
    users: [],
    inviteCodes: [],
    settings: null,
    files: [],
    isLoading: false,
  }),

  getters: {
    // 活跃用户数
    activeUserCount(state) {
      return state.users.filter(u => u.is_active).length
    },

    // 总存储使用量
    totalStorageUsed(state) {
      return state.users.reduce((sum, u) => sum + (u.used_bytes || 0), 0)
    },

    // 有效邀请码数量（used_at 非空即已用过，使用者被删除后 used_by 会置空）
    validInviteCount(state) {
      return state.inviteCodes.filter(c => !c.used_by && !c.used_at).length
    },
  },

  actions: {
    /**
     * 获取统计数据
     */
    async fetchStats() {
      try {
        const data = await api.admin.stats()
        this.stats = data
      } catch (error) {
        console.error('获取统计数据失败:', error)
        throw error
      }
    },

    /**
     * 获取用户列表
     */
    async fetchUsers(skip = 0, limit = 50) {
      try {
        this.isLoading = true
        // 后端返回 { items, total }
        const data = await api.admin.users.list(skip, limit)
        this.users = data?.items || []
      } catch (error) {
        console.error('获取用户列表失败:', error)
        throw error
      } finally {
        this.isLoading = false
      }
    },

    /**
     * 更新用户配额
     */
    async updateUserQuota(userId, quotaBytes) {
      try {
        await api.admin.users.updateQuota(userId, quotaBytes)
        await this.fetchUsers()
      } catch (error) {
        console.error('更新配额失败:', error)
        throw error
      }
    },

    /**
     * 更新用户状态
     */
    async updateUserStatus(userId, isActive) {
      try {
        await api.admin.users.updateStatus(userId, isActive)
        await this.fetchUsers()
      } catch (error) {
        console.error('更新用户状态失败:', error)
        throw error
      }
    },

    /**
     * 删除用户
     */
    async deleteUser(userId) {
      try {
        await api.admin.users.delete(userId)
        this.users = this.users.filter(u => u.id !== userId)
      } catch (error) {
        console.error('删除用户失败:', error)
        throw error
      }
    },

    /**
     * 获取邀请码列表
     */
    async fetchInviteCodes() {
      try {
        const data = await api.admin.inviteCodes.list()
        this.inviteCodes = data?.items || []
      } catch (error) {
        console.error('获取邀请码列表失败:', error)
        throw error
      }
    },

    /**
     * 创建邀请码
     */
    async createInviteCode(data) {
      try {
        const result = await api.admin.inviteCodes.create(data)
        await this.fetchInviteCodes()
        return result
      } catch (error) {
        console.error('创建邀请码失败:', error)
        throw error
      }
    },

    /**
     * 删除邀请码
     */
    async deleteInviteCode(id) {
      try {
        await api.admin.inviteCodes.delete(id)
        this.inviteCodes = this.inviteCodes.filter(c => c.id !== id)
      } catch (error) {
        console.error('删除邀请码失败:', error)
        throw error
      }
    },

    /**
     * 获取系统设置
     */
    async fetchSettings() {
      try {
        const data = await api.admin.settings.get()
        this.settings = data
      } catch (error) {
        console.error('获取系统设置失败:', error)
        throw error
      }
    },

    /**
     * 更新系统设置
     */
    async updateSettings(data) {
      try {
        await api.admin.settings.update(data)
        await this.fetchSettings()
      } catch (error) {
        console.error('更新系统设置失败:', error)
        throw error
      }
    },

    /**
     * 获取文件元数据列表
     */
    async fetchFiles(skip = 0, limit = 50) {
      try {
        // 仅元数据（无下载入口）
        const data = await api.admin.files.list(skip, limit)
        this.files = data?.items || []
      } catch (error) {
        console.error('获取文件列表失败:', error)
        throw error
      }
    },
  },
})
