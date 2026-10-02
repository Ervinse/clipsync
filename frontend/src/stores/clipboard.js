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
    isLoading: false,
    // 历史面板是否打开（由 Clipboard.vue 设置）：打开时收到推送要一并重拉历史
    historyVisible: false,
  }),

  actions: {
    /**
     * 递增刷新序号：之前发出、尚未返回的静默刷新结果作废，避免旧结果覆盖新内容
     */
    _bumpSeq() {
      this._refreshSeq = (this._refreshSeq || 0) + 1
      return this._refreshSeq
    },

    /**
     * 获取当前剪贴板内容
     */
    async fetchCurrent() {
      try {
        this.isLoading = true
        this._bumpSeq()
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
        this._bumpSeq()
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
      this._bumpSeq()
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
    },

    /**
     * 监听 WebSocket 实时更新；连接（重新）建立时也补拉一次，断线期间的变更不会漏掉
     */
    setupWebSocket() {
      if (this._onClipboardUpdated) return
      // 后端推送只带信号（不含正文），收到后静默重新拉取：不切 isLoading，避免编辑框被禁用、失去焦点
      this._onClipboardUpdated = async () => {
        const seq = this._bumpSeq()
        try {
          const data = await api.clipboard.get()
          // 期间又发出了更新的请求或本地已保存：丢弃这次过期结果
          if (seq !== this._refreshSeq) return
          this.currentText = data.content || ''
          // 其他终端保存 / 删除历史后，历史面板打开时一并刷新
          if (this.historyVisible) await this.fetchHistory()
        } catch {
          // 静默刷新失败不打扰用户，下次推送或手动刷新会再同步
        }
      }
      ws.on('clipboard_updated', this._onClipboardUpdated)
      ws.on('open', this._onClipboardUpdated)
    },

    /**
     * 清理监听器
     */
    cleanupWebSocket() {
      if (this._onClipboardUpdated) {
        ws.off('clipboard_updated', this._onClipboardUpdated)
        ws.off('open', this._onClipboardUpdated)
        this._onClipboardUpdated = null
      }
    },
  },
})
