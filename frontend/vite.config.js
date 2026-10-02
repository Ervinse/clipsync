import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        // 用 127.0.0.1：后端只监听 IPv4，localhost 可能先解析成 ::1 导致代理失败
        target: 'http://127.0.0.1:8000',
        // 保留浏览器的 Host（localhost:3000），后端据此拼出的访问码链接才指向前端页面
        changeOrigin: false,
      },
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
      },
    },
  },
})
