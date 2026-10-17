<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { History, Save, LoaderCircle, RotateCcw, Trash2, X, Inbox } from '@lucide/vue'
import { useClipboardStore, useUserStore } from '../stores'
import { formatRelative, formatSize } from '../utils/format'
import toast from '../utils/toast'
import { confirmDialog } from '../utils/dialog'
import { askConflict } from '../utils/conflict'
import AccessCodeButton from '../components/AccessCodeButton.vue'
import AccessCodeDialog from '../components/AccessCodeDialog.vue'

const clipboardStore = useClipboardStore()
const userStore = useUserStore()

const textContent = ref('')
// 编辑框最近一次与服务端一致时的内容；textContent 与它不同即表示有未保存的本地编辑
const syncedText = ref('')
// 编辑框内容所基于的服务端版本：保存时带上，别处改过会返回 409（冲突）
const baseVersion = ref(0)
const isSaving = ref(false)
const showCodeDialog = ref(false)
const showHistory = ref(false)

const isDirty = computed(() => textContent.value !== syncedText.value)

// 其他终端更新后 store.currentText 变化：本地没有未保存编辑时才同步到编辑框，避免覆盖正在输入的内容
// 有未保存编辑时只提示「已在别处更新」，保存时由冲突检测让用户选择。
// 自己保存时 store 也会更新（此时 isSaving 仍为 true），不算别处的更新
watch(() => clipboardStore.currentText, (value) => {
  if (textContent.value === syncedText.value) {
    textContent.value = value
    baseVersion.value = clipboardStore.version
  } else if (!isSaving.value && value !== syncedText.value && value !== textContent.value) {
    toast.info('这段内容已在别处更新，保存时会提示你选择')
  }
  syncedText.value = value
})

// 告诉 store 历史面板是否打开：打开时收到推送才重拉历史
watch(showHistory, (visible) => {
  clipboardStore.historyVisible = visible
})

watch(isDirty, (dirty) => {
  clipboardStore.hasUnsavedEdit = dirty
})

// 有未保存的修改时离开：编辑框内容只存在本页，切到别的页面或刷新就丢了，先让用户确认。
// 已经登出（退出登录、登录过期）时不再拦：退出登录的确认在登出之前已经做过
onBeforeRouteLeave(async () => {
  if (!isDirty.value || !userStore.isLoggedIn) return true
  return await confirmDialog({
    title: '放弃未保存的修改？',
    message: '编辑框里的内容还没有保存，离开后会丢失。',
    confirmText: '放弃并离开',
    cancelText: '继续编辑',
    danger: true,
  })
})

// 刷新、关闭标签页时由浏览器自带的确认框拦一下（文案由浏览器决定）
const onBeforeUnload = (event) => {
  if (!isDirty.value || !userStore.isLoggedIn) return
  event.preventDefault()
  event.returnValue = ''
}

onMounted(async () => {
  window.addEventListener('beforeunload', onBeforeUnload)
  // 先注册监听再拉数据，拉取期间的推送也不会漏掉
  clipboardStore.setupWebSocket()
  try {
    await clipboardStore.fetchCurrent()
    textContent.value = clipboardStore.currentText
    syncedText.value = clipboardStore.currentText
    baseVersion.value = clipboardStore.version
  } catch (error) {
    toast.error('获取剪贴板失败：' + error.message)
  }
})

onUnmounted(() => {
  window.removeEventListener('beforeunload', onBeforeUnload)
  clipboardStore.historyVisible = false
  clipboardStore.hasUnsavedEdit = false
  clipboardStore.cleanupWebSocket()
})

// overwrite：冲突后用户选了「仍然覆盖」，不带版本号直接保存
const handleSave = async ({ overwrite = false } = {}) => {
  try {
    isSaving.value = true
    // 保存的是点击时的内容：请求期间继续输入的字不在其中，不能被标成「已同步」，
    // 否则之后其他终端的更新会把这几个字无提示地覆盖掉
    const saved = textContent.value
    const data = await clipboardStore.updateText(saved, overwrite ? null : baseVersion.value)
    syncedText.value = saved
    baseVersion.value = data.version
    toast.success('已保存，并同步到所有设备')
  } catch (error) {
    if (error?.status === 409) {
      isSaving.value = false
      await resolveConflict()
      return
    }
    toast.error('保存失败：' + error.message)
  } finally {
    isSaving.value = false
  }
}

const resolveConflict = async () => {
  const choice = await askConflict()
  if (choice === 'overwrite') {
    await handleSave({ overwrite: true })
  } else if (choice === 'load') {
    try {
      await clipboardStore.fetchCurrent()
      textContent.value = clipboardStore.currentText
      syncedText.value = clipboardStore.currentText
      baseVersion.value = clipboardStore.version
      toast.info('已载入最新内容')
    } catch (error) {
      toast.error('载入失败：' + error.message)
    }
  }
}

