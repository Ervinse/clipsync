<script setup>
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { Plus, Save, Trash2, LoaderCircle, StickyNote, TriangleAlert, RotateCw } from '@lucide/vue'
import api from '../api'
import { useTextsStore, useUserStore } from '../stores'
import toast from '../utils/toast'
import { confirmDialog } from '../utils/dialog'
import { createTextDrafts } from '../utils/textDrafts'
import TextEditorCard from '../components/TextEditorCard.vue'
import AccessCodeButton from '../components/AccessCodeButton.vue'
import AccessCodeDialog from '../components/AccessCodeDialog.vue'

const textsStore = useTextsStore()
const userStore = useUserStore()

const PREVIEW_CHARS = 200
const utf8Bytes = (value) => new TextEncoder().encode(value).length

// 保存成功后就地更新列表项（列表刷新时版本号一致，草稿不会被重复更新）
const { drafts, isDirty, hasDirty, sync, loadFull, save, forget } = createTextDrafts({
  fetchFull: (id) => api.texts.get(id),
  saveItem: (id, data) => api.texts.update(id, data),
  onSaved: (id, result) => textsStore.patchText(Number(id), {
    title: result.title,
    version: result.version,
    content: result.content,
    preview: result.content.slice(0, PREVIEW_CHARS),
    size: utf8Bytes(result.content),
    updated_at: result.updated_at,
  }),
})

watch(
  () => textsStore.texts,
  (list) => sync(list.map((t) => ({ key: t.id, ...t }))),
  { deep: true, immediate: true },
)

const rows = computed(() => textsStore.sortedTexts.filter((t) => drafts[t.id]))
const atLimit = computed(() => textsStore.texts.length >= textsStore.maxTexts)

// 布局里的「退出登录」据此先确认
const anyDirty = computed(() => hasDirty())
watch(anyDirty, (dirty) => {
  textsStore.hasUnsavedEdit = dirty
})

onBeforeRouteLeave(async () => {
  if (!anyDirty.value || !userStore.isLoggedIn) return true
  return await confirmDialog({
    title: '放弃未保存的修改？',
    message: '有文本还没有保存，离开后会丢失。',
    confirmText: '放弃并离开',
    cancelText: '继续编辑',
    danger: true,
  })
})

const onBeforeUnload = (event) => {
  if (!anyDirty.value || !userStore.isLoggedIn) return
  event.preventDefault()
  event.returnValue = ''
}

const loadTexts = () => textsStore.fetchTexts().catch(() => {})

onMounted(() => {
  window.addEventListener('beforeunload', onBeforeUnload)
  // 先挂监听再拉列表，避免拉取期间漏掉其他终端的变更
  textsStore.setupWebSocket()
  return loadTexts()
})

onUnmounted(() => {
  window.removeEventListener('beforeunload', onBeforeUnload)
  textsStore.hasUnsavedEdit = false
  textsStore.cleanupWebSocket()
})

const isCreating = ref(false)
const handleCreate = async () => {
  try {
    isCreating.value = true
    const text = await textsStore.createText({ title: '', content: '' })
    await nextTick()
    document.getElementById(`text-${text.id}`)?.focus()
  } catch (error) {
    toast.error('新建失败：' + error.message)
  } finally {
    isCreating.value = false
  }
}

const labelOf = (item) => item.title || (item.preview || '').trim().slice(0, 30) || '无标题文本'

const handleDelete = async (item) => {
  const ok = await confirmDialog({
    title: '删除这段文本？',
    message: `「${labelOf(item)}」将被永久删除${item.access_code ? `，它的访问码 ${item.access_code} 也会一并清除` : ''}。`,
    confirmText: '删除',
    danger: true,
  })
  if (!ok) return
  try {
    await textsStore.deleteText(item.id, () => forget(item.id))
  } catch (error) {
    toast.error('删除失败：' + error.message)
  }
}

const codeTarget = ref(null)
const openCode = (item) => {
  codeTarget.value = {
    targetType: 'text',
    targetId: item.id,
    label: labelOf(item),
    code: item.access_code,
    expiresAt: item.access_expires_at,
  }
}
const onCodeSaved = (result) => {
  textsStore.patchText(result.target_id, {
    access_code: result.access_code,
    access_expires_at: result.access_expires_at,
  })
}
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h1 class="page-title">文本</h1>
        <p class="page-subtitle">存放多段独立的文本，每段可以单独设置访问码，在其他设备免登录查看和修改</p>
      </div>
      <div class="page-actions">
        <button class="btn btn-primary" :disabled="isCreating || atLimit" @click="handleCreate">
          <LoaderCircle v-if="isCreating" class="spin" />
          <Plus v-else />
          新建文本
        </button>
      </div>
    </div>

    <p v-if="atLimit" class="limit-hint">已达到 {{ textsStore.maxTexts }} 段的上限，删除不需要的文本后才能新建。</p>

    <div v-if="textsStore.isLoading" class="loading">
      <LoaderCircle class="spin" />
      加载中…
    </div>

    <div v-else-if="textsStore.loadError" class="empty" role="alert">
      <span class="empty-icon"><TriangleAlert :size="20" /></span>
      <p class="empty-title">文本加载失败</p>
      <p class="empty-text">{{ textsStore.loadError }}</p>
      <button class="btn btn-secondary" @click="loadTexts">
        <RotateCw />
        重试
      </button>
    </div>

    <div v-else-if="rows.length === 0" class="empty">
      <span class="empty-icon"><StickyNote :size="20" /></span>
      <p class="empty-title">还没有文本</p>
      <p class="empty-text">新建一段文本，可以给它单独设置访问码</p>
      <button class="btn btn-secondary" :disabled="isCreating" @click="handleCreate">
        <Plus />
        新建第一段文本
      </button>
    </div>

    <div v-else class="text-list">
      <TextEditorCard
        v-for="item in rows"
        :key="item.id"
        :draft="drafts[item.id]"
        :preview="item.preview"
        :size="item.size"
        :updated-at="item.updated_at"
        :input-id="`text-${item.id}`"
        @save="save(item.id)"
        @load-full="loadFull(item.id)"
      >
        <template #actions>
          <AccessCodeButton
            :code="item.access_code"
            :expires-at="item.access_expires_at"
            @click="openCode(item)"
          />
          <button
            class="btn btn-secondary btn-sm"
            :disabled="!drafts[item.id].loaded || drafts[item.id].saving || !isDirty(drafts[item.id])"
            @click="save(item.id)"
          >
            <LoaderCircle v-if="drafts[item.id].saving" class="spin" />
            <Save v-else :size="14" />
            保存
          </button>
          <button class="btn-icon danger" title="删除" aria-label="删除" @click="handleDelete(item)">
            <Trash2 />
          </button>
        </template>
      </TextEditorCard>
    </div>

    <AccessCodeDialog
      v-if="codeTarget"
      :target="codeTarget"
      @close="codeTarget = null"
      @saved="onCodeSaved"
    />
  </div>
</template>

<style scoped>
.text-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.limit-hint {
  margin-bottom: var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}
</style>
