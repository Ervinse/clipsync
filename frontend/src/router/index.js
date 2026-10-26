/**
 * Vue Router 配置
 */
import { createRouter, createWebHistory } from 'vue-router'
import { useUserStore } from '../stores'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/Login.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('../views/Register.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/',
    name: 'Home',
    component: () => import('../views/Home.vue'),
    meta: { requiresAuth: true },
    redirect: '/clipboard',
    children: [
      {
        path: '/clipboard',
        name: 'Clipboard',
        component: () => import('../views/Clipboard.vue'),
        meta: { requiresAuth: true },
      },
      {
        path: '/texts',
        name: 'Texts',
        component: () => import('../views/Texts.vue'),
        meta: { requiresAuth: true },
      },
      {
        path: '/files',
        name: 'Files',
        component: () => import('../views/Files.vue'),
        meta: { requiresAuth: true },
      },
      {
        path: '/access-codes',
        name: 'AccessCodes',
        component: () => import('../views/AccessCodes.vue'),
        meta: { requiresAuth: true },
      },
      {
        path: '/admin',
        name: 'Admin',
        component: () => import('../views/Admin.vue'),
        meta: { requiresAuth: true, requiresAdmin: true },
      },
    ],
  },
  {
    // 快速访问页：凭「用户名@访问码」进入，不需要登录（没有快速访问凭证时页面自己回到登录页）
    path: '/quick',
    name: 'QuickAccess',
    component: () => import('../views/QuickAccess.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/clipboard',
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 服务器升级后，已打开的旧页面里记的按需加载文件名（带内容哈希）在服务器上已经不存在，
// 点菜单时会加载失败、页面没反应。遇到这种错误刷新一次拿到新版本；
// 10 秒内已经刷新过就不再刷，避免服务器真的连不上时陷入刷新循环。
// 页面自带的样式文件会先于脚本预加载，旧文件名 404 时抛出的是 "Unable to preload CSS for ..."，同样要匹配。
const CHUNK_ERROR = /Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module|Unable to preload CSS/i
const RELOAD_KEY = 'chunk_reload_at'
router.onError((error, to) => {
  if (!CHUNK_ERROR.test(String(error?.message || error))) return
  let last = 0
  try {
    last = Number(sessionStorage.getItem(RELOAD_KEY)) || 0
  } catch {
    // 隐私模式下 sessionStorage 可能不可用，按没刷新过处理
  }
  // 10 秒内刚刷新过就放弃，也不更新时间：保护窗口不会被连续出现的错误一直往后推
  if (Date.now() - last <= 10000) return
  try {
    sessionStorage.setItem(RELOAD_KEY, String(Date.now()))
  } catch {
    // 同上
  }
  window.location.assign(to?.fullPath || '/')
})

router.beforeEach((to, from, next) => {
  const userStore = useUserStore()

  // 需要登录的路由
  if (to.meta.requiresAuth && !userStore.isLoggedIn) {
    // 记下原来要去的页面，登录后回到那里
    next({ path: '/login', query: { redirect: to.fullPath } })
    return
  }

  // 需要管理员权限的路由
  if (to.meta.requiresAdmin && !userStore.isAdmin) {
    next('/clipboard')
    return
  }

  // 已登录用户访问登录/注册页，重定向到首页
  if ((to.name === 'Login' || to.name === 'Register') && userStore.isLoggedIn) {
    next('/clipboard')
    return
  }

  next()
})

export default router
