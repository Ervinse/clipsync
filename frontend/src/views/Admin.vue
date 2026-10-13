<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import {
  ChartColumn, Users, UserCheck, Ticket, Folder, Settings, File, HardDrive,
  Plus, Copy, Trash2, Ban, CircleCheck, Pencil, ChevronLeft, ChevronRight,
  CircleAlert, Info, LoaderCircle, X,
} from '@lucide/vue'
import { useAdminStore, useUserStore } from '../stores'
import { PAGE_SIZE } from '../stores/admin'
import { formatDateTime, formatSize } from '../utils/format'
import { copyToClipboard } from '../utils/clipboard'
import toast from '../utils/toast'
import { confirmDialog, promptDialog, copyDialog, dialogState } from '../utils/dialog'

// 访问权限由路由守卫（meta.requiresAdmin）拦截，后端接口再做最终校验
const adminStore = useAdminStore()
const userStore = useUserStore()

// Esc 关闭「创建邀请码」弹窗（不依赖焦点在弹窗内）；全局对话框打开时 Esc 只作用于它
const onEscape = (event) => {
  if (event.key === 'Escape' && showCreateInviteModal.value && !dialogState.current) {
    showCreateInviteModal.value = false
  }
}
onMounted(() => window.addEventListener('keydown', onEscape))
onUnmounted(() => window.removeEventListener('keydown', onEscape))

const TABS = [
  { key: 'stats', label: '概览', icon: ChartColumn },
  { key: 'users', label: '用户', icon: Users },
  { key: 'invites', label: '邀请码', icon: Ticket },
  { key: 'files', label: '文件', icon: Folder },
  { key: 'settings', label: '设置', icon: Settings },
]
const activeTab = ref('stats')
const showCreateInviteModal = ref(false)
const isCreatingInvite = ref(false)
// 邀请码一次性使用，后端只接收 expires_at
const inviteForm = ref({
  expires_in_days: 7,
})

onMounted(async () => {
  // 并行加载，互不影响：任何一个失败都不会阻断其余数据的显示
  // 文件元数据 admin 及以上均可查看（后端 /api/admin/files 同此权限），不含下载入口
  const tasks = [
    ['统计', adminStore.fetchStats()],
    ['用户', adminStore.fetchUsers()],
    ['邀请码', adminStore.fetchInviteCodes()],
    ['文件', adminStore.fetchFiles()],
    ['设置', adminStore.fetchSettings()],
  ]
  const results = await Promise.allSettled(tasks.map(([, p]) => p))
  syncSettingsForm()

  const failed = tasks.filter((_, i) => results[i].status === 'rejected').map(([name]) => name)
  if (failed.length > 0) {
    toast.error(`部分数据加载失败：${failed.join('、')}`)
  }
})

const stats = computed(() => adminStore.stats || {})
const STAT_CARDS = computed(() => [
  { label: '用户总数', value: stats.value.total_users || 0, icon: Users },
  { label: '活跃用户', value: stats.value.active_users || 0, icon: UserCheck },
  { label: '文件总数', value: stats.value.total_files || 0, icon: File },
  { label: '总存储', value: formatSize(stats.value.total_storage_bytes || 0), icon: HardDrive },
])

// 系统设置：后端 GET 对 admin 及以上开放，PATCH 仅 superadmin；目前只有这两项存库
const settingsForm = ref({
  registration_enabled: true,
  default_quota_mb: 100,
})
const isSavingSettings = ref(false)

const syncSettingsForm = () => {
  const s = adminStore.settings
  if (!s) return
  settingsForm.value = {
    registration_enabled: s.registration_enabled,
    default_quota_mb: Math.round(s.default_quota_bytes / 1024 / 1024),
  }
}

