<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useAccessStore, useFilesStore } from '../stores'
import { formatDateTime } from '../utils/format'
import { copyToClipboard } from '../utils/clipboard'
import ws from '../utils/websocket'

const accessStore = useAccessStore()
const filesStore = useFilesStore()

// 其他终端创建 / 撤销访问码，或删除文件（后端级联删码）后刷新列表；重连时补拉一次
const onCodesChanged = () => {
  accessStore.fetchCodes().catch(() => {})
}
const CODE_EVENTS = ['access_codes_changed', 'file_deleted', 'open']

// 「创建访问码」弹窗的文件下拉读 filesStore.files：其他终端上传 / 删除文件后同步刷新，
// 否则会选到已删除的文件（创建时 404），或看不到新上传的文件
const onFilesChanged = () => {
  filesStore.fetchFiles({ silent: true }).catch(() => {})
}
const FILE_EVENTS = ['file_added', 'file_deleted', 'open']

onUnmounted(() => {
  CODE_EVENTS.forEach((event) => ws.off(event, onCodesChanged))
  FILE_EVENTS.forEach((event) => ws.off(event, onFilesChanged))
})

// 访问码最长有效期：1 年
const MAX_EXPIRES_HOURS = 8760

const showCreateModal = ref(false)
const createForm = ref({
  target_type: 'text',
  file_id: null,
  expires_in_hours: 24,
})

