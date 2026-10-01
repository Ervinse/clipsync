import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router from './router'
import App from './App.vue'
import './style.css'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(router)

// 初始化用户状态
import { useUserStore } from './stores'
const userStore = useUserStore()
userStore.init()

app.mount('#app')
