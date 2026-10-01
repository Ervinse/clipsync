<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import api from '../api'
import { copyToClipboard } from '../utils/clipboard'

const route = useRoute()

const loading = ref(true)
const error = ref('')
const data = ref(null)
const targetType = ref('')

onMounted(async () => {
  const code = String(route.params.code || '')

  // 文件码：链接带 ?t=file，直接走公开下载接口（免登录，后端限流 + 有效性校验）
  if (route.query.t === 'file') {
    targetType.value = 'file'
    data.value = { download_url: `/api/access/${encodeURIComponent(code)}/download` }
    loading.value = false
    return
  }

  try {
    loading.value = true
    const result = await api.access.accessText(code)
    targetType.value = 'text'
    data.value = result.content
  } catch (err) {
    error.value = err.message || '访问码无效或已过期'
  } finally {
    loading.value = false
  }
})

// HTTP 部署下 navigator.clipboard 不可用，copyToClipboard 会降级
const copyText = async () => {
  if (await copyToClipboard(data.value)) {
    alert('文本已复制到剪贴板')
  } else {
    alert('复制失败，请手动选中文本复制')
  }
}

const isChecking = ref(false)

// 先探测状态：失效 / 限流时在页面内提示，而不是让浏览器直接显示后端的 JSON。
// 探测成功后立即中止该请求（不读响应体），再交给浏览器原生下载，大文件不进内存。
// 代价：每次下载多计一次公开接口限流（30 次/分钟）。
const downloadFile = async () => {
  const url = data.value?.download_url
  if (!url || isChecking.value) return

  isChecking.value = true
  const controller = new AbortController()
  try {
    const resp = await fetch(url, { signal: controller.signal })
    if (!resp.ok) {
      let message = ''
      try {
        const body = await resp.json()
        message = typeof body?.detail === 'string' ? body.detail : body?.error
      } catch {
        // 响应体不是 JSON，用下面的兜底文案
      }
      if (resp.status === 429) message = '操作过于频繁，请稍后再试'
      error.value = message || '访问码无效或已失效'
      return
    }
    controller.abort()
    window.location.href = url
  } catch (err) {
    if (err?.name !== 'AbortError') error.value = '网络连接失败，请稍后重试'
  } finally {
    isChecking.value = false
  }
}
</script>

<template>
  <div class="public-access-page">
    <div class="access-container">
      <div class="access-header">
        <h1>ClipSync</h1>
        <p>分享内容</p>
      </div>

      <div v-if="loading" class="loading-state">
        <div class="spinner"></div>
        <p>加载中...</p>
      </div>

      <div v-else-if="error" class="error-state">
        <div class="error-icon">⚠️</div>
        <h3>访问失败</h3>
        <p>{{ error }}</p>
      </div>

      <!-- 文本内容 -->
      <div v-else-if="targetType === 'text'" class="content-box">
        <div class="content-header">
          <h3>📋 文本内容</h3>
          <button class="btn-primary" @click="copyText">
            复制文本
          </button>
        </div>
        <div class="text-content">
          {{ data }}
        </div>
      </div>

      <!-- 文件下载 -->
      <div v-else-if="targetType === 'file'" class="content-box">
        <div class="file-info">
          <div class="file-icon">📄</div>
          <div class="file-details">
            <h3>文件访问码</h3>
            <p class="file-size">点击下方按钮下载（链接失效时会提示错误）</p>
          </div>
        </div>
        <button class="btn-primary btn-large" :disabled="isChecking" @click="downloadFile">
          {{ isChecking ? '检查中...' : '⬇️ 下载文件' }}
        </button>
      </div>
    </div>

    <div class="access-footer">
      <p>由 <strong>ClipSync</strong> 提供 | 跨设备剪贴板与文件同步</p>
    </div>
  </div>
</template>

<style scoped>
.public-access-page {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: #0B0E14;
  padding: 2rem;
}

.access-container {
  width: 100%;
  max-width: 680px;
  background: #1E293B;
  border: 1px solid #334155;
  border-radius: 12px;
  padding: 3rem 2.5rem;
}

.access-header {
  text-align: center;
  margin-bottom: 2.5rem;
}

.access-header h1 {
  font-size: 2rem;
  font-weight: 700;
  color: #F8FAFC;
  margin-bottom: 0.5rem;
}

.access-header p {
  font-size: 0.95rem;
  color: #94A3B8;
}

.loading-state {
  text-align: center;
  padding: 3rem 0;
}

.spinner {
  width: 48px;
  height: 48px;
  border: 4px solid #334155;
  border-top-color: #38BDF8;
  border-radius: 50%;
  margin: 0 auto 1.5rem;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.loading-state p {
  color: #94A3B8;
  font-size: 0.95rem;
}

.error-state {
  text-align: center;
  padding: 3rem 0;
}

.error-icon {
  font-size: 4rem;
  margin-bottom: 1.5rem;
}

.error-state h3 {
  font-size: 1.5rem;
  color: #F8FAFC;
  margin-bottom: 0.75rem;
}

.error-state p {
  color: #FCA5A5;
  font-size: 0.95rem;
}

.content-box {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.content-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 1rem;
  border-bottom: 1px solid #334155;
}

.content-header h3 {
  font-size: 1.25rem;
  font-weight: 600;
  color: #F8FAFC;
}

.text-content {
  padding: 1.5rem;
  background: #0F172A;
  border: 1px solid #334155;
  border-radius: 8px;
  color: #CBD5E1;
  font-size: 0.95rem;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 500px;
  overflow-y: auto;
}

.file-info {
  display: flex;
  align-items: center;
  gap: 1.5rem;
  padding: 2rem;
  background: #0F172A;
  border: 1px solid #334155;
  border-radius: 8px;
}

.file-icon {
  font-size: 3.5rem;
}

.file-details h3 {
  font-size: 1.25rem;
  font-weight: 600;
  color: #F8FAFC;
  margin-bottom: 0.5rem;
  word-break: break-word;
}

.file-size {
  font-size: 0.9rem;
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

.btn-primary:hover {
  background: #22D3EE;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(56, 189, 248, 0.3);
}

.btn-primary.btn-large {
  width: 100%;
  padding: 1rem 2rem;
  font-size: 1.1rem;
}

.access-footer {
  margin-top: 2rem;
  text-align: center;
  color: #64748B;
  font-size: 0.85rem;
}

.access-footer strong {
  color: #94A3B8;
}
</style>