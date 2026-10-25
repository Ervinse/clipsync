import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router from './router'
import App from './App.vue'
// Inter 字体随前端打包（不依赖外网字体服务，内网部署也能用），先于全局样式引入
import '@fontsource-variable/inter/index.css'
import './style.css'
// 主题：导入即按本浏览器的选择设好 data-theme，并监听系统深浅色与其他标签页的切换
import './utils/theme'
// 玻璃质感：判断能否启用液态折射，并让按钮、卡片的悬停高光跟着鼠标走
import './utils/glass'
import { useUserStore } from './stores'

const app = createApp(App)
app.use(createPinia())

// 必须先恢复登录状态再安装路由：app.use(router) 会立即触发首次导航，
// 若此时 isLoggedIn 还是 false，刷新受保护页面会被守卫踢回 /login。
const userStore = useUserStore()

// 其他标签页登录 / 登出 / 换账号会改写 localStorage 里的 token：
// 本页的内存状态（用户信息、各 store 数据、WS 连接）已属于旧账号，整页重载以新 token 重新初始化
window.addEventListener('storage', (event) => {
  if (event.key === 'access_token' && event.newValue !== userStore.token) {
    window.location.reload()
  }
})

userStore.init().finally(() => {
  app.use(router)
  app.mount('#app')
})
