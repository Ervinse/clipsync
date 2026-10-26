<script setup>
// 条目上的访问码按钮：已设置时显示访问码，过期时标出；点击打开 AccessCodeDialog
import { computed } from 'vue'
import { KeyRound } from '@lucide/vue'
import { isExpired, clock } from '../utils/accessCode'

const props = defineProps({
  code: { type: String, default: null },
  expiresAt: { type: String, default: null },
  disabled: { type: Boolean, default: false },
})
defineEmits(['click'])

const expired = computed(() => !!props.code && isExpired(props.expiresAt, clock.value))
const title = computed(() => {
  if (!props.code) return '设置访问码'
  return expired.value ? `访问码 ${props.code} 已过期，点击修改` : `访问码 ${props.code}，点击修改或清除`
})
</script>

<template>
  <button
    type="button"
    class="code-btn"
    :class="{ set: !!code, expired }"
    :disabled="disabled"
    :title="title"
    :aria-label="title"
    @click="$emit('click')"
  >
    <KeyRound :size="14" />
    <span v-if="code" class="mono code-text">{{ code }}</span>
    <span v-else>访问码</span>
    <span v-if="expired" class="code-expired">已过期</span>
  </button>
</template>

<style scoped>
.code-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 220px;
  height: 28px;
  padding: 0 10px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-full);
  background: var(--color-bg);
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--color-text-secondary);
  white-space: nowrap;
  transition: border-color var(--duration) var(--ease), color var(--duration) var(--ease);
}

.code-btn:hover:not(:disabled) {
  border-color: var(--color-border-hover);
  color: var(--color-text);
}

.code-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.code-btn.set {
  background: var(--color-bg-muted);
  color: var(--color-text);
}

.code-btn.expired {
  color: var(--color-text-tertiary);
}

.code-text {
  overflow: hidden;
  text-overflow: ellipsis;
}

.code-expired {
  color: var(--color-danger);
}
</style>
