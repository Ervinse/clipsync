<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { useClipboardStore } from '../stores'
import { formatRelative } from '../utils/format'

const clipboardStore = useClipboardStore()

const textContent = ref('')
// 编辑框最近一次与服务端一致时的内容；textContent 与它不同即表示有未保存的本地编辑
const syncedText = ref('')
const isSaving = ref(false)
const showHistory = ref(false)
const saveSuccess = ref(false)

// 其他终端更新后 store.currentText 变化：本地没有未保存编辑时才同步到编辑框，避免覆盖正在输入的内容
watch(() => clipboardStore.currentText, (value) => {
  if (textContent.value === syncedText.value) {
    textContent.value = value
  }
  syncedText.value = value
})

onMounted(async () => {
  // 先注册监听再拉数据，拉取期间的推送也不会漏掉
  clipboardStore.setupWebSocket()
  try {
    await clipboardStore.fetchCurrent()
    textContent.value = clipboardStore.currentText
    syncedText.value = clipboardStore.currentText
  } catch (error) {
    alert('获取剪贴板失败：' + error.message)
  }
})

onUnmounted(() => {
  clipboardStore.cleanupWebSocket()
})

const handleSave = async () => {
  try {
    isSaving.value = true
    await clipboardStore.updateText(textContent.value)
    syncedText.value = textContent.value

    saveSuccess.value = true
    setTimeout(() => {
      saveSuccess.value = false
    }, 2000)
  } catch (error) {
    alert('保存失败：' + error.message)
  } finally {
    isSaving.value = false
  }
}

const toggleHistory = async () => {
  showHistory.value = !showHistory.value
  // 每次打开都重新拉取，保证看到其他终端产生的历史
  if (showHistory.value) {
    try {
      await clipboardStore.fetchHistory()
    } catch (error) {
      alert('获取历史失败：' + error.message)
    }
  }
}

// 仅把历史内容填入编辑框，不保存
const loadHistoryItem = (content) => {
  textContent.value = content
  showHistory.value = false
}

// 恢复为当前文本：直接保存并同步到其他终端
const handleRestore = async (item) => {
  if (!confirm('将这条历史恢复为当前文本？当前文本会归档到历史。')) return
  try {
    const restored = await clipboardStore.restoreHistory(item.id)
    textContent.value = restored
    syncedText.value = restored
  } catch (error) {
    alert('恢复失败：' + error.message)
  }
}

const handleDeleteHistory = async (item) => {
  if (!confirm('确定删除这条历史记录吗？')) return
  try {
    await clipboardStore.deleteHistory(item.id)
  } catch (error) {
    alert('删除失败：' + error.message)
  }
}

// 后端时间为 naive UTC，formatRelative 内部按 UTC 解析
const formatDate = formatRelative
</script>

