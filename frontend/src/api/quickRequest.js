/**
 * 快速访问专用的 axios 实例：带快速访问凭证（不是登录 token），只请求 /api/access/*。
 *
 * 与 request.js 分开：快速访问凭证失效（401）只结束快速访问，不影响登录状态；
 * 登录用户的 token 也不会被带到快速访问接口上。reject 的对象同样是 { status, message }。
 */
import axios from 'axios'
import { extractMessage } from './request'
// 循环引用（quick store → api → 本模块）：只在拦截器函数里调用 useQuickStore()
import { useQuickStore } from '../stores/quick'

const quickRequest = axios.create({
  baseURL: '/api/access',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

quickRequest.interceptors.request.use((config) => {
  const token = useQuickStore().token
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

quickRequest.interceptors.response.use(
  (response) => response.data,
  async (error) => {
    if (error.response) {
      const { status, data } = error.response
      // 401：访问码被清除 / 修改 / 过期、属主被禁用或凭证到期，结束本次快速访问
      if (status === 401) useQuickStore().handleLost()
      return Promise.reject({ status, message: await extractMessage(status, data) })
    }
    if (error.request) {
      return Promise.reject({ message: '网络连接失败' })
    }
    return Promise.reject({ message: error.message })
  }
)

export default quickRequest
