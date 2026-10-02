<script setup>
import { computed, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useUserStore } from '../stores'
import ws from '../utils/websocket'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

// 侧栏配额在布局级刷新：不管当前在哪个页面，文件增删或管理员改配额后都同步
const QUOTA_EVENTS = ['file_added', 'file_deleted', 'quota_updated']
const onQuotaChanged = () => {
  userStore.fetchUserInfo().catch(() => {})
}
onMounted(() => QUOTA_EVENTS.forEach((event) => ws.on(event, onQuotaChanged)))
onUnmounted(() => QUOTA_EVENTS.forEach((event) => ws.off(event, onQuotaChanged)))

const navItems = computed(() => {
  const items = [
    { name: 'Clipboard', label: '剪贴板', icon: '📋', path: '/clipboard' },
    { name: 'Files', label: '文件', icon: '📁', path: '/files' },
    { name: 'AccessCodes', label: '访问码', icon: '🔗', path: '/access-codes' },
  ]

  // 管理员添加后台入口
  if (userStore.isAdmin) {
    items.push({ name: 'Admin', label: '管理后台', icon: '⚙️', path: '/admin' })
  }

  return items
})

const isActive = (path) => {
  return route.path === path
}

const handleLogout = () => {
  userStore.logout()
  router.push('/login')
}
</script>

<template>
  <div class="home-layout">
    <aside class="sidebar">
      <div class="sidebar-header">
        <h1>ClipSync</h1>
        <div class="user-badge">
          <span class="username">{{ userStore.username }}</span>
          <span v-if="userStore.isSuperAdmin" class="role-tag super">超管</span>
          <span v-else-if="userStore.isAdmin" class="role-tag admin">管理</span>
        </div>
      </div>

      <nav class="sidebar-nav">
        <router-link
          v-for="item in navItems"
          :key="item.name"
          :to="item.path"
          class="nav-item"
          :class="{ active: isActive(item.path) }"
        >
          <span class="nav-icon">{{ item.icon }}</span>
          <span class="nav-label">{{ item.label }}</span>
        </router-link>
      </nav>

      <div class="sidebar-footer">
        <div class="quota-info">
          <div class="quota-label">存储使用</div>
          <div class="quota-bar">
            <div
              class="quota-fill"
              :style="{ width: userStore.quota.percentage + '%' }"
            ></div>
          </div>
          <div class="quota-text">
            {{ (userStore.quota.used / 1024 / 1024).toFixed(1) }} MB /
            {{ (userStore.quota.total / 1024 / 1024).toFixed(0) }} MB
          </div>
        </div>

        <button class="btn-logout" @click="handleLogout">
          <span>🚪</span>
          <span>退出登录</span>
        </button>
      </div>
    </aside>

    <main class="main-content">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.home-layout {
  display: flex;
  min-height: 100vh;
  background: #0B0E14;
}

.sidebar {
  width: 280px;
  background: #1E293B;
  border-right: 1px solid #334155;
  display: flex;
  flex-direction: column;
}

.sidebar-header {
  padding: 2rem 1.5rem;
  border-bottom: 1px solid #334155;
}

.sidebar-header h1 {
  font-size: 1.5rem;
  font-weight: 700;
  color: #F8FAFC;
  margin-bottom: 1rem;
}

.user-badge {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.username {
  font-size: 0.95rem;
  color: #CBD5E1;
}

.role-tag {
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 600;
}

.role-tag.super {
  background: rgba(249, 115, 22, 0.15);
  color: #F97316;
  border: 1px solid rgba(249, 115, 22, 0.3);
}

.role-tag.admin {
  background: rgba(56, 189, 248, 0.15);
  color: #38BDF8;
  border: 1px solid rgba(56, 189, 248, 0.3);
}

.sidebar-nav {
  flex: 1;
  padding: 1.5rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.875rem 1rem;
  border-radius: 8px;
  color: #94A3B8;
  text-decoration: none;
  transition: all 0.2s;
  font-size: 0.95rem;
}

.nav-item:hover {
  background: rgba(56, 189, 248, 0.1);
  color: #38BDF8;
}

.nav-item.active {
  background: rgba(56, 189, 248, 0.15);
  color: #38BDF8;
  font-weight: 600;
}

.nav-icon {
  font-size: 1.25rem;
}

.nav-label {
  flex: 1;
}

.sidebar-footer {
  padding: 1.5rem;
  border-top: 1px solid #334155;
}

.quota-info {
  margin-bottom: 1rem;
}

.quota-label {
  font-size: 0.85rem;
  color: #94A3B8;
  margin-bottom: 0.5rem;
}

.quota-bar {
  height: 6px;
  background: #0F172A;
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 0.5rem;
}

.quota-fill {
  height: 100%;
  background: linear-gradient(90deg, #38BDF8, #22D3EE);
  transition: width 0.3s;
}

.quota-text {
  font-size: 0.8rem;
  color: #64748B;
}

.btn-logout {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.75rem;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 8px;
  color: #FCA5A5;
  font-size: 0.9rem;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-logout:hover {
  background: rgba(239, 68, 68, 0.2);
  border-color: rgba(239, 68, 68, 0.5);
}

.main-content {
  flex: 1;
  overflow-y: auto;
}
</style>