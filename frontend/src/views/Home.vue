<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Clipboard, StickyNote, Folder, KeyRound, Settings, LogOut, Menu, X } from '@lucide/vue'
import { useUserStore, useClipboardStore, useTextsStore } from '../stores'
import ws from '../utils/websocket'
import { formatSize } from '../utils/format'
import { confirmDialog } from '../utils/dialog'
import BrandMark from '../components/BrandMark.vue'
import ThemeToggle from '../components/ThemeToggle.vue'

// 项目主页：侧栏底部一行小字，是否显示由后台系统设置的 show_github_link 控制
const REPO_URL = 'https://github.com/Ervinse/clipsync'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const clipboardStore = useClipboardStore()
const textsStore = useTextsStore()

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
    { name: 'Clipboard', label: '云剪切板', icon: Clipboard, path: '/clipboard' },
    { name: 'Texts', label: '文本', icon: StickyNote, path: '/texts' },
    { name: 'Files', label: '文件', icon: Folder, path: '/files' },
    { name: 'AccessCodes', label: '访问码', icon: KeyRound, path: '/access-codes' },
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

const handleLogout = async () => {
  // 退出前一律先确认，防止误点。云剪切板或文本页有没保存的文字时换成危险提示：
  // 登出会清掉本页状态，文字无法找回
  const unsaved = clipboardStore.hasUnsavedEdit || textsStore.hasUnsavedEdit
  const ok = await confirmDialog(unsaved
    ? {
        title: '退出登录并放弃未保存的修改？',
        message: '有文本还没有保存，退出后会丢失。',
        confirmText: '退出登录',
        cancelText: '继续编辑',
        danger: true,
      }
    : {
        title: '退出登录？',
        message: '退出后需要重新输入用户名和密码登录。',
        confirmText: '退出登录',
      })
  if (!ok) return
  userStore.logout()
  router.push('/login')
}
</script>

<template>
  <div class="layout">
    <header class="topbar liquid">
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

        <div class="theme-row">
          <span class="theme-label">主题</span>
          <ThemeToggle />
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

        <a
          v-if="userStore.showGithubLink"
          class="repo-link"
          :href="REPO_URL"
          target="_blank"
          rel="noopener noreferrer"
        >
          <!-- GitHub 标志（Octicons mark-github），lucide 不含品牌图标，所以内联 -->
          <svg class="repo-icon" viewBox="0 0 16 16" width="13" height="13" fill="currentColor" aria-hidden="true">
            <path
              d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"
            />
          </svg>
          <span>开源项目 · GitHub</span>
        </a>
      </div>
    </aside>

    <main class="main">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
/* 不设底色：页面底色和光斑层（style.css 的 body::before）从这里透出来 */
.layout {
  display: flex;
  min-height: 100vh;
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
  height: 100dvh;
  /* 窗口矮到放不下导航和底部区域时整个侧栏滚动，底部账号、退出按钮不会被裁掉 */
  overflow-y: auto;
  /* 一整块竖立的玻璃：半透明浅灰透出背后的光斑，表面光泽，右边缘内侧一道亮边；
     侧栏背后没有滚动的内容，不需要模糊 */
  background-color: var(--color-glass-subtle);
  background-image: var(--glass-sheen);
  border-right: 1px solid var(--color-border);
  box-shadow: inset -1px 0 0 var(--color-glass-rim);
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

/* 占满中间的空余高度，但不压缩到比菜单项还矮 */
.nav {
  flex: 1 0 auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-2) var(--space-3);
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
  transition: background-color var(--duration) var(--ease), color var(--duration) var(--ease),
    box-shadow var(--duration) var(--ease), transform 280ms var(--ease-spring);
}

.nav-item:hover {
  background: var(--color-bg-muted);
  color: var(--color-text);
  text-decoration: none;
}

/* 当前菜单项是浮在侧栏上的一颗玻璃块 */
.nav-item.active {
  background-color: var(--color-glass-pill);
  background-image: var(--glass-sheen);
  color: var(--color-text);
  box-shadow: var(--glass-shadow), var(--shadow-sm);
}

@media (prefers-reduced-motion: no-preference) {
  .nav-item:active {
    transform: scale(0.97);
    transition-duration: 100ms;
    transition-timing-function: var(--ease);
  }
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

.theme-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 10px var(--space-2);
}

.theme-label {
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--color-text-secondary);
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

.repo-link {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: var(--space-1);
  padding: var(--space-1) 10px;
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  text-decoration: none;
  transition: color var(--duration) var(--ease);
}

.repo-link:hover {
  color: var(--color-text);
  text-decoration: none;
}

.repo-icon {
  flex-shrink: 0;
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
    /* 吸顶栏：半透明 + 模糊（支持时再加液态折射，见 style.css 的 .liquid），底边一道亮边 */
    background: var(--color-topbar-bg);
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    border-bottom: 1px solid var(--color-border);
    box-shadow: inset 0 1px 0 var(--color-highlight), 0 1px 0 var(--color-glass-rim);
  }

  /* 抽屉叠在变暗的页面上，用不透明底色，弱提示文字才清楚 */
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
    backdrop-filter: var(--overlay-blur);
    -webkit-backdrop-filter: var(--overlay-blur);
    animation: fade-in var(--duration) var(--ease);
  }
}
</style>
