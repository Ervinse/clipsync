/**
 * 管理后台状态管理
 */
import { defineStore } from 'pinia'
import api from '../api'

// 列表每页条数（后端上限 100）
export const PAGE_SIZE = 50

export const useAdminStore = defineStore('admin', {
  state: () => ({
    stats: null,
    users: [],
    usersTotal: 0,
    usersSkip: 0,
    inviteCodes: [],
    settings: null,
    files: [],
    filesTotal: 0,
    filesSkip: 0,
    isLoading: false,
  }),

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
     * 获取用户列表（分页）；不传 skip 时刷新当前页
     */
    async fetchUsers(skip = this.usersSkip) {
      try {
        this.isLoading = true
        // 后端返回 { items, total }
        const data = await api.admin.users.list(skip, PAGE_SIZE)
        this.users = data?.items || []
        this.usersTotal = data?.total || 0
        this.usersSkip = skip
        // 删除后当前页可能空了：退回上一页
        if (this.users.length === 0 && skip > 0) {
          await this.fetchUsers(Math.max(0, skip - PAGE_SIZE))
        }
      } catch (error) {
        console.error('获取用户列表失败:', error)
        throw error
      } finally {
        this.isLoading = false
      }
    },

    /**
     * 用户变更后刷新受影响的数据：统计、用户列表、文件列表（删除用户会带走其文件）
     * 刷新失败不影响已成功的操作
     */
    async _refreshAfterUserChange() {
      await Promise.allSettled([this.fetchStats(), this.fetchUsers(), this.fetchFiles()])
    },

    /**
     * 更新用户配额
     */
    async updateUserQuota(userId, quotaBytes) {
      try {
        await api.admin.users.updateQuota(userId, quotaBytes)
      } catch (error) {
        console.error('更新配额失败:', error)
        throw error
      }
      await this.fetchUsers().catch(() => {})
    },

    /**
     * 更新用户状态
     */
    async updateUserStatus(userId, isActive) {
      try {
        await api.admin.users.updateStatus(userId, isActive)
      } catch (error) {
        console.error('更新用户状态失败:', error)
        throw error
      }
      await this._refreshAfterUserChange()
    },

    /**
     * 删除用户
     */
    async deleteUser(userId) {
      try {
        await api.admin.users.delete(userId)
      } catch (error) {
        console.error('删除用户失败:', error)
        throw error
      }
      await this._refreshAfterUserChange()
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
     * 获取文件元数据列表（分页，仅元数据、无下载入口）；不传 skip 时刷新当前页
     */
    async fetchFiles(skip = this.filesSkip) {
      try {
        const data = await api.admin.files.list(skip, PAGE_SIZE)
        this.files = data?.items || []
        this.filesTotal = data?.total || 0
        this.filesSkip = skip
        if (this.files.length === 0 && skip > 0) {
          await this.fetchFiles(Math.max(0, skip - PAGE_SIZE))
        }
      } catch (error) {
        console.error('获取文件列表失败:', error)
        throw error
      }
    },
  },
})
