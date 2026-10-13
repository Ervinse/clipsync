<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { Plus, Copy, Ban, Link, Clipboard, File, LoaderCircle, X, TriangleAlert, RotateCw } from '@lucide/vue'
import { useAccessStore, useFilesStore } from '../stores'
import { formatDateTime, parseUtc } from '../utils/format'
import { copyToClipboard } from '../utils/clipboard'
import toast from '../utils/toast'
import { confirmDialog, copyDialog, dialogState } from '../utils/dialog'
import ws from '../utils/websocket'

const accessStore = useAccessStore()
const filesStore = useFilesStore()

// 其他终端创建 / 撤销访问码，或删除文件（后端级联删码）后静默刷新列表（不闪成「加载中」）；重连时补拉一次
const onCodesChanged = () => {
  accessStore.fetchCodes({ silent: true }).catch(() => {})
}
const CODE_EVENTS = ['access_codes_changed', 'file_deleted', 'open']

// 「创建访问码」弹窗的文件下拉读 filesStore.files：其他终端上传 / 删除文件后同步刷新，
// 否则会选到已删除的文件（创建时 404），或看不到新上传的文件
const onFilesChanged = () => {
  filesStore.fetchFiles({ silent: true }).catch(() => {})
}
const FILE_EVENTS = ['file_added', 'file_deleted', 'open']

// 「是否过期」随时间变化：页面开着时每 30 秒重算一次，到期的码自动变成「已过期」
const now = ref(Date.now())
let nowTimer = null

// Esc 关闭「创建访问码」弹窗；全局对话框（确认 / 手动复制）打开时 Esc 只作用于它
const onEscape = (event) => {
  if (event.key === 'Escape' && showCreateModal.value && !dialogState.current) closeCreateModal()
}

onUnmounted(() => {
  CODE_EVENTS.forEach((event) => ws.off(event, onCodesChanged))
  FILE_EVENTS.forEach((event) => ws.off(event, onFilesChanged))
  window.removeEventListener('keydown', onEscape)
  clearInterval(nowTimer)
})

// 访问码最长有效期：1 年
const MAX_EXPIRES_HOURS = 8760

// 常用有效期，点选后填入输入框
const EXPIRY_PRESETS = [
  { label: '1 小时', hours: 1 },
  { label: '1 天', hours: 24 },
  { label: '7 天', hours: 168 },
  { label: '永久', hours: 0 },
]

const showCreateModal = ref(false)
const isCreating = ref(false)
const createForm = ref({
  target_type: 'text',
  file_id: null,
  expires_in_hours: 24,
})

// 失败原因记在 store.loadError，页面显示「加载失败 + 重试」，不会把没加载出来误当成没有访问码
const loadCodes = () => accessStore.fetchCodes().catch(() => {})

onMounted(() => {
  // 先挂监听再拉数据，拉取期间的变更不会漏掉
  CODE_EVENTS.forEach((event) => ws.on(event, onCodesChanged))
  FILE_EVENTS.forEach((event) => ws.on(event, onFilesChanged))
  window.addEventListener('keydown', onEscape)
  nowTimer = setInterval(() => { now.value = Date.now() }, 30000)
  // 文件列表只用于创建弹窗的下拉和显示文件名，加载失败不影响访问码列表
  filesStore.fetchFiles({ silent: true }).catch(() => {})
  return loadCodes()
})

const openCreateModal = () => {
  // 打开弹窗时再静默刷新一次文件列表，保证下拉里是最新的
  onFilesChanged()
  createForm.value = {
    target_type: 'text',
    file_id: null,
    expires_in_hours: 24,
  }
  showCreateModal.value = true
}

const closeCreateModal = () => {
  showCreateModal.value = false
}

const handleCreate = async () => {
  const data = { ...createForm.value }

  // 文件类型必须选择文件
  if (data.target_type === 'file' && !data.file_id) {
    toast.error('请选择要分享的文件')
    return
  }

  // 文本类型不需要 file_id
  if (data.target_type === 'text') {
    delete data.file_id
  }

  // 后端接收 expires_at（ISO 时间，带时区）；0 或空表示永久有效，最长 8760 小时（后端同样校验）
  const hours = Number(data.expires_in_hours || 0)
  if (!Number.isInteger(hours) || hours < 0 || hours > MAX_EXPIRES_HOURS) {
    toast.error(`有效期必须是 0 到 ${MAX_EXPIRES_HOURS} 之间的整数（小时）`)
    return
  }
  delete data.expires_in_hours
  data.expires_at = hours > 0
    ? new Date(Date.now() + hours * 3600 * 1000).toISOString()
    : null

  try {
    isCreating.value = true
    await accessStore.createCode(data)
    closeCreateModal()
    toast.success('访问码已创建')
  } catch (error) {
    toast.error('创建失败：' + error.message)
  } finally {
    isCreating.value = false
  }
}

