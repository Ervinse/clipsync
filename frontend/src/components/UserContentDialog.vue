<script setup>
// 超管只读查看某个用户的文本内容：云剪切板当前文本、剪切板历史、文本栏目。
// 安全红线：只读，不提供修改 / 删除 / 恢复；接口只放行 superadmin，后端每次读取记日志
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { X, LoaderCircle, Info, ChevronLeft } from '@lucide/vue'
import api from '../api'
import { formatDateTime, formatSize } from '../utils/format'
import { dialogState } from '../utils/dialog'
import toast from '../utils/toast'

const props = defineProps({
  // { id, username }
  user: { type: Object, required: true },
})
const emit = defineEmits(['close'])

const SECTIONS = [
  { key: 'clipboard', label: '云剪切板' },
  { key: 'history', label: '剪切板历史' },
  { key: 'texts', label: '文本' },
]
const section = ref('clipboard')

const loading = ref(true)
const error = ref('')
const clipboard = ref(null)
const history = ref([])
const texts = ref([])

// 正在查看全文的一条（历史或文本）：{ title, content, time }
const detail = ref(null)
const detailLoading = ref(false)

const close = () => emit('close')
const onKeydown = (event) => {
  if (event.key !== 'Escape' || dialogState.current) return
  if (detail.value) detail.value = null
  else close()
}

onMounted(async () => {
  window.addEventListener('keydown', onKeydown)
  try {
    const [c, h, t] = await Promise.all([
      api.admin.userContent.clipboard(props.user.id),
      api.admin.userContent.clipboardHistory(props.user.id),
      api.admin.userContent.texts(props.user.id),
    ])
    clipboard.value = c
    history.value = h?.items || []
    texts.value = t?.items || []
  } catch (err) {
    error.value = err.message || '加载失败'
  } finally {
    loading.value = false
  }
})
onUnmounted(() => window.removeEventListener('keydown', onKeydown))

const counts = computed(() => ({
  clipboard: clipboard.value?.version ? 1 : 0,
  history: history.value.length,
  texts: texts.value.length,
}))

const formatTime = (value) => formatDateTime(value, '-', true)
const textTitle = (text) => text.title || '无标题'

// 列表里长内容（超过 64KB）只有开头，点开时再取全文
const openHistory = async (item) => {
  await openDetail(
    { title: '剪切板历史', time: item.created_at },
    item.content,
    () => api.admin.userContent.clipboardHistoryItem(props.user.id, item.id),
  )
}
const openText = async (item) => {
  await openDetail(
    { title: textTitle(item), time: item.updated_at },
    item.content,
    () => api.admin.userContent.text(props.user.id, item.id),
  )
}
const openDetail = async (meta, inlineContent, fetchFull) => {
  if (inlineContent !== null && inlineContent !== undefined) {
    detail.value = { ...meta, content: inlineContent }
    return
  }
  detail.value = { ...meta, content: '' }
  detailLoading.value = true
  try {
    const full = await fetchFull()
    if (detail.value) detail.value.content = full.content
  } catch (err) {
    // 取全文失败：回到列表并提示，不影响已加载的列表
    detail.value = null
    toast.error('加载全文失败：' + (err.message || '未知错误'))
  } finally {
    detailLoading.value = false
  }
}
</script>

