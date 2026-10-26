<script setup>
import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
import {
  ChartColumn, Users, UserCheck, Ticket, Folder, Settings, File, HardDrive,
  Plus, Copy, Trash2, Ban, CircleCheck, Pencil, ChevronLeft, ChevronRight, ChevronDown, Search,
  CircleAlert, Info, LoaderCircle, X, CalendarClock, KeyRound, ShieldCheck,
  ShieldPlus, ShieldMinus, Eye, Download, Server,
} from '@lucide/vue'
import { useAdminStore, useUserStore, useFilesStore } from '../stores'
import UserContentDialog from '../components/UserContentDialog.vue'
import { PAGE_SIZE } from '../stores/admin'
import { formatDateTime, formatSize, formatDownloadProgress, parseUtc, bytesToMB, mbToBytes } from '../utils/format'
import { isExpired } from '../utils/accessCode'
import { copyText } from '../utils/clipboard'
import toast from '../utils/toast'
import { confirmDialog, promptDialog, dialogState } from '../utils/dialog'

// 访问权限由路由守卫（meta.requiresAdmin）拦截，后端接口再做最终校验
const adminStore = useAdminStore()
const userStore = useUserStore()

// Esc 关闭「创建邀请码」弹窗（不依赖焦点在弹窗内）；全局对话框打开时 Esc 只作用于它
const onEscape = (event) => {
  if (event.key === 'Escape' && showCreateInviteModal.value && !dialogState.current) {
    closeCreateInviteModal()
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
  { key: 'system', label: '系统信息', icon: Server },
]
const activeTab = ref('stats')
const showCreateInviteModal = ref(false)
const isCreatingInvite = ref(false)
// 一次生成 1–20 个，同一批共用一个有效期和备注（与后端 MAX_INVITE_BATCH、MAX_INVITE_NOTE_CHARS 一致）
const MAX_INVITE_BATCH = 20
const MAX_INVITE_NOTE_CHARS = 100
const inviteForm = ref({
  count: 1,
  expires_in_days: 7,
  note: '',
})
// 有效期快捷按钮：点一下填入天数（半年按 180 天、一年按 365 天算），输入框仍可手动填其他天数
const EXPIRY_PRESETS = [
  { days: 7, label: '7 天' },
  { days: 14, label: '14 天' },
  { days: 30, label: '30 天' },
  { days: 90, label: '90 天' },
  { days: 180, label: '半年' },
  { days: 365, label: '一年' },
  { days: 0, label: '永久' },
]
// 本次生成的批次：非空时弹窗切换成「生成结果」页
const createdBatch = ref(null)

onMounted(async () => {
  // 并行加载，互不影响：任何一个失败都不会阻断其余数据的显示
  // 文件元数据 admin 及以上均可查看（后端 /api/admin/files 同此权限，只返回元数据）；超管的下载按钮走 /api/files/{id}/download
  const tasks = [
    ['统计', adminStore.fetchStats()],
    ['用户', adminStore.fetchUsers()],
    ['邀请码', adminStore.fetchInviteBatches()],
    ['文件', adminStore.fetchFiles()],
    ['设置', adminStore.fetchSettings()],
    ['系统信息', adminStore.fetchDeployInfo()],
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
  { label: '访问码总数', value: stats.value.total_access_codes || 0, icon: KeyRound },
  { label: '有效访问码', value: stats.value.active_access_codes || 0, icon: ShieldCheck },
])

// 系统设置：后端 GET / PATCH 对 admin 及以上开放；存库的就是下面这几项
const settingsForm = ref({
  registration_enabled: true,
  show_github_link: true,
  default_quota_mb: 100,
})
const isSavingSettings = ref(false)

const syncSettingsForm = () => {
  const s = adminStore.settings
  if (!s) return
  settingsForm.value = {
    registration_enabled: s.registration_enabled,
    show_github_link: s.show_github_link,
    default_quota_mb: bytesToMB(s.default_quota_bytes),
  }
}

const handleSaveSettings = async () => {
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
      show_github_link: settingsForm.value.show_github_link,
      default_quota_bytes: mbToBytes(quotaMB),
    })
    syncSettingsForm()
    // 侧栏的 GitHub 链接开关随 /auth/me 下发：重取一次，改完立刻在本页侧栏生效（失败不影响保存结果）
    userStore.fetchUserInfo().catch(() => {})
    toast.success('系统设置已保存')
  } catch (error) {
    toast.error('保存失败：' + error.message)
  } finally {
    isSavingSettings.value = false
  }
}

const openCreateInviteModal = () => {
  inviteForm.value = {
    count: 1,
    expires_in_days: 7,
    note: '',
  }
  createdBatch.value = null
  showCreateInviteModal.value = true
}

const closeCreateInviteModal = () => {
  showCreateInviteModal.value = false
  createdBatch.value = null
}

// 备注字数按字符算（与后端 len() 一致），emoji 等算一个字
const noteLength = (note) => [...note].length

// 有效天数校验：空、非整数、负数返回 null；0 表示永久有效
const parseDays = (raw) => {
  if (raw === '' || raw === null || raw === undefined) return null
  const days = Number(raw)
  return Number.isInteger(days) && days >= 0 ? days : null
}

// 天数换算成带时区的 ISO 时间，从现在开始计算；0 表示永久有效（null）
const daysToExpiresAt = (days) =>
  days > 0 ? new Date(Date.now() + days * 86400 * 1000).toISOString() : null

const handleCreateInvite = async () => {
  const count = Number(inviteForm.value.count)
  if (!Number.isInteger(count) || count < 1 || count > MAX_INVITE_BATCH) {
    toast.error(`生成数量必须是 1 到 ${MAX_INVITE_BATCH} 之间的整数`)
    return
  }
  const days = parseDays(inviteForm.value.expires_in_days)
  if (days === null) {
    toast.error('有效期必须是非负整数（天）')
    return
  }
  const note = (inviteForm.value.note || '').trim()
  if (noteLength(note) > MAX_INVITE_NOTE_CHARS) {
    toast.error(`备注最多 ${MAX_INVITE_NOTE_CHARS} 个字`)
    return
  }
  try {
    isCreatingInvite.value = true
    createdBatch.value = await adminStore.createInviteBatch({
      count,
      expires_at: daysToExpiresAt(days),
      note,
    })
  } catch (error) {
    toast.error('创建失败：' + error.message)
  } finally {
    isCreatingInvite.value = false
  }
}

