/**
 * 快速访问状态：凭「用户名@访问码」进入后的凭证与实时连接
 *
 * - 凭证存在 sessionStorage：刷新页面仍在，关掉标签页即失效；与登录 token（localStorage）互不影响
 * - 实时推送用单独的 WebSocket 实例 quickWs，不与登录用户的连接混用
 * - 凭证失效（访问码被清除 / 修改 / 过期、属主被禁用、2 小时到期）时 lost 置为 true，
 *   快速访问页据此提示并禁止编辑，未保存的内容仍留在页面上，可以先复制出来
 */
import { defineStore } from 'pinia'
import api from '../api'
import { WebSocketManager } from '../utils/websocket'

const STORAGE_KEY = 'quick_access'

export const quickWs = new WebSocketManager()

function readSaved() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || 'null')
    if (saved?.token && saved.expiresAt > Date.now()) return saved
  } catch {
    // 隐私模式下 sessionStorage 可能不可用，按没有凭证处理
  }
  return null
}

let expiryTimer = null

export const useQuickStore = defineStore('quick', {
  state: () => {
    const saved = readSaved()
    return {
      token: saved?.token || null,
      ownerUsername: saved?.ownerUsername || '',
      code: saved?.code || '',
      expiresAt: saved?.expiresAt || 0,
      lost: false,
    }
  },

  getters: {
    fullCode: (state) => (state.token ? `${state.ownerUsername}@${state.code}` : ''),
  },

  actions: {
    async login(fullCode) {
      const data = await api.quick.login(fullCode)
      this.token = data.access_token
      this.ownerUsername = data.owner_username
      this.code = data.code
      this.expiresAt = Date.now() + data.expires_in * 1000
      this.lost = false
      try {
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
          token: this.token, ownerUsername: this.ownerUsername, code: this.code, expiresAt: this.expiresAt,
        }))
      } catch {
        // 存不进去只影响刷新后需要重新输入
      }
    },

    /** 建立实时连接，并在凭证到期时结束快速访问 */
    connect() {
      if (!this.token) return
      quickWs.connect(this.token)
      clearTimeout(expiryTimer)
      expiryTimer = setTimeout(() => this.handleLost(), Math.max(0, this.expiresAt - Date.now()))
    },

    /** 主动退出 */
    logout() {
      this.token = null
      this.ownerUsername = ''
      this.code = ''
      this.expiresAt = 0
      clearTimeout(expiryTimer)
      quickWs.disconnect()
      try {
        sessionStorage.removeItem(STORAGE_KEY)
      } catch {
        // 同上
      }
    },

    /** 凭证失效：结束快速访问，页面显示「访问码已失效」 */
    handleLost() {
      if (!this.token) return
      this.logout()
      this.lost = true
    },
  },
})

// 已连接后被服务端以 1008 断开：访问码失效或属主被禁用
quickWs.on('auth_failed', () => useQuickStore().handleLost())
// 连接从未建立就被关闭：可能是访问码已失效，请求一次确认（401 时拦截器会调 handleLost，停止重连）
quickWs.on('handshake_failed', () => {
  api.quick.items().catch(() => {})
})
