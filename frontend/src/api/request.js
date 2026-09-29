/**
 * Axios 封装：统一请求配置、拦截器、错误处理
 */
import axios from 'axios'

// 创建 axios 实例
const request = axios.create({
  baseURL: '/api',  // 相对路径，走 Vite 代理
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器：自动附加 Token
request.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器：统一错误处理
request.interceptors.response.use(
  (response) => {
    return response.data
  },
  (error) => {
    if (error.response) {
      const { status, data } = error.response

      // 401：未登录或 Token 失效
      if (status === 401) {
        localStorage.removeItem('access_token')
        window.location.href = '/login'
      }

      // 提取错误信息
      const message = data?.detail || '请求失败'
      return Promise.reject({ status, message })
    } else if (error.request) {
      return Promise.reject({ message: '网络连接失败' })
    } else {
      return Promise.reject({ message: error.message })
    }
  }
)

export default request