const handleSaveSettings = async () => {
  if (!userStore.isSuperAdmin) {
    toast.error('仅超级管理员可修改系统设置')
    return
  }
  // 设置没加载成功时，表单里是初始默认值而不是真实设置，此时保存会把真实设置改成默认值
  if (!adminStore.settings) {
    toast.error('当前设置未能加载，请刷新页面后再保存')
    return
  }
  // 输入框清空后得到的是空字符串，Number('') 等于 0，必须先拦下，否则会静默保存成 0 MB
  const rawQuota = settingsForm.value.default_quota_mb
  const quotaMB = Number(rawQuota)
  if (rawQuota === '' || rawQuota === null || !Number.isInteger(quotaMB) || quotaMB < 0) {
    toast.error('默认配额必须是非负整数（MB）')
    return
  }
  try {
    isSavingSettings.value = true
    await adminStore.updateSettings({
      registration_enabled: settingsForm.value.registration_enabled,
      default_quota_bytes: quotaMB * 1024 * 1024,
    })
    syncSettingsForm()
    toast.success('系统设置已保存')
  } catch (error) {
    toast.error('保存失败：' + error.message)
  } finally {
    isSavingSettings.value = false
  }
}

const openCreateInviteModal = () => {
  inviteForm.value = {
    expires_in_days: 7,
  }
  showCreateInviteModal.value = true
}

const handleCreateInvite = async () => {
  try {
    isCreatingInvite.value = true
    // 0 或空表示永久有效；其余换算为带时区的 ISO 时间
    const days = Number(inviteForm.value.expires_in_days)
    await adminStore.createInviteCode({
      expires_at: days > 0
        ? new Date(Date.now() + days * 86400 * 1000).toISOString()
        : null,
    })
    showCreateInviteModal.value = false
    toast.success('邀请码已创建')
  } catch (error) {
    toast.error('创建失败：' + error.message)
  } finally {
    isCreatingInvite.value = false
  }
}

const handleDeleteInvite = async (id) => {
  const ok = await confirmDialog({
    title: '删除这个邀请码？',
    message: '删除后该邀请码无法再用于注册。',
    confirmText: '删除',
    danger: true,
  })
  if (!ok) return

  try {
    await adminStore.deleteInviteCode(id)
  } catch (error) {
    toast.error('删除失败：' + error.message)
  }
}

const handleToggleUserStatus = async (user) => {
  if (!userStore.isSuperAdmin) {
    toast.error('仅超级管理员可执行此操作')
    return
  }

  // 禁用会立即断开该用户的连接，先确认；启用直接执行
  if (user.is_active) {
    const ok = await confirmDialog({
      title: `禁用用户「${user.username}」？`,
      message: '禁用后该用户无法登录，已打开的页面会立即断开。数据会保留，之后可以重新启用。',
      confirmText: '禁用',
      danger: true,
    })
    if (!ok) return
  }

  try {
    await adminStore.updateUserStatus(user.id, !user.is_active)
  } catch (error) {
    toast.error('操作失败：' + error.message)
  }
}

const handleUpdateQuota = async (user) => {
  if (!userStore.isSuperAdmin) {
    toast.error('仅超级管理员可执行此操作')
    return
  }

  const input = await promptDialog({
    title: `修改「${user.username}」的配额`,
    message: `当前已使用 ${formatSize(user.used_bytes || 0)}。`,
    label: '新配额',
    defaultValue: Math.round(user.quota_bytes / 1024 / 1024),
    inputType: 'number',
    suffix: 'MB',
    confirmText: '保存',
  })
  if (input === null || input.trim() === '') return
  // 与系统设置同样的校验：非负整数（MB）
  const quotaMB = Number(input.trim())
  if (!Number.isInteger(quotaMB) || quotaMB < 0) {
    toast.error('配额必须是非负整数（MB）')
    return
  }

  try {
    await adminStore.updateUserQuota(user.id, quotaMB * 1024 * 1024)
    toast.success('配额已更新')
  } catch (error) {
    toast.error('更新失败：' + error.message)
  }
}

const handleDeleteUser = async (user) => {
  if (!userStore.isSuperAdmin) {
    toast.error('仅超级管理员可执行此操作')
    return
  }

  const ok = await confirmDialog({
    title: `删除用户「${user.username}」？`,
    message: '该用户的文本、历史、文件和访问码会被全部删除，此操作不可撤销。',
    confirmText: '删除用户',
    danger: true,
  })
  if (!ok) return

  try {
    await adminStore.deleteUser(user.id)
    toast.success('用户已删除')
  } catch (error) {
    toast.error('删除失败：' + error.message)
  }
}

