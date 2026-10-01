import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router from './router'
import App from './App.vue'
import './style.css'
import { useUserStore } from './stores'

const app = createApp(App)
app.use(createPinia())

// 必须先恢复登录状态再安装路由：app.use(router) 会立即触发首次导航，
// 若此时 isLoggedIn 还是 false，刷新受保护页面会被守卫踢回 /login。
const userStore = useUserStore()
userStore.init().finally(() => {
  app.use(router)
  app.mount('#app')
})