const handleRevoke = async (code) => {
  const ok = await confirmDialog({
    title: '撤销这个访问码？',
    message: '撤销后链接立即失效，无法恢复。',
    confirmText: '撤销',
    danger: true,
  })
  if (!ok) return

  try {
    await accessStore.revokeCode(code.id)
  } catch (error) {
    toast.error('撤销失败：' + error.message)
  }
}

// 链接由后端按请求 scheme + host 拼好（access_url），前端不自行拼接
const copyLink = async (code) => {
  if (await copyToClipboard(code.access_url)) {
    toast.success('链接已复制')
  } else {
    copyDialog({ value: code.access_url })
  }
}

const formatDate = (value) => formatDateTime(value, '永久有效')

const getFileName = (fileId) => {
  const file = filesStore.files.find(f => f.id === fileId)
  return file?.original_name || '未知文件'
}

// 后端时间为 UTC（不带时区后缀），parseUtc 按 UTC 解析
const isExpired = (code) => {
  const expiresAt = parseUtc(code.expires_at)
  return !!expiresAt && expiresAt.getTime() <= now.value
}

// 已撤销或已过期都算失效（不能再复制链接 / 撤销）
const isInvalid = (code) => code.is_revoked || isExpired(code)

const statusOf = (code) => {
  if (code.is_revoked) return { label: '已撤销', cls: '' }
  if (isExpired(code)) return { label: '已过期', cls: '' }
  return { label: '有效', cls: 'badge-success' }
}
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">访问码</h1>
        <p class="page-subtitle">生成免登录的分享链接，对方打开链接即可查看文本或下载文件</p>
      </div>
      <div class="page-actions">
        <button class="btn btn-primary" @click="openCreateModal">
          <Plus />
          创建访问码
        </button>
      </div>
    </div>

    <div v-if="accessStore.isLoading" class="loading">
      <LoaderCircle class="spin" />
      加载中…
    </div>

    <div v-else-if="accessStore.loadError" class="empty" role="alert">
      <span class="empty-icon"><TriangleAlert :size="20" /></span>
      <p class="empty-title">访问码加载失败</p>
      <p class="empty-text">{{ accessStore.loadError }}</p>
      <button class="btn btn-secondary" @click="loadCodes">
        <RotateCw />
        重试
      </button>
    </div>

    <div v-else-if="accessStore.codes.length === 0" class="empty">
      <span class="empty-icon"><Link :size="20" /></span>
      <p class="empty-title">还没有访问码</p>
      <p class="empty-text">分享当前文本或某个文件给没有账号的人</p>
      <button class="btn btn-secondary" @click="openCreateModal">
        <Plus />
        创建第一个访问码
      </button>
    </div>

    <div v-else class="table-wrap">
      <table class="table">
        <thead>
          <tr>
            <th>内容</th>
            <th>访问码</th>
            <th>状态</th>
            <th>过期时间</th>
            <th class="col-created">创建时间</th>
            <th class="cell-actions"><span class="sr-only">操作</span></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="code in accessStore.sortedCodes"
            :key="code.id"
            :class="{ invalid: isInvalid(code) }"
          >
            <td>
              <span class="target">
                <span class="target-icon">
                  <Clipboard v-if="code.target_type === 'text'" />
                  <File v-else />
                </span>
                <span class="target-text">
                  <span class="target-type">{{ code.target_type === 'text' ? '当前文本' : '文件' }}</span>
                  <span v-if="code.target_type === 'file'" class="target-name" :title="getFileName(code.file_id)">
                    {{ getFileName(code.file_id) }}
                  </span>
                  <span v-else class="target-name">实时指向最新内容</span>
                </span>
              </span>
            </td>
            <td><span class="code mono">{{ code.code }}</span></td>
            <td>
              <span class="badge badge-dot" :class="statusOf(code).cls">{{ statusOf(code).label }}</span>
            </td>
            <td class="cell-muted">{{ formatDate(code.expires_at) }}</td>
            <td class="cell-muted col-created">{{ formatDate(code.created_at) }}</td>
            <td class="cell-actions">
              <span class="row-actions">
                <button
                  class="btn btn-secondary btn-sm"
                  :disabled="isInvalid(code)"
                  @click="copyLink(code)"
                >
                  <Copy :size="14" />
                  复制链接
                </button>
                <button
                  class="btn-icon danger"
                  title="撤销"
                  aria-label="撤销"
                  :disabled="isInvalid(code)"
                  @click="handleRevoke(code)"
                >
                  <Ban />
                </button>
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 创建访问码弹窗 -->
    <div v-if="showCreateModal" class="modal-overlay" @mousedown.self="closeCreateModal">
      <form
        class="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-code-title"
        @submit.prevent="handleCreate"
        @keydown.esc="closeCreateModal"
      >
        <div class="modal-header header-with-close">
          <div>
            <h2 id="create-code-title" class="modal-title">创建访问码</h2>
            <p class="modal-desc">拿到链接的人无需登录即可访问</p>
          </div>
          <button type="button" class="btn-icon" aria-label="关闭" @click="closeCreateModal">
            <X />
          </button>
        </div>

        <div class="modal-body">
          <div class="field">
            <span class="field-label">分享内容</span>
            <div class="choice-group" role="radiogroup">
              <label class="choice" :class="{ active: createForm.target_type === 'text' }">
                <input v-model="createForm.target_type" type="radio" value="text" class="sr-only" />
                <Clipboard />
                <span>
                  <span class="choice-title">当前文本</span>
                  <span class="choice-desc">实时同步最新内容</span>
                </span>
              </label>
              <label class="choice" :class="{ active: createForm.target_type === 'file' }">
                <input v-model="createForm.target_type" type="radio" value="file" class="sr-only" />
                <File />
                <span>
                  <span class="choice-title">指定文件</span>
                  <span class="choice-desc">分享一个已上传的文件</span>
                </span>
              </label>
            </div>
          </div>

          <label v-if="createForm.target_type === 'file'" class="field">
            <span class="field-label">选择文件</span>
            <select v-model="createForm.file_id" class="select">
              <option :value="null">请选择文件</option>
              <option v-for="file in filesStore.files" :key="file.id" :value="file.id">
                {{ file.original_name }}
              </option>
            </select>
            <span v-if="filesStore.files.length === 0" class="field-hint">还没有上传文件，请先到「文件」页上传</span>
          </label>

          <div class="field">
            <label class="field-label" for="expires-hours">有效期</label>
            <div class="presets">
              <button
                v-for="preset in EXPIRY_PRESETS"
                :key="preset.label"
                type="button"
                class="preset"
                :class="{ active: Number(createForm.expires_in_hours || 0) === preset.hours }"
                @click="createForm.expires_in_hours = preset.hours"
              >
                {{ preset.label }}
              </button>
            </div>
            <span class="input-with-suffix">
              <input
                id="expires-hours"
                v-model.number="createForm.expires_in_hours"
                class="input"
                type="number"
                min="0"
                :max="MAX_EXPIRES_HOURS"
                placeholder="0 为永久"
              />
              <span class="input-suffix">小时</span>
            </span>
            <span class="field-hint">0 表示永久有效，最长 8760 小时（1 年）</span>
          </div>
        </div>

        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="closeCreateModal">取消</button>
          <button type="submit" class="btn btn-primary" :disabled="isCreating">
            <LoaderCircle v-if="isCreating" class="spin" />
            创建
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<style scoped>
tr.invalid td {
  color: var(--color-text-tertiary);
}