const codeTarget = computed(() => ({
  targetType: 'clipboard',
  targetId: null,
  label: '',
  code: clipboardStore.accessCode,
  expiresAt: clipboardStore.accessExpiresAt,
}))

const onCodeSaved = (result) => {
  clipboardStore.accessCode = result.access_code
  clipboardStore.accessExpiresAt = result.access_expires_at
}

// Ctrl/⌘ + S 保存
const onEditorKeydown = (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
    event.preventDefault()
    if (!isSaving.value) handleSave()
  }
}

const toggleHistory = async () => {
  showHistory.value = !showHistory.value
  // 每次打开都重新拉取，保证看到其他终端产生的历史
  if (showHistory.value) {
    try {
      await clipboardStore.fetchHistory()
    } catch (error) {
      toast.error('获取历史失败：' + error.message)
    }
  }
}

// 仅把历史内容填入编辑框，不保存；长内容列表里只有开头，先取全文
const loadHistoryItem = async (item) => {
  let content
  try {
    content = await clipboardStore.fetchHistoryContent(item)
  } catch (error) {
    toast.error('载入历史失败：' + error.message)
    return
  }
  textContent.value = content
  showHistory.value = false
  toast.info('已填入编辑框，点击「保存」后才会同步')
}

// 历史条目的摘要：带全文的取前 140 个字符，只有开头的用 preview
const historyText = (item) => item.content ?? item.preview
const historyTruncated = (item) => item.content === null || item.content.length > 140
const historySize = (item) =>
  item.content === null ? formatSize(item.size) : item.content.length.toLocaleString() + ' 字符'

// 恢复为当前文本：直接保存并同步到其他终端
const handleRestore = async (item) => {
  const ok = await confirmDialog({
    title: '恢复这条历史？',
    message: '它会成为当前文本并同步到所有设备，现在的文本会归档到历史。',
    confirmText: '恢复',
  })
  if (!ok) return
  try {
    const restored = await clipboardStore.restoreHistory(item.id)
    textContent.value = restored
    syncedText.value = restored
    baseVersion.value = clipboardStore.version
    toast.success('已恢复为当前文本')
  } catch (error) {
    toast.error('恢复失败：' + error.message)
  }
}

const handleDeleteHistory = async (item) => {
  const ok = await confirmDialog({
    title: '删除这条历史记录？',
    message: '删除后无法找回。',
    confirmText: '删除',
    danger: true,
  })
  if (!ok) return
  try {
    await clipboardStore.deleteHistory(item.id)
  } catch (error) {
    toast.error('删除失败：' + error.message)
  }
}

// 后端时间为 naive UTC，formatRelative 内部按 UTC 解析
const formatDate = formatRelative
</script>

<template>
  <div class="page clipboard-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">云剪切板</h1>
        <p class="page-subtitle">在这里保存的文本会实时同步到你登录的所有设备</p>
      </div>
      <div class="page-actions">
        <AccessCodeButton
          :code="clipboardStore.accessCode"
          :expires-at="clipboardStore.accessExpiresAt"
          @click="showCodeDialog = true"
        />
        <button class="btn btn-secondary" :class="{ pressed: showHistory }" @click="toggleHistory">
          <History />
          {{ showHistory ? '收起历史' : '历史记录' }}
        </button>
        <button class="btn btn-primary" :disabled="isSaving" @click="handleSave()">
          <LoaderCircle v-if="isSaving" class="spin" />
          <Save v-else />
          {{ isSaving ? '保存中…' : '保存' }}
        </button>
      </div>
    </div>

    <div class="workspace" :class="{ 'with-history': showHistory }">
      <section class="editor card">
        <textarea
          v-model="textContent"
          class="editor-input"
          placeholder="在此输入或粘贴文本…"
          aria-label="云剪切板文本"
          :disabled="clipboardStore.isLoading"
          @keydown="onEditorKeydown"
        ></textarea>
        <div class="editor-footer">
          <span class="sync-state" :class="{ dirty: isDirty }">
            <span class="dot" aria-hidden="true"></span>
            {{ isDirty ? '有未保存的修改' : '已同步' }}
          </span>
          <span class="editor-meta">
            {{ textContent.length.toLocaleString() }} 字符
            <span class="kbd-hint">· Ctrl + S 保存</span>
          </span>
        </div>
      </section>

      <aside v-if="showHistory" class="history card" aria-label="历史记录">
        <div class="history-header">
          <h2 class="section-title">历史记录</h2>
          <button class="btn-icon" aria-label="收起历史" @click="showHistory = false">
            <X />
          </button>
        </div>

        <div v-if="clipboardStore.history.length === 0" class="history-empty">
          <Inbox :size="20" />
          <span>暂无历史记录</span>
        </div>

        <ul v-else class="history-list">
          <li
            v-for="item in clipboardStore.history"
            :key="item.id"
            class="history-item"
            tabindex="0"
            title="点击填入编辑框（不保存）"
            @click="loadHistoryItem(item)"
            @keydown.enter="loadHistoryItem(item)"
          >
            <p class="history-content">{{ historyText(item).substring(0, 140) }}<span v-if="historyTruncated(item)">…</span></p>
            <div class="history-meta">
              <span>{{ formatDate(item.created_at) }} · {{ historySize(item) }}</span>
              <span class="history-actions">
                <button class="btn-icon" title="恢复为当前文本并同步" aria-label="恢复" @click.stop="handleRestore(item)">
                  <RotateCcw :size="14" />
                </button>
                <button class="btn-icon danger" title="删除这条历史" aria-label="删除" @click.stop="handleDeleteHistory(item)">
                  <Trash2 :size="14" />
                </button>
              </span>
            </div>
          </li>
        </ul>
      </aside>
    </div>

    <AccessCodeDialog
      v-if="showCodeDialog"
      :target="codeTarget"
      @close="showCodeDialog = false"
      @saved="onCodeSaved"
    />
  </div>
