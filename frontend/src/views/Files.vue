<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useFilesStore, useUserStore } from '../stores'

const filesStore = useFilesStore()
const userStore = useUserStore()

const uploadInput = ref(null)
const isUploading = ref(false)

onMounted(async () => {
  // 先挂监听再拉列表，避免拉取期间漏掉其他终端的变更
  filesStore.setupWebSocket()
  await filesStore.fetchFiles()
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
    isUploading.value = true
    await filesStore.uploadFile(file)
    alert('文件上传成功')
  } catch (error) {
    alert('上传失败：' + (error.response?.data?.detail || error.message))
  } finally {
    isUploading.value = false
    if (uploadInput.value) {
      uploadInput.value.value = ''
    }
  }
}

const handleDownload = async (file) => {
  try {
    await filesStore.downloadFile(file)
  } catch (error) {
    alert('下载失败：' + (error.message || '未知错误'))
  }
}

const handleDelete = async (file) => {
  if (!confirm(`确定删除文件 "${file.original_name}" 吗？`)) return

  try {
    await filesStore.deleteFile(file.id)
  } catch (error) {
    alert('删除失败：' + (error.response?.data?.detail || error.message))
  }
}

const formatSize = (bytes) => {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i]
}

const formatDate = (dateString) => {
  const date = new Date(dateString)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
</script>

<template>
  <div class="files-page">
    <div class="page-header">
      <div>
        <h2>文件管理</h2>
        <p>上传和管理文件，支持大文件分片传输</p>
      </div>
      <button
        class="btn-primary"
        @click="handleFileSelect"
        :disabled="isUploading"
      >
        {{ isUploading ? '上传中...' : '+ 上传文件' }}
      </button>
      <input
        ref="uploadInput"
        type="file"
        style="display: none"
        @change="handleFileChange"
      />
    </div>

    <div v-if="uploadProgress" class="upload-progress">
      <div class="progress-info">
        <span class="progress-filename">{{ uploadProgress.filename }}</span>
        <span class="progress-percent">{{ uploadProgress.percentage }}%</span>
      </div>
      <div class="progress-bar">
        <div
          class="progress-fill"
          :style="{ width: uploadProgress.percentage + '%' }"
        ></div>
      </div>
      <div class="progress-detail">
        分片 {{ uploadProgress.current }} / {{ uploadProgress.total }}
      </div>
    </div>

    <div class="stats-bar">
      <div class="stat-item">
        <span class="stat-label">文件总数</span>
        <span class="stat-value">{{ filesStore.totalFiles }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">总大小</span>
        <span class="stat-value">{{ formatSize(filesStore.totalSize) }}</span>
      </div>
      <div class="stat-item">
        <span class="stat-label">配额使用</span>
        <span class="stat-value">{{ userStore.quota.percentage }}%</span>
      </div>
    </div>

    <div v-if="filesStore.isLoading" class="loading-state">
      加载中...
    </div>

    <div v-else-if="filesStore.files.length === 0" class="empty-state">
      <div class="empty-icon">📁</div>
      <p>还没有上传文件</p>
      <button class="btn-secondary" @click="handleFileSelect">
        上传第一个文件
      </button>
    </div>

    <div v-else class="files-grid">
      <div
        v-for="file in filesStore.sortedFiles"
        :key="file.id"
        class="file-card"
      >
        <div class="file-icon">📄</div>
        <div class="file-info">
          <div class="file-name">{{ file.original_name }}</div>
          <div class="file-meta">
            <span>{{ formatSize(file.size) }}</span>
            <span>•</span>
            <span>{{ formatDate(file.created_at) }}</span>
          </div>
        </div>
        <div class="file-actions">
          <button
            class="btn-icon"
            title="下载"
            @click="handleDownload(file)"
          >
            ⬇️
          </button>
          <button
            class="btn-icon btn-danger"
            title="删除"
            @click="handleDelete(file)"
          >
            🗑️
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.files-page {
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

.btn-primary {
  padding: 0.75rem 1.5rem;
  background: #38BDF8;
  color: #0F172A;
  border: none;
  border-radius: 8px;
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-primary:hover:not(:disabled) {
  background: #22D3EE;
  transform: translateY(-1px);
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-secondary {
  padding: 0.75rem 1.5rem;
  background: rgba(148, 163, 184, 0.1);
  color: #CBD5E1;
  border: 1px solid #334155;
  border-radius: 8px;
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-secondary:hover {
  background: rgba(148, 163, 184, 0.15);
  border-color: #475569;
}

.upload-progress {
  padding: 1.5rem;
  background: #1E293B;
  border: 1px solid #334155;
  border-radius: 12px;
  margin-bottom: 2rem;
}

.progress-info {
  display: flex;
  justify-content: space-between;
  margin-bottom: 0.75rem;
}

.progress-filename {
  font-size: 0.95rem;
  color: #CBD5E1;
  font-weight: 500;
}

.progress-percent {
  font-size: 0.95rem;
  color: #38BDF8;
  font-weight: 600;
}

.progress-bar {
  height: 8px;
  background: #0F172A;
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 0.5rem;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #38BDF8, #22D3EE);
  transition: width 0.3s;
}

.progress-detail {
  font-size: 0.85rem;
  color: #64748B;
}

.stats-bar {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1rem;
  margin-bottom: 2rem;
}

.stat-item {
  padding: 1.25rem;
  background: #1E293B;
  border: 1px solid #334155;
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.stat-label {
  font-size: 0.85rem;
  color: #94A3B8;
}

.stat-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #F8FAFC;
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

.files-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 1rem;
}

.file-card {
  padding: 1.25rem;
  background: #1E293B;
  border: 1px solid #334155;
  border-radius: 12px;
  display: flex;
  align-items: center;
  gap: 1rem;
  transition: all 0.2s;
}

.file-card:hover {
  border-color: #38BDF8;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(56, 189, 248, 0.15);
}

.file-icon {
  font-size: 2rem;
  flex-shrink: 0;
}

.file-info {
  flex: 1;
  min-width: 0;
}

.file-name {
  font-size: 0.95rem;
  font-weight: 500;
  color: #F8FAFC;
  margin-bottom: 0.25rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.file-meta {
  font-size: 0.8rem;
  color: #64748B;
  display: flex;
  gap: 0.5rem;
}

.file-actions {
  display: flex;
  gap: 0.5rem;
}

.btn-icon {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(148, 163, 184, 0.1);
  border: 1px solid #334155;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
  font-size: 1.1rem;
}

.btn-icon:hover {
  background: rgba(56, 189, 248, 0.15);
  border-color: #38BDF8;
}

.btn-icon.btn-danger:hover {
  background: rgba(239, 68, 68, 0.15);
  border-color: rgba(239, 68, 68, 0.5);
}
</style>