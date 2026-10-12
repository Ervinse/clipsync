<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { Copy, Download, File, LoaderCircle, TriangleAlert } from '@lucide/vue'
import api from '../api'
import { copyToClipboard } from '../utils/clipboard'
import toast from '../utils/toast'
import BrandMark from '../components/BrandMark.vue'

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
    toast.success('文本已复制')
  } else {
    toast.error('复制失败，请手动选中文本复制')
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
  <div class="public">
    <header class="public-header">
      <BrandMark :size="24" />
      <span class="header-note">分享内容</span>
    </header>

    <main class="public-main">
      <div v-if="loading" class="loading">
        <LoaderCircle class="spin" />
        加载中…
      </div>

      <div v-else-if="error" class="state card" role="alert">
        <span class="state-icon danger"><TriangleAlert :size="20" /></span>
        <h1 class="state-title">无法访问</h1>
        <p class="state-text">{{ error }}</p>
        <p class="state-hint">链接可能已过期或被撤销，请联系分享者重新获取。</p>
      </div>

      <!-- 文本内容 -->
      <section v-else-if="targetType === 'text'" class="text-card card">
        <div class="text-header">
          <div>
            <h1 class="text-title">分享的文本</h1>
            <p class="text-meta">{{ (data || '').length.toLocaleString() }} 字符</p>
          </div>
          <button class="btn btn-primary" @click="copyText">
            <Copy />
            复制全部
          </button>
        </div>
        <pre class="text-body">{{ data }}</pre>
      </section>

      <!-- 文件下载 -->
      <div v-else-if="targetType === 'file'" class="state card">
        <span class="state-icon"><File :size="20" /></span>
        <h1 class="state-title">有人向你分享了一个文件</h1>
        <p class="state-text">点击下方按钮下载；链接失效时会在这里提示。</p>
        <button class="btn btn-primary btn-lg download-btn" :disabled="isChecking" @click="downloadFile">
          <LoaderCircle v-if="isChecking" class="spin" />
          <Download v-else />
          {{ isChecking ? '检查中…' : '下载文件' }}
        </button>
      </div>
    </main>

    <footer class="public-footer">
      由 ClipSync 提供 · 跨设备剪贴板与文件同步
    </footer>
  </div>
</template>

<style scoped>
.public {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  background: var(--color-bg-subtle);
}

.public-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 60px;
  padding: 0 var(--space-6);
  background: var(--color-bg);
  border-bottom: 1px solid var(--color-border);
}

.header-note {
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
}

.public-main {
  flex: 1;
  width: 100%;
  max-width: 760px;
  margin: 0 auto;
  padding: var(--space-12) var(--space-4);
}

.state {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: var(--space-12) var(--space-6);
}

.state-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  margin-bottom: var(--space-4);
  border-radius: var(--radius-md);
  background: var(--color-bg-muted);
  color: var(--color-text-secondary);
}

.state-icon.danger {
  background: var(--color-danger-subtle);
  color: var(--color-danger);
}

.state-title {
  font-size: var(--text-xl);
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--color-text);
}

.state-text {
  margin-top: var(--space-2);
  font-size: var(--text-base);
  color: var(--color-text-secondary);
  word-break: break-word;
}

.state-hint {
  margin-top: var(--space-1);
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
}

.download-btn {
  margin-top: var(--space-6);
  min-width: 200px;
}

.text-card {
  overflow: hidden;
}

.text-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--color-border);
}

.text-title {
  font-size: var(--text-md);
  font-weight: 600;
  color: var(--color-text);
}

.text-meta {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}

.text-body {
  max-height: 60vh;
  overflow: auto;
  padding: var(--space-5);
  font-family: var(--font-mono);
  font-size: var(--text-base);
  line-height: 1.7;
  color: var(--color-text);
  white-space: pre-wrap;
  word-break: break-word;
}

.public-footer {
  padding: var(--space-6) var(--space-4);
  text-align: center;
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}

@media (max-width: 768px) {
  .public-header {
    padding: 0 var(--space-4);
  }

  .public-main {
    padding-top: var(--space-6);
  }

  .text-header {
    flex-wrap: wrap;
  }
}
</style>
