/**
 * 文本栏目状态：每人多条独立文本
 */
import { defineStore } from 'pinia'
import api from '../api'
import ws from '../utils/websocket'

export const useTextsStore = defineStore('texts', {
  state: () => ({
    // 列表项：较长的文本 content 为 null，只有 preview，编辑前要先取全文
    texts: [],
    maxTexts: 200,
    isLoading: false,
    // 最近一次（非静默）拉取失败的原因；页面据此区分「没有文本」和「没加载出来」
    loadError: '',
    // 有没保存的修改（由 Texts.vue 设置）：布局里的「退出登录」据此先确认
    hasUnsavedEdit: false,
  }),

  getters: {
    // 按创建先后排（新的在前）：保存后条目位置不变，编辑时不会跳动
    sortedTexts(state) {
      return [...state.texts].sort((a, b) => b.id - a.id)
    },
  },

  actions: {
    async fetchTexts({ silent = false } = {}) {
      // 请求序号：期间又发出了更新的请求时，这次的结果（成功或失败）都作废，「加载中」由最新的一次收尾
      const seq = (this._seq = (this._seq || 0) + 1)
      try {
        if (!silent) this.isLoading = true
        const data = await api.texts.list()
        if (seq !== this._seq) return
        this.texts = data?.items || []
        this.maxTexts = data?.max_texts || this.maxTexts
        this.loadError = ''
      } catch (error) {
        console.error('获取文本列表失败:', error)
        if (seq !== this._seq) return
        if (!silent) this.loadError = error?.message || '加载失败'
        throw error
      } finally {
        if (seq === this._seq) this.isLoading = false
      }
    },

    async createText(data) {
      const text = await api.texts.create(data)
      this.texts = [...this.texts.filter((t) => t.id !== text.id), { ...text, preview: '', size: 0 }]
      return text
    },

    /** beforeRemove：删除成功、从列表移除之前调用（页面借此先丢掉草稿，不会误报「已在别处删除」） */
    async deleteText(id, beforeRemove) {
      await api.texts.delete(id)
      beforeRemove?.()
      this.texts = this.texts.filter((t) => t.id !== id)
    },

    /** 保存成功、设置访问码后就地更新列表项，不必等推送 */
    patchText(id, fields) {
      const item = this.texts.find((t) => t.id === id)
      if (item) Object.assign(item, fields)
    },

    /**
     * 监听 WebSocket：其他终端或快速访问页改了文本、改了访问码后静默刷新；重连时补拉
     */
    setupWebSocket() {
      if (this._onTextsChanged) return
      this._onTextsChanged = () => {
        this.fetchTexts({ silent: true }).catch(() => {})
      }
      ws.on('texts_changed', this._onTextsChanged)
      ws.on('access_codes_changed', this._onTextsChanged)
      ws.on('open', this._onTextsChanged)
    },

    cleanupWebSocket() {
      if (this._onTextsChanged) {
        ws.off('texts_changed', this._onTextsChanged)
        ws.off('access_codes_changed', this._onTextsChanged)
        ws.off('open', this._onTextsChanged)
        this._onTextsChanged = null
      }
    },
  },
})
