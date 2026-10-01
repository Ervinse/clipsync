/**
 * 剪贴板状态管理
 */
import { defineStore } from 'pinia'
import api from '../api'
import ws from '../utils/websocket'

export const useClipboardStore = defineStore('clipboard', {
  state: () => ({
    currentText: '',
    history: [],
    historyTotal: 0,
    isLoading: false,
  }),

  actions: {
    /**
     * 获取当前剪贴板内容
     */
    async fetchCurrent() {
      try {
        this.isLoading = true
        const data = await api.clipboard.get()
        this.currentText = data.content || ''
      } catch (error) {
        console.error('获取剪贴板内容失败:', error)
        throw error
      } finally {
        this.isLoading = false
      }
    },

    /**
     * 更新剪贴板内容
     */
    async updateText(content) {
      try {
        await api.clipboard.update(content)
        this.currentText = content
      } catch (error) {
        console.error('更新剪贴板失败:', error)
        throw error
      }
    },

    /**
     * 获取历史记录
     */
    async fetchHistory() {
      try {
        const data = await api.clipboard.history()
        this.history = data.items || []
        this.historyTotal = data.total || 0
      } catch (error) {
        console.error('获取历史记录失败:', error)
        throw error
      }
    },

    /**
     * 恢复某条历史为当前文本：后端会把原当前文本归档，所以恢复后要重新拉历史
     */
    async restoreHistory(historyId) {
      const data = await api.clipboard.restoreHistory(historyId)
      this.currentText = data.content || ''
      await this.fetchHistory()
      return this.currentText
    },

    /**
     * 删除某条历史
     */
    async deleteHistory(historyId) {
      await api.clipboard.deleteHistory(historyId)
      this.history = this.history.filter(item => item.id !== historyId)
      this.historyTotal = Math.max(0, this.historyTotal - 1)
    },

    /**
     * 监听 WebSocket 实时更新
     */
    setupWebSocket() {
      // 后端推送只带信号（不含正文），收到后重新拉取当前文本
      this._onClipboardUpdated = () => {
        this.fetchCurrent().catch(() => {})
      }
      ws.on('clipboard_updated', this._onClipboardUpdated)
    },

    /**
     * 清理监听器
     */
    cleanupWebSocket() {
      if (this._onClipboardUpdated) {
        ws.off('clipboard_updated', this._onClipboardUpdated)
        this._onClipboardUpdated = null
      }
    },
  },
})