</template>

<style scoped>
.btn-secondary.pressed {
  background: var(--color-bg-muted);
}

/* 整页正好占满窗口高度：编辑框填满页头以下的空间，底部状态栏（已同步 / 字符数）始终在窗口内。
   窗口矮于 min-height 时不再压缩，改为整页滚动；dvh 不含手机浏览器地址栏，旧浏览器回落到 vh */
.clipboard-page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  height: 100dvh;
  min-height: 480px;
  padding-bottom: var(--space-8);
}

.workspace {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  grid-template-rows: minmax(0, 1fr);
  gap: var(--space-4);
}

.workspace.with-history {
  grid-template-columns: minmax(0, 1fr) 320px;
}

.editor {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.editor:focus-within {
  border-color: var(--color-border-hover);
  box-shadow: var(--shadow-sm);
}

.editor-input {
  display: block;
  flex: 1;
  width: 100%;
  min-height: 0;
  padding: var(--space-5) var(--space-6);
  border: none;
  background: transparent;
  font-family: var(--font-mono);
  font-size: var(--text-base);
  line-height: 1.7;
  color: var(--color-text);
  resize: none;
}

.editor-input:focus {
  outline: none;
}

.editor-input::placeholder {
  color: var(--color-text-tertiary);
}

.editor-footer {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  height: 40px;
  padding: 0 var(--space-4);
  border-top: 1px solid var(--color-border);
  background: var(--color-bg-subtle);
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}

.sync-state {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--color-text-secondary);
}

.sync-state .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-success);
}

.sync-state.dirty .dot {
  background: var(--color-warning);
}

.editor-meta {
  font-variant-numeric: tabular-nums;
}

/* 历史面板与编辑框等高，条目多时在面板内滚动 */
.history {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.history-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-3) var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border);
}

.history-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-12) var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
}

.history-list {
  list-style: none;
  overflow-y: auto;
}

.history-item {
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border);
  cursor: pointer;
  transition: background-color var(--duration) var(--ease);
}

.history-item:last-child {
  border-bottom: none;
}

.history-item:hover {
  background: var(--color-bg-subtle);
}

.history-item:focus-visible {
  outline-offset: -2px;
}

.history-content {
  font-size: var(--text-sm);
  line-height: 1.55;
  color: var(--color-text);
  white-space: pre-wrap;
  word-break: break-word;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.history-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 6px;
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}

/* 操作按钮悬停时才明显，平时保持安静；触屏设备没有悬停，始终显示 */
.history-actions {
  display: inline-flex;
  gap: 2px;
  opacity: 0.6;
  transition: opacity var(--duration) var(--ease);
}

.history-item:hover .history-actions,
.history-item:focus-within .history-actions {
  opacity: 1;
}

.history-actions .btn-icon {
  width: 26px;
  height: 26px;
}

@media (hover: none) {
  .history-actions {
    opacity: 1;
  }
}

/* 窄窗口历史面板排到编辑框下方：上下按 3 : 2 分高度 */
@media (max-width: 1024px) {
  .workspace.with-history {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: minmax(0, 3fr) minmax(0, 2fr);
  }
}

/* 手机宽度：顶栏（52px）在页面上方，页面高度扣掉它 */
@media (max-width: 768px) {
  .clipboard-page {
    height: calc(100vh - 52px);
    height: calc(100dvh - 52px);
    min-height: 420px;
    padding-bottom: var(--space-4);
  }

  .editor-input {
    padding: var(--space-4);
  }

  .kbd-hint {
    display: none;
  }
}
</style>
