<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { KeyRound, Clipboard, StickyNote, File, TriangleAlert, RotateCw, Copy, X } from '@lucide/vue'
import { useAccessStore } from '../stores'
import { formatDateTime } from '../utils/format'
import { isExpired } from '../utils/accessCode'
import { copyToClipboard } from '../utils/clipboard'
import toast from '../utils/toast'
import { confirmDialog, copyDialog } from '../utils/dialog'
import ws from '../utils/websocket'
import LoadingSkeleton from '../components/LoadingSkeleton.vue'

const router = useRouter()
const accessStore = useAccessStore()

// 任何内容的访问码改动、文本 / 文件被删除（访问码随之消失）后静默刷新；重连时补拉一次
const onChanged = () => {
  accessStore.fetchOverview({ silent: true }).catch(() => {})
}
const EVENTS = ['access_codes_changed', 'texts_changed', 'file_deleted', 'open']

// 「是否过期」随时间变化：页面开着时每 30 秒重算一次
const now = ref(Date.now())
let nowTimer = null

const load = () => accessStore.fetchOverview().catch(() => {})

onMounted(() => {
  EVENTS.forEach((event) => ws.on(event, onChanged))
  nowTimer = setInterval(() => { now.value = Date.now() }, 30000)
  return load()
})

onUnmounted(() => {
  EVENTS.forEach((event) => ws.off(event, onChanged))
  clearInterval(nowTimer)
})

const TYPE_META = {
  clipboard: { label: '云剪切板', icon: Clipboard, path: '/clipboard' },
  text: { label: '文本', icon: StickyNote, path: '/texts' },
  file: { label: '文件', icon: File, path: '/files' },
}

const fullCode = (code) => `${accessStore.username}@${code}`

const expired = (item) => isExpired(item.access_expires_at, now.value)
const groupActive = (group) => group.items.some((item) => !expired(item))

const copyFullCode = async (code) => {
  const value = fullCode(code)
  if (await copyToClipboard(value)) toast.success('完整访问码已复制')
  else copyDialog({ value })
}

const itemName = (item) => item.label || TYPE_META[item.target_type].label

const handleClear = async (item) => {
  const ok = await confirmDialog({
    title: '清除这个访问码？',
    message: `「${itemName(item)}」将不再能通过访问码 ${item.access_code} 进入。`,
    confirmText: '清除',
    danger: true,
  })
  if (!ok) return
  try {
    await accessStore.setCode({ targetType: item.target_type, targetId: item.target_id, code: null })
    toast.success('访问码已清除')
    await accessStore.fetchOverview({ silent: true }).catch(() => {})
  } catch (error) {
    toast.error('清除失败：' + error.message)
  }
}
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">访问码</h1>
        <p class="page-subtitle">按访问码查看你设置过的内容。在登录页输入「用户名@访问码」即可免登录进入</p>
      </div>
    </div>

    <div class="alert alert-info notice">
      <KeyRound />
      <span>访问码在云剪切板、文本、文件页面的条目旁设置。知道完整访问码的人可以查看和修改其中的文本、下载其中的文件，请妥善保管。</span>
    </div>

    <LoadingSkeleton v-if="accessStore.isLoading" variant="cards" :count="2" />

    <div v-else-if="accessStore.loadError" class="empty" role="alert">
      <span class="empty-icon"><TriangleAlert :size="20" /></span>
      <p class="empty-title">访问码加载失败</p>
      <p class="empty-text">{{ accessStore.loadError }}</p>
      <button class="btn btn-secondary" @click="load">
        <RotateCw />
        重试
      </button>
    </div>

    <div v-else-if="accessStore.groups.length === 0" class="empty">
      <span class="empty-icon"><KeyRound :size="20" /></span>
      <p class="empty-title">还没有设置访问码</p>
      <p class="empty-text">到云剪切板、文本或文件页面，点条目旁的「访问码」按钮设置</p>
      <button class="btn btn-secondary" @click="router.push('/texts')">去文本页</button>
    </div>

    <div v-else class="groups">
      <section
        v-for="group in accessStore.groups"
        :key="group.code"
        class="group card card-hover"
        :class="{ inactive: !groupActive(group) }"
      >
        <header class="group-head">
          <span class="group-code">
            <span class="mono">{{ fullCode(group.code) }}</span>
            <span v-if="!groupActive(group)" class="badge">已全部过期</span>
            <span v-else class="badge badge-dot badge-success">{{ group.items.length }} 项</span>
          </span>
          <button class="btn btn-secondary btn-sm" @click="copyFullCode(group.code)">
            <Copy :size="14" />
            复制
          </button>
        </header>
        <ul class="group-items">
          <li
            v-for="item in group.items"
            :key="item.target_type + ':' + (item.target_id ?? '')"
            class="group-item"
            :class="{ expired: expired(item) }"
          >
            <span class="item-icon"><component :is="TYPE_META[item.target_type].icon" :size="16" /></span>
            <span class="item-main">
              <router-link :to="TYPE_META[item.target_type].path" class="item-name" :title="itemName(item)">
                {{ itemName(item) }}
              </router-link>
              <span class="item-sub">
                {{ TYPE_META[item.target_type].label }} ·
                {{ expired(item) ? '已过期' : formatDateTime(item.access_expires_at, '永久有效') }}
              </span>
            </span>
            <button class="btn-icon danger" title="清除这项的访问码" aria-label="清除访问码" @click="handleClear(item)">
              <X />
            </button>
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>

<style scoped>
.notice {
  margin-bottom: var(--space-5);
}

.groups {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.group {
  overflow: hidden;
}

.group.inactive .group-code {
  color: var(--color-text-tertiary);
}

.group-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-glass-subtle);
}

.group-code {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
  min-width: 0;
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--color-text);
  word-break: break-all;
}

.group-items {
  list-style: none;
}

.group-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border);
}

.group-item:last-child {
  border-bottom: none;
}

.group-item.expired .item-name,
.group-item.expired .item-sub {
  color: var(--color-text-tertiary);
}

.item-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 30px;
  height: 30px;
  border-radius: var(--radius-sm);
  background: var(--color-bg-muted);
  color: var(--color-text-secondary);
}

.item-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  line-height: 1.35;
}

.item-name {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item-sub {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}
</style>
