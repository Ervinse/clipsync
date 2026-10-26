<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import {
  Upload, Download, Trash2, LoaderCircle, FolderOpen, TriangleAlert, RotateCw,
  File, FileText, FileImage, FileArchive, FileVideoCamera, FileMusic, FileCode, FileSpreadsheet,
} from '@lucide/vue'
import { useFilesStore, useUserStore } from '../stores'
import { formatSize, formatDateTime, formatDownloadProgress } from '../utils/format'
import toast from '../utils/toast'
import { confirmDialog } from '../utils/dialog'
import AccessCodeButton from '../components/AccessCodeButton.vue'
import AccessCodeDialog from '../components/AccessCodeDialog.vue'
import LoadingSkeleton from '../components/LoadingSkeleton.vue'

const filesStore = useFilesStore()
const userStore = useUserStore()

const uploadInput = ref(null)
// 上传状态在 store 中：离开页面再回来仍能看到正在上传，按钮保持禁用
const isUploading = computed(() => filesStore.isUploading)

// 失败原因记在 store.loadError，页面显示「加载失败 + 重试」，不会把没加载出来误当成没有文件
const loadFiles = () => filesStore.fetchFiles().catch(() => {})

onMounted(() => {
  // 先挂监听再拉列表，避免拉取期间漏掉其他终端的变更
  filesStore.setupWebSocket()
  return loadFiles()
})

onUnmounted(() => {
  filesStore.cleanupWebSocket()
})

const uploadProgress = computed(() => {
  const progress = Object.values(filesStore.uploadProgress)
  return progress.length > 0 ? progress[0] : null
})

const handleFileSelect = () => {
  uploadInput.value?.click()
}

const handleFileChange = async (event) => {
  const file = event.target.files?.[0]
  if (!file) return

  try {
    await filesStore.uploadFile(file)
    toast.success(`「${file.name}」上传完成`)
  } catch (error) {
    // 退出登录导致的中断：用户已在退出确认里同意，不再提示
    if (!error?.cancelled) toast.error('上传失败：' + error.message)
  } finally {
    if (uploadInput.value) {
      uploadInput.value.value = ''
    }
  }
}

const handleDownload = async (file) => {
  try {
    await filesStore.downloadFile(file)
  } catch (error) {
    toast.error('下载失败：' + (error.message || '未知错误'))
  }
}

// 下载中的状态文字：浏览器要收完整个文件才弹出保存，期间显示进度，避免用户以为没反应而重复点击
const downloadText = (file) => formatDownloadProgress(filesStore.downloads[file.id])

const handleDelete = async (file) => {
  const ok = await confirmDialog({
    title: '删除这个文件？',
    message: `「${file.original_name}」将被永久删除，无法找回${file.access_code ? `，它的访问码 ${file.access_code} 也会一并清除` : ''}。`,
    confirmText: '删除',
    danger: true,
  })
  if (!ok) return

  try {
    await filesStore.deleteFile(file.id)
    toast.success('文件已删除')
  } catch (error) {
    toast.error('删除失败：' + error.message)
  }
}

const codeTarget = ref(null)
const openCode = (file) => {
  codeTarget.value = {
    targetType: 'file',
    targetId: file.id,
    label: file.original_name,
    code: file.access_code,
    expiresAt: file.access_expires_at,
  }
}
const onCodeSaved = (result) => {
  filesStore.patchFile(result.target_id, {
    access_code: result.access_code,
    access_expires_at: result.access_expires_at,
  })
}