onMounted(async () => {
  // 先挂监听再拉数据，拉取期间的变更不会漏掉
  CODE_EVENTS.forEach((event) => ws.on(event, onCodesChanged))
  FILE_EVENTS.forEach((event) => ws.on(event, onFilesChanged))
  await Promise.all([
    accessStore.fetchCodes(),
    filesStore.fetchFiles(),
  ])
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
  try {
    const data = { ...createForm.value }

    // 文件类型必须选择文件
    if (data.target_type === 'file' && !data.file_id) {
      alert('请选择要分享的文件')
      return
    }

    // 文本类型不需要 file_id
    if (data.target_type === 'text') {
      delete data.file_id
    }

    // 后端接收 expires_at（ISO 时间，带时区）；0 或空表示永久有效，最长 8760 小时（后端同样校验）
    const hours = Number(data.expires_in_hours || 0)
    if (!Number.isInteger(hours) || hours < 0 || hours > MAX_EXPIRES_HOURS) {
      alert(`有效期必须是 0 到 ${MAX_EXPIRES_HOURS} 之间的整数（小时）`)
      return
    }
    delete data.expires_in_hours
    data.expires_at = hours > 0
      ? new Date(Date.now() + hours * 3600 * 1000).toISOString()
      : null

    await accessStore.createCode(data)
    closeCreateModal()
  } catch (error) {
    alert('创建失败：' + error.message)
  }
}

const handleRevoke = async (code) => {
  if (!confirm('确定撤销此访问码吗？撤销后链接将失效。')) return

  try {
    await accessStore.revokeCode(code.id)
  } catch (error) {
    alert('撤销失败：' + error.message)
  }
}

// 链接由后端按请求 scheme + host 拼好（access_url），前端不自行拼接
const copyLink = async (code) => {
  if (await copyToClipboard(code.access_url)) {
    alert('链接已复制到剪贴板')
  } else {
    prompt('复制失败，请手动复制：', code.access_url)
  }
}

const formatDate = (value) => formatDateTime(value, '永久有效')

const getFileName = (fileId) => {
  const file = filesStore.files.find(f => f.id === fileId)
  return file?.original_name || '未知文件'
}
</script>

<template>
  <div class="access-page">
    <div class="page-header">
      <div>
        <h2>访问码管理</h2>
        <p>创建免登录分享链接</p>
      </div>
      <button class="btn-primary" @click="openCreateModal">
        + 创建访问码
      </button>
    </div>

    <div v-if="accessStore.isLoading" class="loading-state">
      加载中...
    </div>

    <div v-else-if="accessStore.codes.length === 0" class="empty-state">
      <div class="empty-icon">🔗</div>
      <p>还没有创建访问码</p>
      <button class="btn-secondary" @click="openCreateModal">
        创建第一个访问码
      </button>
    </div>

    <div v-else class="codes-list">
      <div
        v-for="code in accessStore.sortedCodes"
        :key="code.id"
        class="code-card"
      >
        <div class="code-header">
          <span class="code-type" :class="code.target_type">
            {{ code.target_type === 'text' ? '📋 文本' : '📁 文件' }}
          </span>
          <span class="code-status" :class="{ expired: code.is_invalid }">
            {{ code.is_revoked ? '已撤销' : code.expired ? '已过期' : '有效' }}
          </span>
        </div>

        <div class="code-body">
          <div class="code-info">
            <div class="code-label">访问码</div>
            <div class="code-value">{{ code.code }}</div>
          </div>

          <div v-if="code.target_type === 'file'" class="code-info">
            <div class="code-label">文件</div>
            <div class="code-value">{{ getFileName(code.file_id) }}</div>
          </div>

          <div class="code-info">
            <div class="code-label">过期时间</div>
            <div class="code-value">{{ formatDate(code.expires_at) }}</div>
          </div>

          <div class="code-info">
            <div class="code-label">创建时间</div>
            <div class="code-value">{{ formatDate(code.created_at) }}</div>
          </div>
        </div>

        <div class="code-actions">
          <button
            class="btn-secondary"
            @click="copyLink(code)"
            :disabled="code.is_invalid"
          >
            复制链接
          </button>
          <button
            class="btn-danger"
            @click="handleRevoke(code)"
            :disabled="code.is_invalid"
          >
            撤销
          </button>
        </div>
      </div>
    </div>

    <!-- 创建访问码弹窗 -->
    <div v-if="showCreateModal" class="modal-overlay" @click="closeCreateModal">
      <div class="modal-content" @click.stop>
        <h3>创建访问码</h3>

        <div class="form-group">
          <label>分享类型</label>
          <select v-model="createForm.target_type">
            <option value="text">当前文本（实时同步）</option>
            <option value="file">指定文件</option>
          </select>
        </div>

        <div v-if="createForm.target_type === 'file'" class="form-group">
          <label>选择文件</label>
          <select v-model="createForm.file_id">
            <option :value="null">-- 请选择文件 --</option>
            <option
              v-for="file in filesStore.files"
              :key="file.id"
              :value="file.id"
            >
              {{ file.original_name }}
            </option>
          </select>
        </div>

        <div class="form-group">
          <label>有效期（小时）</label>
          <input
            v-model.number="createForm.expires_in_hours"
            type="number"
            min="0"
            max="8760"
            placeholder="24"
          />
          <div class="form-hint">
            0 表示永久有效，最长 8760 小时（1 年）
          </div>
        </div>

        <div class="modal-actions">
          <button class="btn-secondary" @click="closeCreateModal">
            取消
          </button>
          <button class="btn-primary" @click="handleCreate">
            创建
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.access-page {
  padding: 2rem;
  max-width: 1400px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 2rem;
}

.page-header h2 {
  font-size: 1.75rem;
  font-weight: 700;
  color: #F8FAFC;
  margin-bottom: 0.5rem;
}

.page-header p {
  font-size: 0.95rem;
  color: #94A3B8;
}

.btn-primary,
.btn-secondary,
.btn-danger {
  padding: 0.75rem 1.5rem;
  border: none;
  border-radius: 8px;
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-primary {
  background: #38BDF8;
  color: #0F172A;
}

.btn-primary:hover:not(:disabled) {
  background: #22D3EE;
  transform: translateY(-1px);
}

.btn-secondary {
  background: rgba(148, 163, 184, 0.1);
  color: #CBD5E1;
  border: 1px solid #334155;
}

.btn-secondary:hover:not(:disabled) {
  background: rgba(148, 163, 184, 0.15);
  border-color: #475569;
}

.btn-secondary:disabled,
.btn-danger:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-danger {
  background: rgba(239, 68, 68, 0.1);
  color: #FCA5A5;
  border: 1px solid rgba(239, 68, 68, 0.3);
}

.btn-danger:hover:not(:disabled) {
  background: rgba(239, 68, 68, 0.2);
  border-color: rgba(239, 68, 68, 0.5);
}

.loading-state,
.empty-state {
  text-align: center;
  padding: 4rem 2rem;
  color: #64748B;
}

.empty-icon {
  font-size: 4rem;
  margin-bottom: 1rem;
}

.empty-state p {
  font-size: 1.1rem;
  margin-bottom: 1.5rem;
}

.codes-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
  gap: 1.5rem;
}

.code-card {
  padding: 1.5rem;
  background: #1E293B;
  border: 1px solid #334155;
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.code-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.code-type {
  padding: 0.375rem 0.75rem;
  border-radius: 6px;
  font-size: 0.85rem;
  font-weight: 600;
}

.code-type.text {
  background: rgba(56, 189, 248, 0.15);
  color: #38BDF8;
  border: 1px solid rgba(56, 189, 248, 0.3);
}

.code-type.file {
  background: rgba(249, 115, 22, 0.15);
  color: #F97316;
  border: 1px solid rgba(249, 115, 22, 0.3);
}

.code-status {
  padding: 0.25rem 0.625rem;
  border-radius: 4px;
  font-size: 0.8rem;
  font-weight: 600;
  background: rgba(34, 211, 238, 0.15);
  color: #22D3EE;
  border: 1px solid rgba(34, 211, 238, 0.3);
}

.code-status.expired {
  background: rgba(100, 116, 139, 0.15);
  color: #94A3B8;
  border-color: #475569;
}

.code-body {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.code-info {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.code-label {
  font-size: 0.8rem;
  color: #64748B;
}

.code-value {
  font-size: 0.95rem;
  color: #CBD5E1;
  font-family: 'IBM Plex Sans', monospace;
}

.code-actions {
  display: flex;
  gap: 0.75rem;
  padding-top: 0.5rem;
  border-top: 1px solid #334155;
}

.code-actions button {
  flex: 1;
  padding: 0.625rem;
  font-size: 0.875rem;
}

/* 弹窗样式 */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-content {
  width: 90%;
  max-width: 480px;
  background: #1E293B;
  border: 1px solid #334155;
  border-radius: 12px;
  padding: 2rem;
}

.modal-content h3 {
  font-size: 1.5rem;
  font-weight: 700;
  color: #F8FAFC;
  margin-bottom: 1.5rem;
}

.form-group {
  margin-bottom: 1.5rem;
}

.form-group label {
  display: block;
  font-size: 0.9rem;
  font-weight: 500;
  color: #CBD5E1;
  margin-bottom: 0.5rem;
}

.form-group input,
.form-group select {
  width: 100%;
  padding: 0.75rem 1rem;
  background: #0F172A;
  border: 1px solid #334155;
  border-radius: 8px;
  color: #F8FAFC;
  font-size: 0.95rem;
  transition: all 0.2s;
}

.form-group input:focus,
.form-group select:focus {
  outline: none;
  border-color: #38BDF8;
  box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.1);
}

.form-hint {
  margin-top: 0.5rem;
  font-size: 0.85rem;
  color: #64748B;
}

.modal-actions {
  display: flex;
  gap: 1rem;
  justify-content: flex-end;
  margin-top: 2rem;
}
</style>