/**
 * 云剪切板状态管理
 */
import { defineStore } from 'pinia'
import api from '../api'
import ws from '../utils/websocket'

export const useClipboardStore = defineStore('clipboard', {
  state: () => ({
    currentText: '',
    // 服务端版本号：保存时带上，内容已在别处改过会返回 409；0 表示还没有保存过
    version: 0,
    accessCode: null,
    accessExpiresAt: null,
    history: [],
    isLoading: false,
    // 历史面板是否打开（由 Clipboard.vue 设置）：打开时收到推送要一并重拉历史
    historyVisible: false,
    // 编辑框里是否有没保存的修改（由 Clipboard.vue 设置）：布局里的「退出登录」据此先确认
    hasUnsavedEdit: false,
  }),

  actions: {
    /**
     * 递增刷新序号：之前发出、尚未返回的静默刷新结果作废，避免旧结果覆盖新内容
     */
    _bumpSeq() {
      this._refreshSeq = (this._refreshSeq || 0) + 1
      return this._refreshSeq
    },

    _apply(data) {
      this.currentText = data?.content || ''
      this.version = data?.version ?? 0
      this.accessCode = data?.access_code ?? null
      this.accessExpiresAt = data?.access_expires_at ?? null
    },

    /**
     * 获取当前剪贴板内容
     */
    async fetchCurrent() {
      // 与推送触发的静默刷新共用序号：期间又发出了更新的请求或本地已保存时，这次的结果（成功或失败）都作废
      const seq = this._bumpSeq()
      try {
        this.isLoading = true
        const data = await api.clipboard.get()
        if (seq !== this._refreshSeq) return
        this._apply(data)
      } catch (error) {
        console.error('获取剪贴板内容失败:', error)
        if (seq !== this._refreshSeq) return
        throw error
      } finally {
        if (seq === this._refreshSeq) this.isLoading = false
      }
    },

    /**
     * 更新剪贴板内容；baseVersion 为编辑开始时的版本号，传 null 表示直接覆盖。
     * 版本不一致时后端返回 409，错误对象的 status 为 409，由页面让用户选择
     */
    async updateText(content, baseVersion = null) {
      try {
        const data = await api.clipboard.update(content, baseVersion)
        this._bumpSeq()
        this._apply(data)
        return data
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
     * 取某条历史的全文：列表里较短的条目已带全文，较长的（content 为 null）才请求后端
     */
    async fetchHistoryContent(item) {
      if (item.content !== null && item.content !== undefined) return item.content
      const data = await api.clipboard.historyItem(item.id)
      return data.content
    },

    /**
     * 恢复某条历史为当前文本：后端会把原当前文本归档，所以恢复后要重新拉历史
     */
    async restoreHistory(historyId) {
      const data = await api.clipboard.restoreHistory(historyId)
      this._bumpSeq()
      this._apply(data)
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
     * 监听 WebSocket 实时更新；连接（重新）建立时也补拉一次，断线期间的变更不会漏掉。
     * 访问码改动（含其他终端设置 / 清除剪切板访问码）也重拉一次，页面上显示的访问码保持最新
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
          this._apply(data)
          // 其他终端保存 / 删除历史后，历史面板打开时一并刷新
          if (this.historyVisible) await this.fetchHistory()
        } catch {
          // 静默刷新失败不打扰用户，下次推送或手动刷新会再同步
        } finally {
          // 它可能顶替了还在进行的 fetchCurrent（后者的结果已作废，不再收尾「加载中」），由最新的这一次收尾
          if (seq === this._refreshSeq) this.isLoading = false
        }
      }
      ws.on('clipboard_updated', this._onClipboardUpdated)
      ws.on('access_codes_changed', this._onClipboardUpdated)
      ws.on('open', this._onClipboardUpdated)
    },

    /**
     * 清理监听器
     */
    cleanupWebSocket() {
      if (this._onClipboardUpdated) {
        ws.off('clipboard_updated', this._onClipboardUpdated)
        ws.off('access_codes_changed', this._onClipboardUpdated)
        ws.off('open', this._onClipboardUpdated)
        this._onClipboardUpdated = null
      }
    },
  },
})