// 邀请码状态：used_at 非空即已用过（使用者被删除后 used_by 会置空）；未用过再看是否过期
const inviteStatus = (invite) => {
  if (invite.used_at || invite.used_by) return 'used'
  // 后端时间为 UTC（不带时区后缀），补 Z 再解析
  if (invite.expires_at && new Date(invite.expires_at + 'Z').getTime() <= Date.now()) return 'expired'
  return 'available'
}
const INVITE_STATUS = {
  used: { label: '已使用', cls: '' },
  expired: { label: '已过期', cls: 'badge-warning' },
  available: { label: '可用', cls: 'badge-success' },
}

const ROLE_LABEL = { superadmin: '超级管理员', admin: '管理员', user: '普通用户' }
const ROLE_CLASS = { superadmin: 'badge-accent', admin: 'badge-accent', user: '' }

// 用户行里的用量条：配额为 0 时按已满处理
const usagePercent = (user) => {
  if (!user.quota_bytes) return user.used_bytes ? 100 : 0
  return Math.min(100, Math.round(((user.used_bytes || 0) / user.quota_bytes) * 100))
}

// 分页：skip 为当前页起点
const pageInfo = (skip, total) => ({
  page: Math.floor(skip / PAGE_SIZE) + 1,
  pages: Math.max(1, Math.ceil(total / PAGE_SIZE)),
  hasPrev: skip > 0,
  hasNext: skip + PAGE_SIZE < total,
})
const usersPage = computed(() => pageInfo(adminStore.usersSkip, adminStore.usersTotal))
const filesPage = computed(() => pageInfo(adminStore.filesSkip, adminStore.filesTotal))

const gotoUsersPage = async (delta) => {
  try {
    await adminStore.fetchUsers(Math.max(0, adminStore.usersSkip + delta * PAGE_SIZE))
  } catch (error) {
    toast.error('加载失败：' + error.message)
  }
}
const gotoFilesPage = async (delta) => {
  try {
    await adminStore.fetchFiles(Math.max(0, adminStore.filesSkip + delta * PAGE_SIZE))
  } catch (error) {
    toast.error('加载失败：' + error.message)
  }
}

// 后端时间为 naive UTC，formatDateTime 内部按 UTC 解析；空值（如永久有效的邀请码）显示「永久有效」
const formatDate = (value) => formatDateTime(value, '永久有效', false)

