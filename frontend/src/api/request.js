/**
 * Axios 封装：统一请求配置、拦截器、错误处理
 *
 * 拦截器 reject 的对象统一为 { status, message }，视图里读 err.message 即可。
 */
import axios from 'axios'

// 创建 axios 实例
const request = axios.create({
  baseURL: '/api',  // 相对路径，走 Vite 代理 / Nginx 反代
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 这些请求返回 401 只表示「凭证不对」，不代表已登录状态失效，不能整页跳转
const NO_REDIRECT_ON_401 = ['/auth/login', '/auth/register']

// 请求拦截器：自动附加 Token
request.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

/** 从后端错误响应里取出可读的错误信息 */
async function extractMessage(status, data) {
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
    message = message.map((e) => e?.msg).filter(Boolean).join('；')
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

      // 401：已登录状态失效才清 token 并跳转登录页。
      // 登录 / 注册本身的 401 交给页面显示；公开访问页（/access/...）不跳转，避免访客被踢走。
      if (status === 401 && !NO_REDIRECT_ON_401.some((p) => url.startsWith(p))) {
        localStorage.removeItem('access_token')
        if (!window.location.pathname.startsWith('/access/')
          && window.location.pathname !== '/login') {
          window.location.href = '/login'
        }
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
