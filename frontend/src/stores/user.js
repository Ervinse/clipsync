/**
 * 用户状态管理
 */
import { defineStore } from 'pinia'
import api from '../api'
import ws from '../utils/websocket'
// 以下 store 也 import 了本模块（循环引用）：只在函数体内调用 useXxxStore()，模块顶层不调用，ESM 下安全
import { useClipboardStore } from './clipboard'
import { useTextsStore } from './texts'
import { useFilesStore } from './files'
import { useAccessStore } from './access'
import { useAdminStore } from './admin'

// /auth/me 只在凭证失效（401）或账号被禁用（403）时返回这两个状态码
const isAuthError = (error) => error?.status === 401 || error?.status === 403

export const useUserStore = defineStore('user', {
  state: () => ({
    token: localStorage.getItem('access_token') || null,
    userInfo: null,
    isLoggedIn: false,
    // 启动时连不上服务器（网络错误 / 5xx）的提示；此时 token 保留，不算登出
    connectionError: '',
  }),

  getters: {
    // 是否为管理员
    isAdmin(state) {
      return state.userInfo?.role === 'admin' || state.userInfo?.role === 'superadmin'
    },

    // 是否为超级管理员
    isSuperAdmin(state) {
      return state.userInfo?.role === 'superadmin'
    },

    // 用户名
    username(state) {
      return state.userInfo?.username || ''
    },

    // 侧栏是否显示 GitHub 链接：后台系统设置里的开关，随 /auth/me 下发（普通用户读不了后台设置接口）
    showGithubLink(state) {
      return state.userInfo?.show_github_link === true
    },

    // 配额信息
    quota(state) {
      // 后端 /auth/me 返回 used_bytes（已落盘）与 reserved_bytes（进行中上传占用）；两者都计入配额
      const used = state.userInfo?.used_bytes || 0
      const reserved = state.userInfo?.reserved_bytes || 0
      const total = state.userInfo?.quota_bytes || 0
      return {
        used,
        reserved,
        total,
        percentage: total ? Math.round(((used + reserved) / total) * 100) : 0,
      }
    },
  },

  actions: {
    /**
     * 登录
     */
    async login(credentials) {
      const data = await api.auth.login(credentials)
      this.token = data.access_token
      localStorage.setItem('access_token', data.access_token)

      try {
        await this.fetchUserInfo()
      } catch (error) {
        // 刚拿到的 token 取不到用户信息：不保留半登录状态
        console.error('登录失败:', error)
        this.logout()
        throw error
      }

      // 连接 WebSocket
      ws.connect(this.token)
      return true
    },

    /**
     * 注册
     */
    async register(data) {
      try {
        const result = await api.auth.register(data)
        return result
      } catch (error) {
        console.error('注册失败:', error)
        throw error
      }
    },

    /**
     * 获取用户信息：只有凭证失效 / 账号禁用才登出，网络错误或 5xx 保留 token
     */
    async fetchUserInfo() {
      try {
        const data = await api.auth.me()
        this.userInfo = data
        this.isLoggedIn = true
        this.connectionError = ''
      } catch (error) {
        console.error('获取用户信息失败:', error)
        if (isAuthError(error)) this.logout()
        throw error
      }
    },

    /**
     * 登出：清掉 token、断开 WS，并重置其他 store，避免下一个登录的账号看到上一个账号的数据
     */
    logout() {
      this.token = null
      this.userInfo = null
      this.isLoggedIn = false
      this.connectionError = ''
      localStorage.removeItem('access_token')
      ws.disconnect()

      for (const store of [useClipboardStore(), useTextsStore(), useFilesStore(), useAccessStore(), useAdminStore()]) {
        store.cleanupWebSocket?.()
        store.$reset()
      }
    },

    /**
     * 凭证失效 / 账号被禁用：登出并回到登录页（登录页、注册页、快速访问页不跳转，访客不受影响）
     */
    handleAuthLost() {
      this.logout()
      const path = window.location.pathname
      // 登录页、注册页、快速访问页本来就不需要登录：留在原地
      if (path !== '/quick' && path !== '/login' && path !== '/register') {
        // 带上当前页面，重新登录后回到这里
        window.location.href = '/login?redirect=' + encodeURIComponent(path + window.location.search)
      }
    },

    /**
     * WS 握手被拒时浏览器只给 1006，分不清是凭证失效还是服务器不可达：问一次 /auth/me。
     * 401 / 禁用 403 由请求拦截器调 handleAuthLost 处理；其他错误交给 WS 继续退避重连。
     */
    async verifySession() {
      try {
        this.userInfo = await api.auth.me()
      } catch {
        // 见上方注释
      }
    },

    /**
     * 初始化（页面加载时）
     */
    async init() {
      if (!this.token) return
      try {
        await this.fetchUserInfo()
        ws.connect(this.token)
      } catch (error) {
        if (!isAuthError(error)) {
          this.connectionError = '暂时无法连接服务器，登录状态已保留，请稍后刷新页面'
        }
      }
    },
  },
})

// 已连接后被服务端以 1008 断开（账号被禁用 / 删除）：登出并回登录页
ws.on('auth_failed', () => useUserStore().handleAuthLost())
// 连接从未建立就被关闭：可能是握手被拒，确认一次会话是否仍有效
ws.on('handshake_failed', () => useUserStore().verifySession())
