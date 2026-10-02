/**
 * 访问码状态管理
 */
import { defineStore } from 'pinia'
import api from '../api'

export const useAccessStore = defineStore('access', {
  state: () => ({
    codes: [],
    isLoading: false,
  }),

  getters: {
    // 按创建时间倒序
    sortedCodes(state) {
      return [...state.codes].sort((a, b) =>
        new Date(b.created_at) - new Date(a.created_at)
      )
    },
  },

  actions: {
    /**
     * 获取访问码列表
     */
    async fetchCodes() {
      try {
        this.isLoading = true
        // 后端返回 { items, total }；是否失效由前端按 is_revoked / expires_at 计算
        const data = await api.access.list()
        const now = Date.now()
        this.codes = (data?.items || []).map(c => {
          // 后端时间为 UTC（不带时区后缀），补 Z 再解析
          const expired = !!c.expires_at && new Date(c.expires_at + 'Z').getTime() <= now
          return {
            ...c,
            expired,
            // 已撤销或已过期都算失效（不能再复制链接 / 撤销）
            is_invalid: c.is_revoked || expired,
          }
        })
      } catch (error) {
        console.error('获取访问码列表失败:', error)
        throw error
      } finally {
        this.isLoading = false
      }
    },

    /**
     * 创建访问码
     */
    async createCode(data) {
      try {
        const result = await api.access.create(data)
        await this.fetchCodes()
        return result
      } catch (error) {
        console.error('创建访问码失败:', error)
        throw error
      }
    },

    /**
     * 撤销访问码
     */
    async revokeCode(id) {
      try {
        await api.access.revoke(id)
        await this.fetchCodes()
      } catch (error) {
        console.error('撤销访问码失败:', error)
        throw error
      }
    },
  },
})