.target {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}

.target-icon {
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

.target-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
  line-height: 1.35;
}

.target-type {
  font-weight: 500;
}

.target-name {
  max-width: 220px;
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
  overflow: hidden;
  text-overflow: ellipsis;
}

.code {
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  background: var(--color-bg-muted);
  color: var(--color-text);
}

.row-actions {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}

.header-with-close {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
}

.choice-group {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-2);
}

.choice {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: var(--space-3);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  cursor: pointer;
  color: var(--color-text-secondary);
  transition: border-color var(--duration) var(--ease), background-color var(--duration) var(--ease);
}

.choice svg {
  flex-shrink: 0;
  margin-top: 2px;
}

.choice:hover {
  border-color: var(--color-border-hover);
}

.choice.active {
  border-color: var(--color-text);
  box-shadow: 0 0 0 1px var(--color-text);
  color: var(--color-text);
}

.choice:focus-within {
  box-shadow: 0 0 0 3px var(--color-focus-ring);
}

.choice-title {
  display: block;
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--color-text);
}

.choice-desc {
  display: block;
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}

.presets {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.preset {
  height: 28px;
  padding: 0 10px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--color-text-secondary);
  transition: all var(--duration) var(--ease);
}

.preset:hover {
  border-color: var(--color-border-hover);
  color: var(--color-text);
}

.preset.active {
  background: var(--color-primary);
  border-color: var(--color-primary);
  color: var(--color-text-inverse);
}

.input-with-suffix {
  position: relative;
  display: block;
}

.input-with-suffix .input {
  padding-right: 52px;
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

/* 中等宽度时省掉次要的「创建时间」列，表格不必横向滚动 */
@media (max-width: 1280px) {
  .col-created {
    display: none;
  }
}

@media (max-width: 480px) {
  .choice-group {
    grid-template-columns: 1fr;
  }
}
</style>
