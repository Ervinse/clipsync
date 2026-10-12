<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Clipboard, Folder, Link, Settings, LogOut, Menu, X } from '@lucide/vue'
import { useUserStore } from '../stores'
import ws from '../utils/websocket'
import { formatSize } from '../utils/format'
import BrandMark from '../components/BrandMark.vue'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

// 侧栏配额在布局级刷新：不管当前在哪个页面，文件增删或管理员改配额后都同步
// open：连接（重新）建立时补拉，断线期间错过的配额变更不会一直显示旧值
const QUOTA_EVENTS = ['file_added', 'file_deleted', 'quota_updated', 'open']
const onQuotaChanged = () => {
  userStore.fetchUserInfo().catch(() => {})
}
onMounted(() => QUOTA_EVENTS.forEach((event) => ws.on(event, onQuotaChanged)))
onUnmounted(() => QUOTA_EVENTS.forEach((event) => ws.off(event, onQuotaChanged)))

const navItems = computed(() => {
  const items = [
    { name: 'Clipboard', label: '剪贴板', icon: Clipboard, path: '/clipboard' },
    { name: 'Files', label: '文件', icon: Folder, path: '/files' },
    { name: 'AccessCodes', label: '访问码', icon: Link, path: '/access-codes' },
  ]

  // 管理员添加后台入口（只是入口隐藏，后端接口另做角色校验）
  if (userStore.isAdmin) {
    items.push({ name: 'Admin', label: '管理后台', icon: Settings, path: '/admin' })
  }

  return items
})

const isActive = (path) => {
  return route.path === path
}

const roleLabel = computed(() => {
  if (userStore.isSuperAdmin) return '超级管理员'
  if (userStore.isAdmin) return '管理员'
  return '普通用户'
})

const avatarText = computed(() => (userStore.username || '?').slice(0, 1).toUpperCase())

// 配额用量超过 80% 显示为警示色，超过 95% 为危险色
const quotaLevel = computed(() => {
  const p = userStore.quota.percentage
  if (p >= 95) return 'danger'
  if (p >= 80) return 'warning'
  return ''
})

// 窄屏下侧栏是抽屉：点菜单按钮打开，切换页面后自动收起
const drawerOpen = ref(false)
watch(() => route.path, () => {
  drawerOpen.value = false
})

const handleLogout = () => {
  userStore.logout()
  router.push('/login')
}
</script>

<template>
  <div class="layout">
    <header class="topbar">
      <button class="btn-icon" aria-label="打开导航" @click="drawerOpen = true">
        <Menu :size="18" />
      </button>
      <BrandMark :size="22" />
    </header>

    <div v-if="drawerOpen" class="drawer-mask" @click="drawerOpen = false"></div>

    <aside class="sidebar" :class="{ open: drawerOpen }">
      <div class="sidebar-top">
        <BrandMark :size="24" />
        <button class="btn-icon drawer-close" aria-label="关闭导航" @click="drawerOpen = false">
          <X :size="18" />
        </button>
      </div>

      <nav class="nav" aria-label="主导航">
        <router-link
          v-for="item in navItems"
          :key="item.name"
          :to="item.path"
          class="nav-item"
          :class="{ active: isActive(item.path) }"
          :aria-current="isActive(item.path) ? 'page' : undefined"
        >
          <component :is="item.icon" class="nav-icon" />
          <span>{{ item.label }}</span>
        </router-link>
      </nav>

      <div class="sidebar-bottom">
        <div class="quota">
          <div class="quota-row">
            <span class="quota-label">存储空间</span>
            <span class="quota-percent">{{ userStore.quota.percentage }}%</span>
          </div>
          <div class="progress">
            <div
              class="progress-fill"
              :class="quotaLevel"
              :style="{ width: Math.min(userStore.quota.percentage, 100) + '%' }"
            ></div>
          </div>
          <div class="quota-text">
            {{ formatSize(userStore.quota.used) }} / {{ formatSize(userStore.quota.total) }}
          </div>
          <!-- 进行中上传的声明大小也占配额：有时单独显示，避免用户以为空间凭空少了 -->
          <div v-if="userStore.quota.reserved > 0" class="quota-text">
            上传中 {{ formatSize(userStore.quota.reserved) }}
          </div>
        </div>

        <div class="account">
          <span class="avatar" aria-hidden="true">{{ avatarText }}</span>
          <span class="account-info">
            <span class="account-name">{{ userStore.username }}</span>
            <span class="account-role">{{ roleLabel }}</span>
          </span>
          <button class="btn-icon" title="退出登录" aria-label="退出登录" @click="handleLogout">
            <LogOut />
          </button>
        </div>
      </div>
    </aside>

    <main class="main">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.layout {
  display: flex;
  min-height: 100vh;
  background: var(--color-bg);
}

