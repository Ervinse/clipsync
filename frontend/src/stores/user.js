/**
 * 用户状态管理
 */
import { defineStore } from 'pinia'
import api from '../api'
import ws from '../utils/websocket'

export const useUserStore = defineStore('user', {
  state: () => ({
    token: localStorage.getItem('access_token') || null,
    userInfo: null,
    isLoggedIn: false,
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

    // 配额信息
    quota(state) {
      return {
        used: state.userInfo?.storage_used || 0,
        total: state.userInfo?.quota_bytes || 0,
        percentage: state.userInfo?.quota_bytes
          ? Math.round((state.userInfo.storage_used / state.userInfo.quota_bytes) * 100)
          : 0,
      }
    },
  },

  actions: {
    /**
     * 登录
     */
    async login(credentials) {
      try {
        const data = await api.auth.login(credentials)
        this.token = data.access_token
        localStorage.setItem('access_token', data.access_token)

        // 获取用户信息
        await this.fetchUserInfo()

        // 连接 WebSocket
        ws.connect(this.token)

        this.isLoggedIn = true
        return true
      } catch (error) {
        console.error('登录失败:', error)
        throw error
      }
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
     * 获取用户信息
     */
    async fetchUserInfo() {
      try {
        const data = await api.auth.me()
        this.userInfo = data
        this.isLoggedIn = true
      } catch (error) {
        console.error('获取用户信息失败:', error)
        this.logout()
        throw error
      }
    },

    /**
     * 登出
     */
    logout() {
      this.token = null
      this.userInfo = null
      this.isLoggedIn = false
      localStorage.removeItem('access_token')
      ws.disconnect()
    },

    /**
     * 初始化（页面加载时）
     */
    async init() {
      if (this.token) {
        try {
          await this.fetchUserInfo()
          ws.connect(this.token)
        } catch (error) {
          this.logout()
        }
      }
    },
  },
})