<template>
  <div class="clipboard-page">
    <div class="page-header">
      <div>
        <h2>剪贴板同步</h2>
        <p>跨设备实时同步文本内容</p>
      </div>
      <div class="header-actions">
        <button class="btn-secondary" @click="toggleHistory">
          {{ showHistory ? '隐藏历史' : '查看历史' }}
        </button>
        <button
          class="btn-primary"
          @click="handleSave"
          :disabled="isSaving"
        >
          {{ isSaving ? '保存中...' : '保存' }}
        </button>
      </div>
    </div>

    <div v-if="saveSuccess" class="save-toast">
      ✓ 保存成功，已同步到所有设备
    </div>

    <div class="clipboard-container">
      <div class="editor-panel">
        <textarea
          v-model="textContent"
          class="text-editor"
          placeholder="在此输入或粘贴文本..."
          :disabled="clipboardStore.isLoading"
        ></textarea>
        <div class="editor-footer">
          <span class="char-count">{{ textContent.length }} 字符</span>
        </div>
      </div>

      <div v-if="showHistory" class="history-panel">
        <h3>历史记录</h3>
        <div v-if="clipboardStore.history.length === 0" class="empty-state">
          暂无历史记录
        </div>
        <div v-else class="history-list">
          <div
            v-for="item in clipboardStore.history"
            :key="item.id"
            class="history-item"
            @click="loadHistoryItem(item.content)"
          >
            <div class="history-content">
              {{ item.content.substring(0, 100) }}
              <span v-if="item.content.length > 100">...</span>
            </div>
            <div class="history-meta">
              <span class="history-time">{{ formatDate(item.created_at) }}</span>
              <span class="history-length">{{ item.content.length }} 字符</span>
            </div>
            <div class="history-actions">
              <button class="btn-mini" title="恢复为当前文本并同步" @click.stop="handleRestore(item)">
                恢复
              </button>
              <button class="btn-mini btn-mini-danger" title="删除这条历史" @click.stop="handleDeleteHistory(item)">
                删除
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.clipboard-page {
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

.header-actions {
  display: flex;
  gap: 1rem;
}

.btn-primary,
.btn-secondary {
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

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-secondary {
  background: rgba(148, 163, 184, 0.1);
  color: #CBD5E1;
  border: 1px solid #334155;
}

.btn-secondary:hover {
  background: rgba(148, 163, 184, 0.15);
  border-color: #475569;
}

.save-toast {
  position: fixed;
  top: 2rem;
  right: 2rem;
  padding: 1rem 1.5rem;
  background: rgba(34, 211, 238, 0.15);
  border: 1px solid #22D3EE;
  border-radius: 8px;
  color: #22D3EE;
  font-size: 0.95rem;
  animation: slideIn 0.3s ease-out;
  z-index: 1000;
}

@keyframes slideIn {
  from {
    transform: translateX(100%);
    opacity: 0;
  }
  to {
    transform: translateX(0);
    opacity: 1;
  }
}

.clipboard-container {
  display: grid;
  grid-template-columns: 1fr 320px;
  gap: 1.5rem;
}

.clipboard-container:not(:has(.history-panel)) {
  grid-template-columns: 1fr;
}

.editor-panel {
  background: #1E293B;
  border: 1px solid #334155;
  border-radius: 12px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.text-editor {
  flex: 1;
  min-height: 500px;
  padding: 1.5rem;
  background: #0F172A;
  border: none;
  color: #F8FAFC;
  font-size: 0.95rem;
  font-family: 'IBM Plex Sans', monospace;
  line-height: 1.6;
  resize: vertical;
}

.text-editor:focus {
  outline: none;
}

.text-editor::placeholder {
  color: #64748B;
}

.editor-footer {
  padding: 0.75rem 1.5rem;
  background: #1E293B;
  border-top: 1px solid #334155;
  display: flex;
  justify-content: flex-end;
}

.char-count {
  font-size: 0.85rem;
  color: #64748B;
}

.history-panel {
  background: #1E293B;
  border: 1px solid #334155;
  border-radius: 12px;
  padding: 1.5rem;
  max-height: 600px;
  overflow-y: auto;
}

.history-panel h3 {
  font-size: 1.1rem;
  font-weight: 600;
  color: #F8FAFC;
  margin-bottom: 1rem;
}

.empty-state {
  text-align: center;
  padding: 2rem;
  color: #64748B;
  font-size: 0.9rem;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.history-item {
  padding: 1rem;
  background: #0F172A;
  border: 1px solid #334155;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}

.history-item:hover {
  border-color: #38BDF8;
  background: rgba(56, 189, 248, 0.05);
}

.history-content {
  color: #CBD5E1;
  font-size: 0.9rem;
  line-height: 1.5;
  margin-bottom: 0.5rem;
  overflow: hidden;
  text-overflow: ellipsis;
}

.history-meta {
  display: flex;
  justify-content: space-between;
  font-size: 0.8rem;
  color: #64748B;
}

.history-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 0.5rem;
}

.btn-mini {
  padding: 0.25rem 0.75rem;
  background: rgba(56, 189, 248, 0.1);
  border: 1px solid #334155;
  border-radius: 6px;
  color: #38BDF8;
  font-size: 0.8rem;
  cursor: pointer;
}

.btn-mini:hover {
  border-color: #38BDF8;
}

.btn-mini-danger {
  background: rgba(248, 113, 113, 0.1);
  color: #F87171;
}

.btn-mini-danger:hover {
  border-color: #F87171;
}
</style>