// HTTP 部署下 navigator.clipboard 不可用，copyToClipboard 会降级
const copyInviteCode = async (code) => {
  if (await copyToClipboard(code)) {
    toast.success('邀请码已复制')
  } else {
    copyDialog({ value: code })
  }
}
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">管理后台</h1>
        <p class="page-subtitle">用户、邀请码与系统设置</p>
      </div>
    </div>

    <div class="tabs" role="tablist">
      <button
        v-for="tab in TABS"
        :key="tab.key"
        class="tab"
        :class="{ active: activeTab === tab.key }"
        role="tab"
        :aria-selected="activeTab === tab.key"
        @click="activeTab = tab.key"
      >
        <component :is="tab.icon" />
        {{ tab.label }}
      </button>
    </div>

    <!-- 概览 -->
    <div v-if="activeTab === 'stats'" class="tab-panel">
      <div class="stat-grid">
        <div v-for="card in STAT_CARDS" :key="card.label" class="stat-card card">
          <div class="stat-head">
            <span class="stat-label">{{ card.label }}</span>
            <component :is="card.icon" class="stat-icon" />
          </div>
          <div class="stat-value">{{ card.value }}</div>
        </div>
      </div>
    </div>

    <!-- 用户管理 -->
    <div v-if="activeTab === 'users'" class="tab-panel">
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>用户</th>
              <th>角色</th>
              <th>存储使用</th>
              <th>状态</th>
              <th>注册时间</th>
              <th v-if="userStore.isSuperAdmin" class="cell-actions"><span class="sr-only">操作</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="user in adminStore.users" :key="user.id">
              <td>
                <span class="user-cell">
                  <span class="avatar" aria-hidden="true">{{ user.username.slice(0, 1).toUpperCase() }}</span>
                  <span class="user-name">{{ user.username }}</span>
                </span>
              </td>
              <td>
                <span class="badge" :class="ROLE_CLASS[user.role]">{{ ROLE_LABEL[user.role] || user.role }}</span>
              </td>
              <td>
                <span class="usage">
                  <span class="usage-text">{{ formatSize(user.used_bytes || 0) }} / {{ formatSize(user.quota_bytes) }}</span>
                  <span class="progress usage-bar">
                    <span
                      class="progress-fill"
                      :class="{ warning: usagePercent(user) >= 80 && usagePercent(user) < 95, danger: usagePercent(user) >= 95 }"
                      :style="{ width: usagePercent(user) + '%' }"
                    ></span>
                  </span>
                </span>
              </td>
              <td>
                <span class="badge badge-dot" :class="user.is_active ? 'badge-success' : 'badge-danger'">
                  {{ user.is_active ? '正常' : '已禁用' }}
                </span>
              </td>
              <td class="cell-muted">{{ formatDate(user.created_at) }}</td>
              <td v-if="userStore.isSuperAdmin" class="cell-actions">
                <span class="row-actions">
                  <button class="btn-icon" title="修改配额" aria-label="修改配额" @click="handleUpdateQuota(user)">
                    <Pencil />
                  </button>
                  <!-- superadmin 之间互不可禁用 / 删除（后端返回 403），按钮不显示 -->
                  <button
                    v-if="user.role !== 'superadmin'"
                    class="btn-icon"
                    :title="user.is_active ? '禁用' : '启用'"
                    :aria-label="user.is_active ? '禁用' : '启用'"
                    @click="handleToggleUserStatus(user)"
                  >
                    <Ban v-if="user.is_active" />
                    <CircleCheck v-else />
                  </button>
                  <button
                    v-if="user.role !== 'superadmin'"
                    class="btn-icon danger"
                    title="删除"
                    aria-label="删除"
                    @click="handleDeleteUser(user)"
                  >
                    <Trash2 />
                  </button>
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="usersPage.pages > 1" class="pagination">
        <span>第 {{ usersPage.page }} / {{ usersPage.pages }} 页，共 {{ adminStore.usersTotal }} 个用户</span>
        <span class="pagination-buttons">
          <button class="btn btn-secondary btn-sm" :disabled="!usersPage.hasPrev" @click="gotoUsersPage(-1)">
            <ChevronLeft :size="14" />上一页
          </button>
          <button class="btn btn-secondary btn-sm" :disabled="!usersPage.hasNext" @click="gotoUsersPage(1)">
            下一页<ChevronRight :size="14" />
          </button>
        </span>
      </div>
    </div>

    <!-- 邀请码管理 -->
    <div v-if="activeTab === 'invites'" class="tab-panel">
      <div class="panel-toolbar">
        <p class="toolbar-text">邀请码只能使用一次，注册时填写</p>
        <button class="btn btn-primary" @click="openCreateInviteModal">
          <Plus />
          创建邀请码
        </button>
      </div>

      <div v-if="adminStore.inviteCodes.length === 0" class="empty">
        <span class="empty-icon"><Ticket :size="20" /></span>
        <p class="empty-title">还没有邀请码</p>
        <p class="empty-text">创建邀请码后发给要注册的人</p>
      </div>

      <div v-else class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>邀请码</th>
              <th>状态</th>
              <th>过期时间</th>
              <th>使用者</th>
              <th class="cell-actions"><span class="sr-only">操作</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="invite in adminStore.inviteCodes" :key="invite.id">
              <td><span class="code mono">{{ invite.code }}</span></td>
              <td>
                <span class="badge badge-dot" :class="INVITE_STATUS[inviteStatus(invite)].cls">
                  {{ INVITE_STATUS[inviteStatus(invite)].label }}
                </span>
              </td>
              <td class="cell-muted">{{ formatDate(invite.expires_at) }}</td>
              <td class="cell-muted">{{ invite.used_by ? (invite.used_by_username || invite.used_by) : '—' }}</td>
              <td class="cell-actions">
                <span class="row-actions">
                  <button class="btn btn-secondary btn-sm" @click="copyInviteCode(invite.code)">
                    <Copy :size="14" />
                    复制
                  </button>
                  <!-- 已使用的邀请码后端禁止删除（409），按钮不显示 -->
                  <button
                    v-if="inviteStatus(invite) !== 'used'"
                    class="btn-icon danger"
                    title="删除"
                    aria-label="删除"
                    @click="handleDeleteInvite(invite.id)"
                  >
                    <Trash2 />
                  </button>
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 文件元数据（admin 及以上；安全红线：只展示元数据，无下载入口） -->
    <div v-if="activeTab === 'files'" class="tab-panel">
      <div class="alert alert-info panel-note">
        <Info />
        <span>这里只显示文件的元数据，管理员无法查看或下载其他用户的文件内容。</span>
      </div>
      <div v-if="adminStore.files.length === 0" class="empty">
        <span class="empty-icon"><Folder :size="20" /></span>
        <p class="empty-title">还没有文件</p>
        <p class="empty-text">用户上传的文件会在这里列出</p>
      </div>
      <div v-else class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>文件名</th>
              <th>大小</th>
              <th>所属用户</th>
              <th>上传时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="file in adminStore.files" :key="file.id">
              <td><span class="file-name" :title="file.original_name">{{ file.original_name }}</span></td>
              <td class="cell-muted num">{{ formatSize(file.size) }}</td>
              <td>{{ file.username }}</td>
              <td class="cell-muted">{{ formatDate(file.created_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="filesPage.pages > 1" class="pagination">
        <span>第 {{ filesPage.page }} / {{ filesPage.pages }} 页，共 {{ adminStore.filesTotal }} 个文件</span>
        <span class="pagination-buttons">
          <button class="btn btn-secondary btn-sm" :disabled="!filesPage.hasPrev" @click="gotoFilesPage(-1)">
            <ChevronLeft :size="14" />上一页
          </button>
          <button class="btn btn-secondary btn-sm" :disabled="!filesPage.hasNext" @click="gotoFilesPage(1)">
            下一页<ChevronRight :size="14" />
          </button>
        </span>
      </div>
    </div>

    <!-- 系统设置（admin 只读，superadmin 可修改；后端为最终防线） -->
    <div v-if="activeTab === 'settings'" class="tab-panel">
      <form class="settings card" @submit.prevent="handleSaveSettings">
        <div v-if="!adminStore.settings" class="alert alert-warning">
          <CircleAlert />
          <span>当前设置未能加载，下面显示的不是真实设置，无法保存。请刷新页面重试。</span>
        </div>
        <div v-else-if="!userStore.isSuperAdmin" class="alert alert-info">
          <Info />
          <span>仅超级管理员可修改系统设置，当前为只读。</span>
        </div>

        <div class="setting-row">
          <div class="setting-text">
            <span class="setting-title">开放注册</span>
            <span class="setting-desc">关闭后即使持有有效邀请码也无法注册</span>
          </div>
          <label class="switch">
            <input
              v-model="settingsForm.registration_enabled"
              type="checkbox"
              :disabled="!userStore.isSuperAdmin"
              aria-label="开放注册"
            />
            <span class="switch-track"></span>
          </label>
        </div>

        <div class="setting-row">
          <div class="setting-text">
            <label class="setting-title" for="default-quota">新用户默认配额</label>
            <span class="setting-desc">只影响之后注册的用户；已有用户的配额在「用户」页单独修改</span>
          </div>
          <span class="input-with-suffix quota-input">
            <input
              id="default-quota"
              v-model.number="settingsForm.default_quota_mb"
              class="input"
              type="number"
              min="0"
              :disabled="!userStore.isSuperAdmin"
            />
            <span class="input-suffix">MB</span>
          </span>
        </div>

        <p class="settings-note">
          单文件上限、分片大小、历史保留条数等由 backend/.env 配置，需重启后端生效，不在此修改。
        </p>

        <div v-if="userStore.isSuperAdmin" class="settings-footer">
          <button
            type="submit"
            class="btn btn-primary"
            :disabled="isSavingSettings || !adminStore.settings"
          >
            <LoaderCircle v-if="isSavingSettings" class="spin" />
            {{ isSavingSettings ? '保存中…' : '保存设置' }}
          </button>
        </div>
      </form>
    </div>

    <!-- 创建邀请码弹窗 -->
    <div v-if="showCreateInviteModal" class="modal-overlay" @mousedown.self="showCreateInviteModal = false">
      <form
        class="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-invite-title"
        @submit.prevent="handleCreateInvite"
        @keydown.esc="showCreateInviteModal = false"
      >
        <div class="modal-header header-with-close">
          <div>
            <h2 id="create-invite-title" class="modal-title">创建邀请码</h2>
            <p class="modal-desc">每个邀请码只能注册一个账号</p>
          </div>
          <button type="button" class="btn-icon" aria-label="关闭" @click="showCreateInviteModal = false">
            <X />
          </button>
        </div>
        <div class="modal-body">
          <label class="field">
            <span class="field-label">有效期</span>
            <span class="input-with-suffix">
              <input
                v-model.number="inviteForm.expires_in_days"
                class="input"
                type="number"
                min="0"
                placeholder="7"
              />
              <span class="input-suffix">天</span>
            </span>
            <span class="field-hint">0 表示永久有效</span>
          </label>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="showCreateInviteModal = false">取消</button>
          <button type="submit" class="btn btn-primary" :disabled="isCreatingInvite">
            <LoaderCircle v-if="isCreatingInvite" class="spin" />
            创建
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--space-4);
}

.stat-card {
  padding: var(--space-5);
}

.stat-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.stat-label {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--color-text-secondary);
}

