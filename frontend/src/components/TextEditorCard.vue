<script setup>
// 一段文本的编辑卡片：标题（或固定的小标题 heading）+ 编辑框 + 状态栏，右上角操作按钮由 actions 插槽提供。
// 草稿对象来自 utils/textDrafts.js；长文本未载入全文时只显示开头，点按钮后载入（emit('load-full')）
import { computed } from 'vue'
import { LoaderCircle, ChevronsDown } from '@lucide/vue'
import { formatSize, formatRelative } from '../utils/format'

const props = defineProps({
  draft: { type: Object, required: true },
  preview: { type: String, default: '' },
  size: { type: Number, default: 0 },
  updatedAt: { type: String, default: '' },
  // 有 heading 时显示固定小标题，不显示标题输入框（如云剪切板）
  heading: { type: String, default: '' },
  readonly: { type: Boolean, default: false },
  inputId: { type: String, default: undefined },
})
const emit = defineEmits(['save', 'load-full'])

const dirty = computed(() => props.draft.loaded
  && (props.draft.title !== props.draft.syncedTitle || props.draft.content !== props.draft.syncedContent))

const stateText = computed(() => {
  if (props.draft.remoteChanged) return '已在别处更新，保存时会提示你选择'
  if (dirty.value) return '有未保存的修改'
  return '已保存'
})

// Ctrl/⌘ + S 保存
const onKeydown = (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
    event.preventDefault()
    if (!props.readonly) emit('save')
  }
}
</script>

<template>
  <section class="text-card card">
    <div class="text-head">
      <h2 v-if="heading" class="text-heading">{{ heading }}</h2>
      <input
        v-else
        v-model="draft.title"
        class="title-input"
        type="text"
        maxlength="100"
        placeholder="无标题"
        aria-label="标题"
        :readonly="readonly"
        :disabled="!draft.loaded"
        @keydown="onKeydown"
      />
      <span class="text-actions">
        <slot name="actions" :dirty="dirty" />
      </span>
    </div>

    <textarea
      v-if="draft.loaded"
      :id="inputId"
      v-model="draft.content"
      class="text-input"
      placeholder="在此输入或粘贴文本…"
      :aria-label="heading || draft.title || '文本内容'"
      :readonly="readonly"
      @keydown="onKeydown"
    ></textarea>
    <div v-else class="text-preview">
      <p class="preview-body">{{ preview }}…</p>
      <button type="button" class="btn btn-secondary btn-sm" :disabled="draft.loading" @click="emit('load-full')">
        <LoaderCircle v-if="draft.loading" class="spin" />
        <ChevronsDown v-else />
        内容较长（{{ formatSize(size) }}），载入全文后编辑
      </button>
    </div>

    <div class="text-foot">
      <span class="sync-state" :class="{ dirty, remote: draft.remoteChanged }">
        <span class="dot" aria-hidden="true"></span>
        {{ stateText }}
      </span>
      <span class="text-meta">
        {{ draft.loaded ? draft.content.length.toLocaleString() + ' 字符' : formatSize(size) }}
        <template v-if="updatedAt"> · {{ formatRelative(updatedAt) }}</template>
      </span>
    </div>
  </section>
</template>

<style scoped>
.text-card {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.text-card:focus-within {
  border-color: var(--color-border-hover);
  box-shadow: inset 0 1px 0 var(--color-highlight), var(--shadow-sm);
}

.text-head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-height: 48px;
  padding: var(--space-2) var(--space-3) var(--space-2) var(--space-4);
  border-bottom: 1px solid var(--color-border);
}

.text-heading {
  flex: 1;
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--color-text);
}

.title-input {
  flex: 1;
  min-width: 0;
  height: 32px;
  border: none;
  background: transparent;
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--color-text);
}

.title-input:focus {
  outline: none;
}

.title-input::placeholder {
  color: var(--color-text-tertiary);
  font-weight: 500;
}

.text-actions {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--space-1);
}

.text-input {
  display: block;
  width: 100%;
  min-height: 180px;
  padding: var(--space-4);
  border: none;
  background: transparent;
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  line-height: 1.7;
  color: var(--color-text);
  resize: vertical;
}

.text-input:focus {
  outline: none;
}

.text-input::placeholder {
  color: var(--color-text-tertiary);
}

.text-preview {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-4);
}

.preview-body {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  line-height: 1.7;
  color: var(--color-text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
}

.text-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  min-height: 36px;
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

.sync-state.remote .dot {
  background: var(--color-danger);
}

.text-meta {
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

@media (max-width: 640px) {
  .text-head {
    flex-wrap: wrap;
  }

  .text-actions {
    width: 100%;
    justify-content: flex-start;
  }
}
</style>
