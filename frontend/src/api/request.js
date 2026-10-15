/**
 * Axios 封装：统一请求配置、拦截器、错误处理
 *
 * 拦截器 reject 的对象统一为 { status, message }，视图里读 err.message 即可。
 */
import axios from 'axios'
// 循环引用（user store → api → 本模块）：只在拦截器函数里调用 useUserStore()，模块顶层不调用
import { useUserStore } from '../stores/user'

// 创建 axios 实例
const request = axios.create({
  baseURL: '/api',  // 相对路径，走 Vite 代理 / Nginx 反代
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 这些请求返回 401 / 403 只表示「凭证不对 / 账号已禁用」，不代表已登录状态失效，不能整页跳转
const NO_AUTH_LOST = ['/auth/login', '/auth/register']

// 请求拦截器：自动附加 Token（用本标签页 store 里的 token，不读 localStorage，避免多标签页串号）
request.interceptors.request.use(
  (config) => {
    const token = useUserStore().token
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

/** 从后端错误响应里取出可读的错误信息（快速访问的请求实例 quickRequest.js 也用它） */
export async function extractMessage(status, data) {
  // responseType 为 blob 时，错误响应体也是 Blob，需要先解析成 JSON
  if (typeof Blob !== 'undefined' && data instanceof Blob) {
    try {
      data = JSON.parse(await data.text())
    } catch {
      data = null
    }
  }

  // FastAPI 用 detail；slowapi 限流用 error
  let message = data?.detail ?? data?.error
  // 422 校验错误的 detail 是数组 [{ loc, msg, type }]
  if (Array.isArray(message)) {
    // pydantic 的自定义校验会给 msg 加上英文前缀 "Value error, "，对用户没有意义，去掉
    message = message.map((e) => e?.msg?.replace(/^Value error,\s*/i, '')).filter(Boolean).join('；')
  }
  if (status === 429 && !data?.detail) {
    message = '操作过于频繁，请稍后再试'
  }
  if (status === 413 && !message) {
    message = '文件或请求过大'
  }
  return typeof message === 'string' && message ? message : '请求失败'
}

// 响应拦截器：统一错误处理
request.interceptors.response.use(
  (response) => response.data,
  async (error) => {
    if (error.response) {
      const { status, data } = error.response
      const url = error.config?.url || ''

      // 401（凭证失效）或带 X-Auth-Error: disabled 的 403（账号被禁用）：已登录状态失效，登出并回登录页。
      // 用响应头判断禁用而不是匹配中文 detail；普通「权限不足」的 403 不带该头，不受影响。
      // 登录 / 注册本身的 401 / 403 交给页面显示；公开访问页由 handleAuthLost 判断不跳转。
      const disabled = status === 403 && error.response.headers?.['x-auth-error'] === 'disabled'
      if ((status === 401 || disabled) && !NO_AUTH_LOST.some((p) => url.startsWith(p))) {
        useUserStore().handleAuthLost()
      }

      return Promise.reject({ status, message: await extractMessage(status, data) })
    }
    if (error.request) {
      return Promise.reject({ message: '网络连接失败' })
    }
    return Promise.reject({ message: error.message })
  }
)

export default request