<template>
  <div class="modal-overlay" @mousedown.self="close">
    <div
      class="modal content-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="user-content-title"
    >
      <div class="modal-header header-with-close">
        <div>
          <h2 id="user-content-title" class="modal-title">「{{ user.username }}」的文本内容</h2>
          <p class="modal-desc">只读查看，无法修改或删除</p>
        </div>
        <button type="button" class="btn-icon" aria-label="关闭" @click="close">
          <X />
        </button>
      </div>

      <div class="modal-body">
        <div class="alert alert-info">
          <Info />
          <span>这是用户的隐私内容。每次查看都会记入服务器日志。</span>
        </div>

        <div v-if="loading" class="state" role="status">
          <LoaderCircle class="spin" />
          加载中…
        </div>
        <div v-else-if="error" class="alert alert-danger" role="alert">{{ error }}</div>

        <!-- 查看某一条的全文 -->
        <template v-else-if="detail">
          <div class="detail-head">
            <button type="button" class="btn btn-secondary btn-sm" @click="detail = null">
              <ChevronLeft :size="14" />
              返回列表
            </button>
            <span class="detail-meta">{{ detail.title }} · {{ formatTime(detail.time) }}</span>
          </div>
          <div v-if="detailLoading" class="state" role="status">
            <LoaderCircle class="spin" />
            加载全文…
          </div>
          <pre v-else class="content-box">{{ detail.content || '（空）' }}</pre>
        </template>

        <template v-else>
          <div class="sections" role="tablist">
            <button
              v-for="s in SECTIONS"
              :key="s.key"
              type="button"
              class="section-chip"
              :class="{ active: section === s.key }"
              role="tab"
              :aria-selected="section === s.key"
              @click="section = s.key"
            >
              {{ s.label }}
              <span class="chip-count">{{ counts[s.key] }}</span>
            </button>
          </div>

          <!-- 云剪切板当前文本 -->
          <template v-if="section === 'clipboard'">
            <p v-if="!clipboard?.version" class="empty-line">还没有保存过云剪切板内容</p>
            <template v-else>
              <span class="detail-meta">更新于 {{ formatTime(clipboard.updated_at) }}</span>
              <pre class="content-box">{{ clipboard.content || '（空）' }}</pre>
            </template>
          </template>

          <!-- 剪切板历史 -->
          <template v-else-if="section === 'history'">
            <p v-if="history.length === 0" class="empty-line">还没有历史记录</p>
            <ul v-else class="item-list">
              <li v-for="item in history" :key="item.id">
                <button type="button" class="item" @click="openHistory(item)">
                  <span class="item-preview">{{ item.preview || '（空）' }}</span>
                  <span class="item-meta">{{ formatTime(item.created_at) }} · {{ formatSize(item.size) }}</span>
                </button>
              </li>
            </ul>
          </template>

          <!-- 文本栏目 -->
          <template v-else>
            <p v-if="texts.length === 0" class="empty-line">还没有文本</p>
            <ul v-else class="item-list">
              <li v-for="item in texts" :key="item.id">
                <button type="button" class="item" @click="openText(item)">
                  <span class="item-title">{{ textTitle(item) }}</span>
                  <span class="item-preview">{{ item.preview || '（空）' }}</span>
                  <span class="item-meta">更新于 {{ formatTime(item.updated_at) }} · {{ formatSize(item.size) }}</span>
                </button>
              </li>
            </ul>
          </template>
        </template>
      </div>

      <div class="modal-footer">
        <button type="button" class="btn btn-primary" @click="close">关闭</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.content-modal {
  max-width: 720px;
}

.state {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-text-secondary);
}

.sections {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.section-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  background: transparent;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  cursor: pointer;
}

.section-chip.active {
  color: var(--color-text);
  border-color: var(--color-primary);
  background: var(--color-bg-subtle);
}

.chip-count {
  font-variant-numeric: tabular-nums;
  color: var(--color-text-tertiary, var(--color-text-secondary));
}

.empty-line {
  color: var(--color-text-secondary);
}

.content-box {
  max-height: 50vh;
  margin: 0;
  padding: var(--space-3);
  overflow: auto;
  font-family: inherit;
  font-size: var(--text-base);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--color-bg-subtle);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md, 8px);
}

.detail-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
}

.detail-meta,
.item-meta {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.item-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  max-height: 50vh;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  list-style: none;
}

.item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  width: 100%;
  padding: var(--space-3);
  text-align: left;
  color: var(--color-text);
  background: transparent;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md, 8px);
  cursor: pointer;
}

.item:hover {
  background: var(--color-bg-subtle);
}

.item:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

.item-title {
  font-weight: 600;
}

.item-preview {
  display: -webkit-box;
  overflow: hidden;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