.topbar {
  display: none;
}

.sidebar {
  position: sticky;
  top: 0;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  width: var(--sidebar-width);
  height: 100vh;
  background: var(--color-bg-subtle);
  border-right: 1px solid var(--color-border);
}

.sidebar-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 60px;
  padding: 0 var(--space-5);
}

.drawer-close {
  display: none;
}

.nav {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-2) var(--space-3);
  overflow-y: auto;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 34px;
  padding: 0 10px;
  border-radius: var(--radius-sm);
  font-size: var(--text-base);
  font-weight: 500;
  color: var(--color-text-secondary);
  text-decoration: none;
  transition: background-color var(--duration) var(--ease), color var(--duration) var(--ease);
}

.nav-item:hover {
  background: var(--color-bg-muted);
  color: var(--color-text);
  text-decoration: none;
}

.nav-item.active {
  background: var(--color-bg);
  color: var(--color-text);
  box-shadow: var(--shadow-sm);
}

.nav-icon {
  flex-shrink: 0;
  color: var(--color-text-tertiary);
}

.nav-item.active .nav-icon,
.nav-item:hover .nav-icon {
  color: var(--color-text);
}

.sidebar-bottom {
  padding: var(--space-3);
  border-top: 1px solid var(--color-border);
}

.quota {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: var(--space-2) 10px var(--space-3);
}

.quota-row {
  display: flex;
  justify-content: space-between;
  font-size: var(--text-xs);
}

.quota-label {
  font-weight: 500;
  color: var(--color-text-secondary);
}

.quota-percent {
  color: var(--color-text-tertiary);
  font-variant-numeric: tabular-nums;
}

.quota-text {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  font-variant-numeric: tabular-nums;
}

.account {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: var(--space-2);
  border-radius: var(--radius-md);
}

.avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: var(--color-primary);
  color: var(--color-text-inverse);
  font-size: var(--text-sm);
  font-weight: 600;
}

.account-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}

.account-name {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.account-role {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}

.main {
  flex: 1;
  min-width: 0;
}

.drawer-mask {
  display: none;
}

@media (max-width: 768px) {
  .layout {
    flex-direction: column;
  }

  .topbar {
    position: sticky;
    top: 0;
    z-index: 50;
    display: flex;
    align-items: center;
    gap: var(--space-2);
    height: 52px;
    padding: 0 var(--space-3);
    background: rgba(255, 255, 255, 0.9);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    border-bottom: 1px solid var(--color-border);
  }

  .sidebar {
    position: fixed;
    left: 0;
    top: 0;
    z-index: 200;
    width: min(280px, 85vw);
    height: 100%;
    background: var(--color-bg-subtle);
    box-shadow: var(--shadow-lg);
    transform: translateX(-100%);
    transition: transform 200ms var(--ease);
  }

  .sidebar.open {
    transform: translateX(0);
  }

  .drawer-close {
    display: inline-flex;
  }

  .drawer-mask {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 150;
    background: var(--color-overlay);
    animation: fade-in var(--duration) var(--ease);
  }
}
</style>
