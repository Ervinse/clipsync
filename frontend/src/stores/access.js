/**
 * 访问码状态管理
 */
import { defineStore } from 'pinia'
import api from '../api'

export const useAccessStore = defineStore('access', {
  state: () => ({
    codes: [],
    isLoading: false,
    // 最近一次（非静默）拉取失败的原因；任何一次拉取成功都会清空。页面据此区分「没有访问码」和「没加载出来」
    loadError: '',
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
     * silent：WS 推送 / 重连触发的后台刷新不切 isLoading，避免列表闪成加载状态
     * 是否已过期随时间变化，由页面按当前时间计算，这里只存后端返回的原始数据
     */
    async fetchCodes({ silent = false } = {}) {
      try {
        if (!silent) this.isLoading = true
        // 后端返回 { items, total }
        const data = await api.access.list()
        this.codes = data?.items || []
        this.loadError = ''
      } catch (error) {
        console.error('获取访问码列表失败:', error)
        if (!silent) this.loadError = error?.message || '加载失败'
        throw error
      } finally {
        if (!silent) this.isLoading = false
      }
    },

    /**
     * 创建访问码
     */
    async createCode(data) {
      try {
        const result = await api.access.create(data)
        await this.fetchCodes({ silent: true }).catch(() => {})
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
      } catch (error) {
        console.error('撤销访问码失败:', error)
        throw error
      }
      // 撤销已成功：刷新失败不影响结果
      await this.fetchCodes({ silent: true }).catch(() => {})
    },
  },
})