// 按 MIME 类型与扩展名选图标，只影响显示
const EXT_ICONS = [
  [/\.(zip|rar|7z|tar|gz|tgz|bz2|xz)$/i, FileArchive],
  [/\.(xlsx?|csv|numbers)$/i, FileSpreadsheet],
  [/\.(js|ts|py|java|go|rs|c|cpp|h|json|ya?ml|xml|html?|css|sh|sql)$/i, FileCode],
  [/\.(txt|md|pdf|docx?|rtf|pages)$/i, FileText],
]
const fileIcon = (file) => {
  const mime = file.mime_type || ''
  if (mime.startsWith('image/')) return FileImage
  if (mime.startsWith('video/')) return FileVideoCamera
  if (mime.startsWith('audio/')) return FileMusic
  const match = EXT_ICONS.find(([pattern]) => pattern.test(file.original_name))
  if (match) return match[1]
  if (mime.startsWith('text/')) return FileText
  return File
}
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">文件</h1>
        <p class="page-subtitle">上传后可在任意设备下载，大文件自动分片传输</p>
      </div>
      <div class="page-actions">
        <button class="btn btn-primary" :disabled="isUploading" @click="handleFileSelect">
          <LoaderCircle v-if="isUploading" class="spin" />
          <Upload v-else />
          {{ isUploading ? '上传中…' : '上传文件' }}
        </button>
      </div>
      <input
        ref="uploadInput"
        type="file"
        class="sr-only"
        tabindex="-1"
        aria-hidden="true"
        @change="handleFileChange"
      />
    </div>

    <div class="stats">
      <div class="stat">
        <span class="stat-label">文件数</span>
        <span class="stat-value">{{ filesStore.totalFiles }}</span>
      </div>
      <div class="stat">
        <span class="stat-label">占用空间</span>
        <span class="stat-value">{{ formatSize(filesStore.totalSize) }}</span>
      </div>
      <div class="stat">
        <span class="stat-label">配额使用</span>
        <span class="stat-value">{{ userStore.quota.percentage }}<small>%</small></span>
        <span class="stat-hint">共 {{ formatSize(userStore.quota.total) }}</span>
      </div>
    </div>

    <div v-if="uploadProgress" class="upload card" role="status">
      <div class="upload-row">
        <span class="upload-name">
          <LoaderCircle class="spin" />
          {{ uploadProgress.filename }}
        </span>
        <span class="upload-percent">{{ uploadProgress.percentage }}%</span>
      </div>
      <div class="progress">
        <div class="progress-fill" :style="{ width: uploadProgress.percentage + '%' }"></div>
      </div>
      <div class="upload-detail">分片 {{ uploadProgress.current }} / {{ uploadProgress.total }}</div>
    </div>

    <LoadingSkeleton v-if="filesStore.isLoading" variant="rows" :count="4" />

    <div v-else-if="filesStore.loadError" class="empty" role="alert">
      <span class="empty-icon"><TriangleAlert :size="20" /></span>
      <p class="empty-title">加载失败</p>
      <p class="empty-text">{{ filesStore.loadError }}</p>
      <button class="btn btn-secondary" @click="loadFiles">
        <RotateCw />
        重试
      </button>
    </div>

    <div v-else-if="filesStore.files.length === 0" class="empty">
      <span class="empty-icon"><FolderOpen :size="20" /></span>
      <p class="empty-title">还没有文件</p>
      <p class="empty-text">上传的文件会出现在这里，可在任意设备下载</p>
      <button class="btn btn-secondary" :disabled="isUploading" @click="handleFileSelect">
        <Upload />
        上传第一个文件
      </button>
    </div>

    <ul v-else class="file-list card">
      <li v-for="file in filesStore.sortedFiles" :key="file.id" class="file-row">
        <span class="file-icon"><component :is="fileIcon(file)" :size="18" /></span>
        <span class="file-main">
          <span class="file-name" :title="file.original_name">{{ file.original_name }}</span>
          <span class="file-sub">{{ formatSize(file.size) }} · {{ formatDateTime(file.created_at) }}</span>
          <span v-if="filesStore.downloads[file.id]" class="file-downloading" role="status">{{ downloadText(file) }}</span>
        </span>
        <span class="file-size">{{ formatSize(file.size) }}</span>
        <span class="file-date">{{ formatDateTime(file.created_at) }}</span>
        <span class="file-actions">
          <AccessCodeButton
            :code="file.access_code"
            :expires-at="file.access_expires_at"
            @click="openCode(file)"
          />
          <button
            class="btn-icon"
            :title="filesStore.downloads[file.id] ? downloadText(file) : '下载'"
            :aria-label="filesStore.downloads[file.id] ? downloadText(file) : '下载'"
            :disabled="!!filesStore.downloads[file.id]"
            @click="handleDownload(file)"
          >
            <LoaderCircle v-if="filesStore.downloads[file.id]" class="spin" />
            <Download v-else />
          </button>
          <button class="btn-icon danger" title="删除" aria-label="删除" @click="handleDelete(file)">
            <Trash2 />
          </button>
        </span>
      </li>
    </ul>

    <AccessCodeDialog
      v-if="codeTarget"
      :target="codeTarget"
      @close="codeTarget = null"
      @saved="onCodeSaved"
    />
  </div>
</template>

<style scoped>
.stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-bottom: var(--space-6);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background-color: var(--color-glass);
  background-image: var(--glass-sheen);
  box-shadow: var(--glass-shadow), var(--shadow-xs);
}

.stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-4) var(--space-5);
}

.stat + .stat {
  border-left: 1px solid var(--color-border);
}

.stat-label {
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--color-text-tertiary);
}

.stat-value {
  font-size: var(--text-xl);
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--color-text);
  font-variant-numeric: tabular-nums;
}

.stat-value small {
  margin-left: 1px;
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--color-text-secondary);
}

.stat-hint {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}

.upload {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-bottom: var(--space-6);
  padding: var(--space-4) var(--space-5);
}

.upload-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  font-size: var(--text-sm);
}

.upload-name {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
  font-weight: 500;
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.upload-name svg {
  flex-shrink: 0;
  color: var(--color-accent);
}

.upload-percent {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.upload-detail {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}

.file-list {
  list-style: none;
  overflow: hidden;
}

.file-row {
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr) 100px 150px auto;
  align-items: center;
  gap: var(--space-3);
  min-height: 56px;
  padding: var(--space-2) var(--space-3) var(--space-2) var(--space-4);
  border-bottom: 1px solid var(--color-border);
  transition: background-color var(--duration) var(--ease);
}

.file-row:last-child {
  border-bottom: none;
}

.file-row:hover {
  background: var(--color-bg-subtle);
}

.file-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  background: var(--color-bg-muted);
  color: var(--color-text-secondary);
}

.file-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.file-name {
  font-size: var(--text-base);
  font-weight: 500;
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-downloading {
  font-size: var(--text-xs);
  color: var(--color-accent);
  font-variant-numeric: tabular-nums;
}

/* 窄屏时大小和时间挪到文件名下方 */
.file-sub {
  display: none;
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}

.file-size,
.file-date {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.file-size {
  text-align: right;
}

.file-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 2px;
}

@media (max-width: 768px) {
  .stats {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .stat {
    padding: var(--space-3);
  }

  .stat-value {
    font-size: var(--text-lg);
  }

  .stat-hint {
    display: none;
  }

  .file-row {
    grid-template-columns: 36px minmax(0, 1fr) auto;
    padding-left: var(--space-3);
  }

  .file-size,
  .file-date {
    display: none;
  }

  .file-sub {
    display: block;
  }
}
</style>