// 有效期的完整写法，用于生成结果页与邀请信息，例如 2025年6月20日 14:30；永久有效返回 null
const formatExpiryLong = (value) => {
  const date = parseUtc(value)
  if (!date || Number.isNaN(date.getTime())) return null
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日 ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

// 刚生成的一批共用一个有效期，取第一个即可
const createdExpiry = computed(() => formatExpiryLong(createdBatch.value?.codes?.[0]?.expires_at))

// 注册链接取当前打开管理页的地址；只有一个码时带上 ?code= 让注册页自动填好
const registerUrl = (code) => {
  const base = `${window.location.origin}/register`
  return code ? `${base}?code=${encodeURIComponent(code)}` : base
}

// 邀请信息里的有效期：一批码通常共用一个有效期；单独改过、各不相同时写最早的那个
const inviteExpiryText = (invites) => {
  const values = [...new Set(invites.map((invite) => invite.expires_at ?? null))]
  if (values.length === 1) {
    const expiry = formatExpiryLong(values[0])
    return expiry ? `${expiry} 前` : '长期有效'
  }
  const earliest = values.filter(Boolean).sort((a, b) => parseUtc(a) - parseUtc(b))[0]
  return `最早 ${formatExpiryLong(earliest)} 前`
}

/**
 * 邀请信息：发给别人的整段文字。
 * 标签统一三个字，聊天软件里后面的内容自然对齐；只用空行分组，不加装饰符号
 */
const buildInviteMessage = (invites) => {
  const expiryLine = `有效期  ${inviteExpiryText(invites)}`
  const title = 'ClipSync · 注册邀请'
  if (invites.length === 1) {
    return [title, '', `邀请码  ${invites[0].code}`, expiryLine, '', registerUrl(invites[0].code)].join('\n')
  }
  return [
    title,
    '',
    '邀请码  每个限注册一个账号',
    ...invites.map((invite) => invite.code),
    '',
    expiryLine,
    registerUrl(),
  ].join('\n')
}

const copyCreatedCodes = () => {
  const invites = createdBatch.value?.codes || []
  copyText(invites.map((invite) => invite.code).join('\n'), `已复制 ${invites.length} 个邀请码`)
}

const copyCreatedMessage = () => {
  copyText(buildInviteMessage(createdBatch.value?.codes || []), '邀请信息已复制')
}

// 邀请码状态：used_at 非空即已用过（使用者被删除后 used_by 会置空）；未用过再看是否过期
const inviteStatus = (invite) => {
  if (invite.used_at || invite.used_by) return 'used'
  if (isExpired(invite.expires_at)) return 'expired'
  return 'available'
}
const INVITE_STATUS = {
  used: { label: '已使用', cls: '' },
  expired: { label: '已过期', cls: 'badge-warning' },
  available: { label: '可用', cls: 'badge-success' },
}

// ---------- 批次列表：统计、筛选、搜索、展开 ----------

// 每批的统计与有效期概要；有效期只看未使用的码（已用掉的码有效期没有意义）
const batchViews = computed(() =>
  adminStore.inviteBatches.map((batch) => {
    const stats = { available: 0, expired: 0, used: 0 }
    for (const invite of batch.codes) stats[inviteStatus(invite)] += 1
    const unused = batch.codes.filter((invite) => inviteStatus(invite) !== 'used')
    const expiries = [...new Set(unused.map((invite) => invite.expires_at ?? null))]
    let expirySummary = '—'
    if (expiries.length === 1) expirySummary = formatDate(expiries[0])
    else if (expiries.length > 1) expirySummary = '各不相同'
    return { ...batch, stats, unusedIds: unused.map((invite) => invite.id), expirySummary }
  }),
)

// 状态筛选按批次：一批可能同时符合「有可用的」和「有已过期的」
const INVITE_FILTERS = [
  { key: 'all', label: '全部', test: () => true },
  { key: 'available', label: '有可用的', test: (b) => b.stats.available > 0 },
  { key: 'expired', label: '有已过期的', test: (b) => b.stats.expired > 0 },
  { key: 'used', label: '已用完', test: (b) => b.stats.available === 0 && b.stats.expired === 0 },
]
const inviteFilter = ref('all')
const inviteSearch = ref('')

// 邀请码比较时去掉短横线和空格、不分大小写，与注册时的输入规则一致
const compactCode = (value) => value.replace(/[\s-]/g, '').toUpperCase()

// 搜索备注、创建人或邀请码；返回 { batchIds, codeIds }，codeIds 是按邀请码命中的码（用于高亮）
const searchMatches = computed(() => {
  const query = inviteSearch.value.trim().toLowerCase()
  if (!query) return null
  const codeQuery = compactCode(query)
  const batchIds = new Set()
  const codeIds = new Set()
  for (const batch of batchViews.value) {
    if (batch.note.toLowerCase().includes(query) || batch.created_by_username.toLowerCase().includes(query)) {
      batchIds.add(batch.id)
    }
    if (!codeQuery) continue
    for (const invite of batch.codes) {
      if (compactCode(invite.code).includes(codeQuery)) {
        batchIds.add(batch.id)
        codeIds.add(invite.id)
      }
    }
  }
  return { batchIds, codeIds }
})

const searchedBatches = computed(() =>
  searchMatches.value ? batchViews.value.filter((b) => searchMatches.value.batchIds.has(b.id)) : batchViews.value,
)

// 筛选按钮上的数字：在当前搜索结果里各有几批
const filterCounts = computed(() =>
  Object.fromEntries(INVITE_FILTERS.map((f) => [f.key, searchedBatches.value.filter(f.test).length])),
)

const filteredBatches = computed(() => {
  const filter = INVITE_FILTERS.find((f) => f.key === inviteFilter.value) || INVITE_FILTERS[0]
  return searchedBatches.value.filter(filter.test)
})

const isCodeMatched = (invite) => Boolean(searchMatches.value?.codeIds.has(invite.id))

const clearInviteFilters = () => {
  inviteSearch.value = ''
  inviteFilter.value = 'all'
}

// 展开的批次；按邀请码搜到的批次自动展开，仍可以手动收起
const expandedBatchIds = ref(new Set())
const isExpanded = (id) => expandedBatchIds.value.has(id)
const toggleBatch = (id) => {
  const next = new Set(expandedBatchIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expandedBatchIds.value = next
}
watch(searchMatches, (matches) => {
  if (!matches || matches.codeIds.size === 0) return
  const next = new Set(expandedBatchIds.value)
  for (const batch of batchViews.value) {
    if (batch.codes.some((invite) => matches.codeIds.has(invite.id))) next.add(batch.id)
  }
  expandedBatchIds.value = next
})

// ---------- 勾选：只有未使用的码（含已过期未使用）可以勾选并修改有效期 ----------
const selectedInviteIds = ref([])
const isInviteSelectable = (invite) => inviteStatus(invite) !== 'used'
const selectableInviteIds = computed(() => batchViews.value.flatMap((batch) => batch.unusedIds))

// 列表刷新后（删除、被注册用掉、修改后重取）去掉已不存在或不可选的勾选
watch(selectableInviteIds, (ids) => {
  const valid = new Set(ids)
  selectedInviteIds.value = selectedInviteIds.value.filter((id) => valid.has(id))
})

// 每批表头的全选框：只作用于这一批
const batchSelection = (batch) => {
  const chosen = batch.unusedIds.filter((id) => selectedInviteIds.value.includes(id)).length
  return {
    all: batch.unusedIds.length > 0 && chosen === batch.unusedIds.length,
    some: chosen > 0 && chosen < batch.unusedIds.length,
  }
}

const toggleBatchSelection = (batch) => {
  const ids = new Set(batch.unusedIds)
  const rest = selectedInviteIds.value.filter((id) => !ids.has(id))
  selectedInviteIds.value = batchSelection(batch).all ? rest : [...rest, ...batch.unusedIds]
}

const toggleInvite = (id) => {
  const ids = selectedInviteIds.value
  selectedInviteIds.value = ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]
}

// 修改有效期：单个（行内按钮）与批量（勾选后工具栏按钮）共用，天数从现在开始算
const handleEditInviteExpiry = async (ids) => {
  if (ids.length === 0) return
  const input = await promptDialog({
    title: ids.length === 1 ? '修改有效期' : `修改 ${ids.length} 个邀请码的有效期`,
    message: '从现在开始计算，0 表示永久有效。',
    label: '有效期',
    defaultValue: 7,
    inputType: 'number',
    suffix: '天',
    confirmText: '保存',
  })
  if (input === null) return
  const days = parseDays(input.trim())
  if (days === null) {
    toast.error('有效期必须是非负整数（天）')
    return
  }
  try {
    await adminStore.updateInviteExpiry(ids, daysToExpiresAt(days))
    selectedInviteIds.value = selectedInviteIds.value.filter((id) => !ids.includes(id))
    toast.success(ids.length === 1 ? '有效期已更新' : `已更新 ${ids.length} 个邀请码的有效期`)
  } catch (error) {
    toast.error('修改失败：' + error.message)
  }
}

const handleDeleteInvite = async (id) => {
  const ok = await confirmDialog({
    title: '删除这个邀请码？',
    message: '这个邀请码将被永久删除，无法找回，也无法再用于注册。',
    confirmText: '删除',
    danger: true,
  })
  if (!ok) return

  try {
    await adminStore.deleteInviteCode(id)
    toast.success('邀请码已删除')
  } catch (error) {
    toast.error('删除失败：' + error.message)
  }
}

// ---------- 批次操作 ----------

// 重新复制邀请信息：只放还能用的码，已用掉或过期的放进去对方会白试
const availableCodes = (batch) => batch.codes.filter((invite) => inviteStatus(invite) === 'available')

const copyBatchMessage = (batch) => {
  const invites = availableCodes(batch)
  if (invites.length === 0) {
    toast.error('这批没有可用的邀请码')
    return
  }
  copyText(buildInviteMessage(invites), `邀请信息已复制（${invites.length} 个可用邀请码）`)
}

const copyBatchCodes = (batch) => {
  const invites = availableCodes(batch)
  if (invites.length === 0) {
    toast.error('这批没有可用的邀请码')
    return
  }
  copyText(invites.map((invite) => invite.code).join('\n'), `已复制 ${invites.length} 个可用邀请码`)
}

const handleEditBatchNote = async (batch) => {
  const input = await promptDialog({
    title: batch.note ? '修改备注' : '添加备注',
    message: `写下这批邀请码的用途，最多 ${MAX_INVITE_NOTE_CHARS} 个字；留空表示清除备注。`,
    label: '备注',
    defaultValue: batch.note,
    confirmText: '保存',
  })
  if (input === null) return
  const note = input.trim()
  if (noteLength(note) > MAX_INVITE_NOTE_CHARS) {
    toast.error(`备注最多 ${MAX_INVITE_NOTE_CHARS} 个字`)
    return
  }
  if (note === batch.note) return
  try {
    await adminStore.updateInviteBatchNote(batch.id, note)
    toast.success(note ? '备注已保存' : '备注已清除')
  } catch (error) {
    toast.error('保存失败：' + error.message)
  }
}

// 整批删除未使用的码（含已过期未使用的）；已使用的保留，批次与备注随之保留
const handleDeleteUnusedInBatch = async (batch) => {
  const count = batch.unusedIds.length
  if (count === 0) return
  const keepsUsed = batch.stats.used > 0
  const ok = await confirmDialog({
    title: `删除这批里 ${count} 个未使用的邀请码？`,
    message: keepsUsed
      ? `这些邀请码将被永久删除，无法找回，也无法再用于注册。已使用的 ${batch.stats.used} 个保留，这批记录和备注也保留。`
      : '这些邀请码将被永久删除，无法找回，也无法再用于注册，这批记录也会一起删除。',
    confirmText: '删除',
    danger: true,
  })
  if (!ok) return
  try {
    const result = await adminStore.deleteUnusedInBatch(batch.id)
    toast.success(`已删除 ${result.deleted} 个邀请码`)
  } catch (error) {
    toast.error('删除失败：' + error.message)
  }
}

// 用户行的按钮按角色显示（与后端校验一致，后端是最终防线）：
// admin 只能管理普通用户；superadmin 可改所有人的配额，可启用/禁用、删除、改角色的对象不含 superadmin
const canEditQuota = (user) => userStore.isSuperAdmin || user.role === 'user'
const canToggleStatus = (user) => user.role === 'user' || (userStore.isSuperAdmin && user.role === 'admin')
const canDeleteUser = (user) => userStore.isSuperAdmin && user.role !== 'superadmin'
const canChangeRole = (user) => userStore.isSuperAdmin && user.role !== 'superadmin'
// 查看他人文本内容：仅超管，自己的内容在各自页面看
const canViewContent = (user) => userStore.isSuperAdmin && user.id !== userStore.userInfo?.id

const handleToggleUserStatus = async (user) => {
  if (!canToggleStatus(user)) {
    toast.error('没有权限执行此操作')
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
  if (!canEditQuota(user)) {
    toast.error('没有权限执行此操作')
    return
  }

  const input = await promptDialog({
    title: `修改「${user.username}」的配额`,
    message: `当前已使用 ${formatSize(user.used_bytes || 0)}。`,
    label: '新配额',
    defaultValue: bytesToMB(user.quota_bytes),
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
    await adminStore.updateUserQuota(user.id, mbToBytes(quotaMB))
    toast.success('配额已更新')
  } catch (error) {
    toast.error('更新失败：' + error.message)
  }
}

const handleChangeRole = async (user) => {
  if (!canChangeRole(user)) {
    toast.error('仅超级管理员可修改角色')
    return
  }
  const promote = user.role === 'user'
  const ok = await confirmDialog(promote
    ? {
        title: `把「${user.username}」设为管理员？`,
        message: '管理员可以管理普通用户（改配额、启用禁用）、邀请码和系统设置，但看不到任何人的文本和文件内容，也不能删除用户。',
        confirmText: '设为管理员',
      }
    : {
        title: `取消「${user.username}」的管理员身份？`,
        message: '取消后该用户变回普通用户，立即失去管理后台的权限。',
        confirmText: '取消管理员',
        danger: true,
      })
  if (!ok) return

  try {
    await adminStore.updateUserRole(user.id, promote ? 'admin' : 'user')
    toast.success(promote ? '已设为管理员' : '已取消管理员身份')
  } catch (error) {
    toast.error('操作失败：' + error.message)
  }
}

// 超管只读查看某个用户的文本内容
const contentViewUser = ref(null)
const openContentView = (user) => {
  if (!canViewContent(user)) return
  contentViewUser.value = user
}

// 超管下载他人文件：与文件页共用下载逻辑（带进度，同一文件不重复发起）
const filesStore = useFilesStore()
const handleAdminDownload = async (file) => {
  try {
    await filesStore.downloadFile(file)
  } catch (error) {
    toast.error('下载失败：' + (error.message || '未知错误'))
  }
}
const downloadProgressText = (file) => formatDownloadProgress(filesStore.downloads[file.id], '下载')

const handleDeleteUser = async (user) => {
  if (!canDeleteUser(user)) {
    toast.error('仅超级管理员可删除用户')
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

const copyInviteCode = (code) => copyText(code, '邀请码已复制')

// ========== 系统信息 ==========
// 版本号来自服务器 .env 的 CLIPSYNC_TAG；为空表示没走 Docker 部署（开发环境）
const MAX_DEPLOY_NOTE_CHARS = 200
const deployInfo = computed(() => adminStore.deployInfo)
const versionLabel = (version) => {
  if (!version) return '开发版本'
  if (version === 'latest') return 'latest（master 最新构建）'
  return version
}
const shortCommit = (sha) => (sha ? sha.slice(0, 12) : '-')

// 已运行时长：取到数据后在本机继续累加，每 30 秒刷新一次显示
const nowTick = ref(Date.now())
let uptimeTimer = null
onMounted(() => { uptimeTimer = window.setInterval(() => { nowTick.value = Date.now() }, 30000) })
onUnmounted(() => window.clearInterval(uptimeTimer))
const uptimeText = computed(() => {
  if (!deployInfo.value) return '-'
  const elapsed = Math.max(0, Math.floor((nowTick.value - adminStore.deployInfoFetchedAt) / 1000))
  const total = deployInfo.value.uptime_seconds + elapsed
  const days = Math.floor(total / 86400)
  const hours = Math.floor((total % 86400) / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  if (days > 0) return `${days} 天 ${hours} 小时`
  if (hours > 0) return `${hours} 小时 ${minutes} 分钟`
  return minutes > 0 ? `${minutes} 分钟` : '不到 1 分钟'
})
const formatFullDate = (value) => formatDateTime(value, '-', true)

const handleEditDeployNote = async (record) => {
  const input = await promptDialog({
    title: record.note ? '修改部署备注' : '添加部署备注',
    message: `写下这次部署的说明，最多 ${MAX_DEPLOY_NOTE_CHARS} 个字；留空表示清除备注。`,
    label: '备注',
    defaultValue: record.note,
    confirmText: '保存',
  })
  if (input === null) return
  const note = input.trim()
  if (noteLength(note) > MAX_DEPLOY_NOTE_CHARS) {
    toast.error(`备注最多 ${MAX_DEPLOY_NOTE_CHARS} 个字`)
    return
  }
  if (note === record.note) return
  try {
    await adminStore.updateDeploymentNote(record.id, note)
    toast.success(note ? '备注已保存' : '备注已清除')
  } catch (error) {
    toast.error('保存失败：' + error.message)
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
        <div v-for="card in STAT_CARDS" :key="card.label" class="stat-card card card-hover">
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
              <th class="cell-actions"><span class="sr-only">操作</span></th>
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
              <td class="cell-actions">
                <!-- 按钮按权限显示：admin 只能管理普通用户；改角色、删除、查看内容仅超管（后端同样校验） -->
                <span class="row-actions">
                  <button
                    v-if="canViewContent(user)"
                    class="btn-icon"
                    title="查看文本内容"
                    aria-label="查看文本内容"
                    @click="openContentView(user)"
                  >
                    <Eye />
                  </button>
                  <button
                    v-if="canEditQuota(user)"
                    class="btn-icon"
                    title="修改配额"
                    aria-label="修改配额"
                    @click="handleUpdateQuota(user)"
                  >
                    <Pencil />
                  </button>
                  <button
                    v-if="canChangeRole(user)"
                    class="btn-icon"
                    :title="user.role === 'user' ? '设为管理员' : '取消管理员'"
                    :aria-label="user.role === 'user' ? '设为管理员' : '取消管理员'"
                    @click="handleChangeRole(user)"
                  >
                    <ShieldPlus v-if="user.role === 'user'" />
                    <ShieldMinus v-else />
                  </button>
                  <button
                    v-if="canToggleStatus(user)"
                    class="btn-icon"
                    :title="user.is_active ? '禁用' : '启用'"
                    :aria-label="user.is_active ? '禁用' : '启用'"
                    @click="handleToggleUserStatus(user)"
                  >
                    <Ban v-if="user.is_active" />
                    <CircleCheck v-else />
                  </button>
                  <button
                    v-if="canDeleteUser(user)"
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

    <!-- 邀请码管理：按批次列出，每次生成是一批（1 个也算），点开看其中的码 -->
    <div v-if="activeTab === 'invites'" class="tab-panel">
      <div class="panel-toolbar">
        <p v-if="selectedInviteIds.length === 0" class="toolbar-text">每次生成的邀请码是一批，点开查看其中的码；每个码只能注册一个账号</p>
        <p v-else class="toolbar-text toolbar-selected">已选 {{ selectedInviteIds.length }} 个</p>
        <span class="toolbar-buttons">
          <template v-if="selectedInviteIds.length > 0">
            <button class="btn btn-secondary" @click="selectedInviteIds = []">取消选择</button>
            <button class="btn btn-secondary" @click="handleEditInviteExpiry([...selectedInviteIds])">
              <CalendarClock />
              修改有效期
            </button>
          </template>
          <button class="btn btn-primary" @click="openCreateInviteModal">
            <Plus />
            创建邀请码
          </button>
        </span>
      </div>

      <div v-if="adminStore.inviteBatches.length === 0" class="empty">
        <span class="empty-icon"><Ticket :size="20" /></span>
        <p class="empty-title">还没有邀请码</p>
        <p class="empty-text">创建邀请码后发给要注册的人</p>
      </div>

      <template v-else>
        <div class="invite-filters">
          <span class="search-box">
            <Search class="search-icon" aria-hidden="true" />
            <input
              v-model="inviteSearch"
              class="input"
              type="search"
              placeholder="搜索备注、创建人或邀请码"
              aria-label="搜索备注、创建人或邀请码"
            />
          </span>
          <div class="filter-group" role="group" aria-label="按状态筛选">
            <button
              v-for="f in INVITE_FILTERS"
              :key="f.key"
              type="button"
              class="filter-chip"
              :class="{ active: inviteFilter === f.key }"
              :aria-pressed="inviteFilter === f.key"
              @click="inviteFilter = f.key"
            >
              {{ f.label }}
              <span class="filter-count">{{ filterCounts[f.key] }}</span>
            </button>
          </div>
        </div>
        <div v-if="filteredBatches.length === 0" class="empty">
          <span class="empty-icon"><Search :size="20" /></span>
          <p class="empty-title">没有符合条件的邀请码</p>
          <button type="button" class="btn btn-secondary btn-sm" @click="clearInviteFilters">清除筛选</button>
        </div>

        <ul v-else class="batch-list">
          <li v-for="batch in filteredBatches" :key="batch.id" class="batch card">
            <div class="batch-head">
              <button
                type="button"
                class="batch-toggle"
                :aria-expanded="isExpanded(batch.id)"
                :aria-controls="`invite-batch-${batch.id}`"
                @click="toggleBatch(batch.id)"
              >
                <ChevronDown class="batch-chevron" :class="{ open: isExpanded(batch.id) }" aria-hidden="true" />
                <span class="batch-main">
                  <span class="batch-title">
                    <span class="batch-note" :class="{ 'batch-note-empty': !batch.note }">{{ batch.note || '无备注' }}</span>
                    <!-- 只有一个码的批次直接显示码 -->
                    <span v-if="batch.codes.length === 1" class="code mono">{{ batch.codes[0].code }}</span>
                  </span>
                  <span class="batch-meta">
                    {{ formatDate(batch.created_at) }} · {{ batch.created_by_username }} · 共 {{ batch.codes.length }} 个 · 有效期 {{ batch.expirySummary }}
                  </span>
                </span>
              </button>
              <span class="batch-stats">
                <span v-if="batch.stats.available" class="badge badge-dot badge-success">可用 {{ batch.stats.available }}</span>
                <span v-if="batch.stats.expired" class="badge badge-dot badge-warning">已过期 {{ batch.stats.expired }}</span>
                <span v-if="batch.stats.used" class="badge badge-dot">已使用 {{ batch.stats.used }}</span>
              </span>
              <span class="row-actions">
                <button
                  class="btn btn-secondary btn-sm"
                  :disabled="batch.stats.available === 0"
                  :title="batch.stats.available === 0 ? '这批没有可用的邀请码' : '只包含还能用的邀请码'"
                  @click="copyBatchMessage(batch)"
                >
                  <Copy :size="14" />
                  复制邀请信息
                </button>
                <button
                  class="btn-icon"
                  :title="batch.note ? '修改备注' : '添加备注'"
                  :aria-label="batch.note ? '修改备注' : '添加备注'"
                  @click="handleEditBatchNote(batch)"
                >
                  <Pencil />
                </button>
                <!-- 只删未使用的码；已使用的后端保留作审计记录 -->
                <button
                  v-if="batch.unusedIds.length > 0"
                  class="btn-icon danger"
                  :title="`删除未使用的 ${batch.unusedIds.length} 个`"
                  :aria-label="`删除这批里未使用的 ${batch.unusedIds.length} 个邀请码`"
                  @click="handleDeleteUnusedInBatch(batch)"
                >
                  <Trash2 />
                </button>
              </span>
            </div>

            <div v-if="isExpanded(batch.id)" :id="`invite-batch-${batch.id}`" class="batch-body">
              <div class="table-wrap batch-table">
                <table class="table">
                  <thead>
                    <tr>
                      <th class="cell-check">
                        <input
                          type="checkbox"
                          class="checkbox"
                          aria-label="全选这批里可修改的邀请码"
                          :checked="batchSelection(batch).all"
                          :indeterminate="batchSelection(batch).some"
                          :disabled="batch.unusedIds.length === 0"
                          @change="toggleBatchSelection(batch)"
                        />
                      </th>
                      <th>邀请码</th>
                      <th>状态</th>
                      <th>过期时间</th>
                      <th>使用者</th>
                      <th class="cell-actions"><span class="sr-only">操作</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="invite in batch.codes"
                      :key="invite.id"
                      :class="{ 'row-selected': selectedInviteIds.includes(invite.id), 'row-matched': isCodeMatched(invite) }"
                    >
                      <td class="cell-check">
                        <!-- 已使用的码不能修改有效期（后端返回 409），不显示勾选框 -->
                        <input
                          v-if="isInviteSelectable(invite)"
                          type="checkbox"
                          class="checkbox"
                          :aria-label="`选择邀请码 ${invite.code}`"
                          :checked="selectedInviteIds.includes(invite.id)"
                          @change="toggleInvite(invite.id)"
                        />
                      </td>
                      <td><span class="code mono">{{ invite.code }}</span></td>
                      <td>
                        <span class="badge badge-dot" :class="INVITE_STATUS[inviteStatus(invite)].cls">
                          {{ INVITE_STATUS[inviteStatus(invite)].label }}
                        </span>
                      </td>
                      <td class="cell-muted">{{ formatDate(invite.expires_at) }}</td>
                      <td class="cell-muted">
                        {{ invite.used_by ? (invite.used_by_username || invite.used_by) : (invite.used_at ? '已删除的用户' : '—') }}
                      </td>
                      <td class="cell-actions">
                        <span class="row-actions">
                          <button class="btn btn-secondary btn-sm" @click="copyInviteCode(invite.code)">
                            <Copy :size="14" />
                            复制
                          </button>
                          <!-- 已使用的邀请码后端禁止修改有效期与删除（409），按钮不显示 -->
                          <button
                            v-if="isInviteSelectable(invite)"
                            class="btn-icon"
                            title="修改有效期"
                            aria-label="修改有效期"
                            @click="handleEditInviteExpiry([invite.id])"
                          >
                            <CalendarClock />
                          </button>
                          <button
                            v-if="isInviteSelectable(invite)"
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
              <div v-if="batch.stats.available > 1" class="batch-footer">
                <button type="button" class="btn btn-ghost btn-sm" @click="copyBatchCodes(batch)">
                  只复制可用的邀请码
                </button>
              </div>
            </div>
          </li>
        </ul>
      </template>
    </div>

    <!-- 文件元数据（admin 及以上）；安全红线：下载按钮只给超管，下载走 /api/files/{id}/download，后端只放行属主与超管 -->
    <div v-if="activeTab === 'files'" class="tab-panel">
      <div class="alert alert-info panel-note">
        <Info />
        <span v-if="userStore.isSuperAdmin">超级管理员可以下载任何用户的文件，每次下载都会记入服务器日志。</span>
        <span v-else>这里只显示文件的元数据，管理员无法查看或下载其他用户的文件内容。</span>
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
              <th v-if="userStore.isSuperAdmin" class="cell-actions"><span class="sr-only">操作</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="file in adminStore.files" :key="file.id">
              <td><span class="file-name" :title="file.original_name">{{ file.original_name }}</span></td>
              <td class="cell-muted num">{{ formatSize(file.size) }}</td>
              <td>{{ file.username }}</td>
              <td class="cell-muted">{{ formatDate(file.created_at) }}</td>
              <td v-if="userStore.isSuperAdmin" class="cell-actions">
                <button
                  class="btn-icon"
                  :title="downloadProgressText(file)"
                  :aria-label="downloadProgressText(file)"
                  :disabled="!!filesStore.downloads[file.id]"
                  @click="handleAdminDownload(file)"
                >
                  <LoaderCircle v-if="filesStore.downloads[file.id]" class="spin" />
                  <Download v-else />
                </button>
              </td>
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

    <!-- 系统设置（admin 与 superadmin 均可修改） -->
    <div v-if="activeTab === 'settings'" class="tab-panel">
      <form class="settings card" @submit.prevent="handleSaveSettings">
        <div v-if="!adminStore.settings" class="alert alert-warning">
          <CircleAlert />
          <span>当前设置未能加载，下面显示的不是真实设置，无法保存。请刷新页面重试。</span>
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
              aria-label="开放注册"
            />
            <span class="switch-track"></span>
          </label>
        </div>

        <div class="setting-row">
          <div class="setting-text">
            <span class="setting-title">显示 GitHub 链接</span>
            <span class="setting-desc">登录后在侧栏底部显示一行小字链接，指向本项目的 GitHub 主页；用户刷新页面或重新登录后生效</span>
          </div>
          <label class="switch">
            <input
              v-model="settingsForm.show_github_link"
              type="checkbox"
              aria-label="显示 GitHub 链接"
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
            />
            <span class="input-suffix">MB</span>
          </span>
        </div>

        <p class="settings-note">
          单文件上限、分片大小、历史保留条数等由 backend/.env 配置，需重启后端生效，不在此修改。
        </p>

        <div class="settings-footer">
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

    <!-- 系统信息：admin 及以上可看，只有超管能写部署备注 -->
    <div v-if="activeTab === 'system'" class="tab-panel">
      <div v-if="!deployInfo" class="alert alert-warning">
        <CircleAlert />
        <span>系统信息未能加载，请刷新页面重试。</span>
      </div>
      <template v-else>
        <div class="settings card system-info">
          <div class="setting-row">
            <span class="setting-title">版本</span>
            <span class="system-value">{{ versionLabel(deployInfo.app_version) }}</span>
          </div>
          <div class="setting-row">
            <span class="setting-title">提交号</span>
            <span class="system-value mono">{{ shortCommit(deployInfo.commit_sha) }}</span>
          </div>
          <div class="setting-row">
            <span class="setting-title">分支</span>
            <span class="system-value">{{ deployInfo.branch || '-' }}</span>
          </div>
          <div class="setting-row">
            <span class="setting-title">构建时间</span>
            <span class="system-value">{{ formatFullDate(deployInfo.built_at) }}</span>
          </div>
          <div class="setting-row">
            <span class="setting-title">部署时间</span>
            <span class="system-value">{{ formatFullDate(deployInfo.current?.deployed_at) }}</span>
          </div>
          <div class="setting-row">
            <span class="setting-title">本次启动</span>
            <span class="system-value">{{ formatFullDate(deployInfo.started_at) }}</span>
          </div>
          <div class="setting-row">
            <span class="setting-title">已运行</span>
            <span class="system-value">{{ uptimeText }}</span>
          </div>
          <p class="settings-note">
            版本取自服务器 .env 的 CLIPSYNC_TAG；提交号、分支与构建时间在打包时写入镜像。
            部署时间是这个版本第一次启动的时间，重启不会改变；本次启动时间每次重启都会更新。
          </p>
        </div>

        <h2 class="system-heading">部署记录</h2>
        <div v-if="deployInfo.history.length === 0" class="empty">
          <span class="empty-icon"><Server :size="20" /></span>
          <p class="empty-title">还没有部署记录</p>
          <p class="empty-text">后端每次以新版本启动时会自动记一条</p>
        </div>
        <div v-else class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>版本</th>
                <th>提交号</th>
                <th>部署时间</th>
                <th>备注</th>
                <th v-if="userStore.isSuperAdmin" class="cell-actions"><span class="sr-only">操作</span></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="record in deployInfo.history" :key="record.id">
                <td>
                  {{ versionLabel(record.app_version) }}
                  <span v-if="deployInfo.current?.id === record.id" class="badge badge-success">当前</span>
                </td>
                <td class="cell-muted mono" :title="record.branch">{{ shortCommit(record.commit_sha) }}</td>
                <td class="cell-muted">{{ formatFullDate(record.deployed_at) }}</td>
                <td>
                  <span v-if="record.note" class="batch-note">{{ record.note }}</span>
                  <span v-else class="batch-note-empty">无备注</span>
                </td>
                <td v-if="userStore.isSuperAdmin" class="cell-actions">
                  <button
                    class="btn-icon"
                    :title="record.note ? '修改备注' : '添加备注'"
                    :aria-label="record.note ? '修改备注' : '添加备注'"
                    @click="handleEditDeployNote(record)"
                  >
                    <Pencil />
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="deployInfo.total > deployInfo.history.length" class="settings-note">
          共 {{ deployInfo.total }} 条记录，这里显示最近 {{ deployInfo.history.length }} 条。
        </p>
      </template>
    </div>

    <!-- 创建邀请码弹窗 -->
    <!-- 生成成功后同一个弹窗切换为「生成结果」页，只列本次生成的码，方便复制 -->
    <div v-if="showCreateInviteModal" class="modal-overlay" @mousedown.self="closeCreateInviteModal">
      <form
        v-if="!createdBatch"
        class="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-invite-title"
        @submit.prevent="handleCreateInvite"
        @keydown.esc="closeCreateInviteModal"
      >
        <div class="modal-header header-with-close">
          <div>
            <h2 id="create-invite-title" class="modal-title">创建邀请码</h2>
            <p class="modal-desc">每个邀请码只能注册一个账号</p>
          </div>
          <button type="button" class="btn-icon" aria-label="关闭" @click="closeCreateInviteModal">
            <X />
          </button>
        </div>
        <div class="modal-body invite-form">
          <label class="field">
            <span class="field-label">数量</span>
            <span class="input-with-suffix">
              <input
                v-model.number="inviteForm.count"
                class="input"
                type="number"
                min="1"
                :max="MAX_INVITE_BATCH"
                placeholder="1"
              />
              <span class="input-suffix">个</span>
            </span>
            <span class="field-hint">一次最多 {{ MAX_INVITE_BATCH }} 个</span>
          </label>
          <!-- 外层不用 label：里面的快捷按钮不能被当成输入框的标签区域 -->
          <div class="field">
            <label class="field-label" for="invite-expiry-days">有效期</label>
            <span class="input-with-suffix">
              <input
                id="invite-expiry-days"
                v-model.number="inviteForm.expires_in_days"
                class="input"
                type="number"
                min="0"
                placeholder="7"
              />
              <span class="input-suffix">天</span>
            </span>
            <div class="expiry-presets" role="group" aria-label="快捷设置有效期">
              <button
                v-for="preset in EXPIRY_PRESETS"
                :key="preset.days"
                type="button"
                class="filter-chip preset-chip"
                :class="{ active: Number(inviteForm.expires_in_days) === preset.days && inviteForm.expires_in_days !== '' }"
                :aria-pressed="Number(inviteForm.expires_in_days) === preset.days && inviteForm.expires_in_days !== ''"
                @click="inviteForm.expires_in_days = preset.days"
              >
                {{ preset.label }}
              </button>
            </div>
            <span class="field-hint">0 表示永久有效；同一批共用这个有效期，生成后可以再改</span>
          </div>
          <label class="field">
            <span class="field-label">备注<span class="field-optional">（选填）</span></span>
            <input
              v-model="inviteForm.note"
              class="input"
              type="text"
              :maxlength="MAX_INVITE_NOTE_CHARS"
              placeholder="例如：给设计组新同事"
            />
            <span class="field-hint">写下这批邀请码的用途，以后看到没用掉的码就知道该不该删；最多 {{ MAX_INVITE_NOTE_CHARS }} 个字，生成后可以再改</span>
          </label>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="closeCreateInviteModal">取消</button>
          <button type="submit" class="btn btn-primary" :disabled="isCreatingInvite">
            <LoaderCircle v-if="isCreatingInvite" class="spin" />
            生成
          </button>
        </div>
      </form>

      <div
        v-else
        class="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="created-invite-title"
        @keydown.esc="closeCreateInviteModal"
      >
        <div class="modal-header header-with-close">
          <div>
            <h2 id="created-invite-title" class="modal-title">已生成 {{ createdBatch.codes.length }} 个邀请码</h2>
            <p class="modal-desc">
              {{ createdExpiry ? `有效期至 ${createdExpiry}` : '长期有效' }}<template v-if="createdBatch.note"> · {{ createdBatch.note }}</template>
            </p>
          </div>
          <button type="button" class="btn-icon" aria-label="关闭" @click="closeCreateInviteModal">
            <X />
          </button>
        </div>
        <div class="modal-body">
          <ul class="created-list">
            <li v-for="invite in createdBatch.codes" :key="invite.id" class="created-item">
              <span class="created-code mono">{{ invite.code }}</span>
              <button type="button" class="btn btn-secondary btn-sm" @click="copyInviteCode(invite.code)">
                <Copy :size="14" />
                复制
              </button>
            </li>
          </ul>
        </div>
        <div class="modal-footer created-footer">
          <span class="created-copy">
            <button type="button" class="btn btn-secondary" @click="copyCreatedCodes">
              复制邀请码
            </button>
            <button type="button" class="btn btn-secondary" @click="copyCreatedMessage">
              复制邀请信息
            </button>
          </span>
          <button type="button" class="btn btn-primary" @click="closeCreateInviteModal">完成</button>
        </div>
      </div>
    </div>

    <!-- 超管只读查看用户文本内容 -->
    <UserContentDialog v-if="contentViewUser" :user="contentViewUser" @close="contentViewUser = null" />
  </div>
</template>

<style scoped>
.stat-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
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

/* 邀请码勾选列：原生复选框，跟随强调色 */
.table .cell-check {
  width: 40px;
  padding-right: 0;
}

.checkbox {
  width: 15px;
  height: 15px;
  margin: 0;
  vertical-align: middle;
  accent-color: var(--color-accent);
  cursor: pointer;
}

.checkbox:disabled {
  cursor: default;
}

.table tbody tr.row-selected td {
  background: var(--color-accent-subtle);
}

.toolbar-buttons {
  display: inline-flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.toolbar-selected {
  color: var(--color-text);
  font-weight: 500;
}

/* 邀请码：搜索与状态筛选 */
.invite-filters {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.search-box {
  position: relative;
  flex: 1 1 260px;
  max-width: 360px;
}

.search-box .input {
  padding-left: 34px;
}

.search-icon {
  position: absolute;
  left: 10px;
  top: 50%;
  width: 16px;
  height: 16px;
  transform: translateY(-50%);
  color: var(--color-text-tertiary);
  pointer-events: none;
}

.filter-group {
  display: inline-flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.filter-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  padding: 0 var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  background: var(--color-bg);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  transition: color var(--duration) var(--ease), border-color var(--duration) var(--ease),
    background-color var(--duration) var(--ease);
}

.filter-chip:hover {
  color: var(--color-text);
  border-color: var(--color-border-strong);
}

.filter-chip.active {
  border-color: var(--color-accent);
  background: var(--color-accent-subtle);
  color: var(--color-accent);
}

.filter-count {
  font-size: var(--text-xs);
  font-variant-numeric: tabular-nums;
  opacity: 0.8;
}

/* 邀请码批次卡片 */
.batch-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.batch-head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
}

.batch-toggle {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  flex: 1;
  min-width: 0;
  padding: 0;
  text-align: left;
  color: inherit;
}

.batch-toggle:focus-visible {
  outline: 2px solid var(--color-accent);
  outline-offset: 2px;
  border-radius: var(--radius-sm);
}

.batch-chevron {
  flex-shrink: 0;
  width: 16px;
  height: 16px;
  margin-top: 3px;
  color: var(--color-text-tertiary);
  transform: rotate(-90deg);
  transition: transform var(--duration) var(--ease);
}

.batch-chevron.open {
  transform: rotate(0deg);
}

.batch-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.batch-title {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
  min-width: 0;
}

.batch-note {
  font-weight: 500;
  color: var(--color-text);
  overflow-wrap: anywhere;
}

.batch-note-empty {
  font-weight: 400;
  color: var(--color-text-tertiary);
}

.batch-meta {
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
}

.batch-stats {
  display: inline-flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--space-1);
}

.batch-body {
  padding: 0 var(--space-4) var(--space-4);
}

/* 批次里的表格嵌在卡片中：去掉外层玻璃效果，避免叠两层 */
.batch-table {
  background: var(--color-bg);
  box-shadow: none;
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
}

.table tbody tr.row-matched td {
  background: var(--color-warning-subtle);
}

.batch-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: var(--space-2);
}

/* 创建邀请码弹窗：有效期快捷按钮，沿用筛选按钮的样式，略小一号 */
.expiry-presets {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.preset-chip {
  height: 28px;
  font-size: var(--text-xs);
}

.field-optional {
  font-weight: 400;
  color: var(--color-text-tertiary);
}

/* 生成结果页：只列本次生成的码 */
.created-list {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.created-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--color-border);
}

.created-item:last-child {
  border-bottom: none;
}

.created-code {
  font-size: var(--text-base);
  letter-spacing: 0.04em;
  color: var(--color-text);
}

.created-footer {
  justify-content: space-between;
  flex-wrap: wrap;
}

.created-copy {
  display: inline-flex;
  flex-wrap: wrap;
  gap: var(--space-2);
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

.system-info .setting-row {
  padding: var(--space-3) 0;
}

.system-value {
  font-size: var(--text-sm);
  color: var(--color-text);
  text-align: right;
  overflow-wrap: anywhere;
}

.system-heading {
  margin: var(--space-6) 0 var(--space-3);
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--color-text);
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

  .search-box {
    max-width: none;
  }

  .batch-head {
    flex-wrap: wrap;
  }

  .batch-toggle {
    flex-basis: 100%;
  }

  .batch-stats {
    justify-content: flex-start;
    flex: 1;
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
