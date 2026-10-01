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

    // 文本访问码
    textCodes(state) {
      return state.codes.filter(c => c.target_type === 'text')
    },

    // 文件访问码
    fileCodes(state) {
      return state.codes.filter(c => c.target_type === 'file')
    },
  },

  actions: {
    /**
     * 获取访问码列表
     */
    async fetchCodes() {
      try {
        this.isLoading = true
        const data = await api.access.list()
        this.codes = data || []
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
        this.codes = this.codes.filter(c => c.id !== id)
      } catch (error) {
        console.error('撤销访问码失败:', error)
        throw error
      }
    },

    /**
     * 生成访问链接
     */
    generateLink(code) {
      const protocol = window.location.protocol
      const host = window.location.host
      return `${protocol}//${host}/access/${code}`
    },
  },
})
