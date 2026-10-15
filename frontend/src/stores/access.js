/**
 * 访问码状态：按访问码分组的总览 + 设置访问码
 */
import { defineStore } from 'pinia'
import api from '../api'

export const useAccessStore = defineStore('access', {
  state: () => ({
    // [{ code, items: [{ target_type, target_id, label, access_code, access_expires_at }] }]
    groups: [],
    username: '',
    isLoading: false,
    // 最近一次（非静默）拉取失败的原因；页面据此区分「没有访问码」和「没加载出来」
    loadError: '',
  }),

  actions: {
    /**
     * 获取总览
     * silent：WS 推送 / 重连触发的后台刷新不切 isLoading，避免列表闪成加载状态
     * 是否已过期随时间变化，由页面按当前时间计算，这里只存后端返回的原始数据
     */
    async fetchOverview({ silent = false } = {}) {
      try {
        if (!silent) this.isLoading = true
        const data = await api.access.overview()
        this.groups = data?.groups || []
        this.username = data?.username || ''
        this.loadError = ''
      } catch (error) {
        console.error('获取访问码失败:', error)
        if (!silent) this.loadError = error?.message || '加载失败'
        throw error
      } finally {
        if (!silent) this.isLoading = false
      }
    },

    /**
     * 设置 / 修改 / 清除访问码（code 为 null 即清除），返回 { target_type, target_id, access_code, access_expires_at }
     * 总览页靠 access_codes_changed 推送刷新
     */
    async setCode({ targetType, targetId = null, code, expiresAt = null }) {
      return api.access.setCode({
        target_type: targetType,
        target_id: targetId,
        code,
        expires_at: expiresAt,
      })
    },
  },
})