.stat-icon {
  color: var(--color-text-tertiary);
}

.stat-value {
  margin-top: var(--space-3);
  font-size: var(--text-3xl);
  font-weight: 600;
  letter-spacing: -0.02em;
  line-height: 1.1;
  color: var(--color-text);
  font-variant-numeric: tabular-nums;
}

.user-cell {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: var(--color-bg-muted);
  color: var(--color-text-secondary);
  font-size: var(--text-xs);
  font-weight: 600;
}

.user-name {
  font-weight: 500;
}

.usage {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 140px;
}

.usage-text {
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  font-variant-numeric: tabular-nums;
}

.usage-bar {
  height: 4px;
}

.row-actions {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}

.code {
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  background: var(--color-bg-muted);
  color: var(--color-text);
}

.file-name {
  display: inline-block;
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: bottom;
}

.num {
  font-variant-numeric: tabular-nums;
}

.panel-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}

.toolbar-text {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.panel-note {
  margin-bottom: var(--space-4);
}

.pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  margin-top: var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.pagination-buttons {
  display: inline-flex;
  gap: var(--space-2);
}

.settings {
  max-width: 640px;
  display: flex;
  flex-direction: column;
  padding: var(--space-2) var(--space-6);
}

.settings > .alert {
  margin-top: var(--space-4);
}

.setting-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-6);
  padding: var(--space-5) 0;
  border-bottom: 1px solid var(--color-border);
}

.setting-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.setting-title {
  font-size: var(--text-base);
  font-weight: 500;
  color: var(--color-text);
}

.setting-desc {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.quota-input {
  flex-shrink: 0;
  width: 140px;
}

.settings-note {
  padding: var(--space-4) 0;
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}

.settings-footer {
  display: flex;
  justify-content: flex-end;
  margin: 0 calc(-1 * var(--space-6));
  padding: var(--space-4) var(--space-6);
  border-top: 1px solid var(--color-border);
  background: var(--color-bg-subtle);
  border-radius: 0 0 var(--radius-lg) var(--radius-lg);
}

.settings:has(.settings-footer) {
  padding-bottom: 0;
}

.header-with-close {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
}

.input-with-suffix {
  position: relative;
  display: block;
}

.input-with-suffix .input {
  padding-right: 48px;
}

.input-suffix {
  position: absolute;
  right: var(--space-3);
  top: 50%;
  transform: translateY(-50%);
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
  pointer-events: none;
}

@media (max-width: 1024px) {
  .stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 768px) {
  .stat-value {
    font-size: var(--text-2xl);
  }

  .panel-toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .setting-row {
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-3);
  }

  .pagination {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
