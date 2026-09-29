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
    path: '/access/:code',
    name: 'PublicAccess',
    component: () => import('../views/PublicAccess.vue'),
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

// 路由守卫
router.beforeEach((to, from, next) => {
  const userStore = useUserStore()

  // 需要登录的路由
  if (to.meta.requiresAuth && !userStore.isLoggedIn) {
    next('/login')
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
