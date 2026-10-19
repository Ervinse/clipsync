<script setup>
// 全局提示条：固定在窗口底部居中，叠放最多 3 条。
// 页头右上角放的是操作按钮，提示放在顶部会盖住它们；pointer-events: none 让提示条不挡下面的点击
import { CircleCheck, CircleAlert, Info } from '@lucide/vue'
import { toastState } from '../utils/toast'

const ICONS = { success: CircleCheck, error: CircleAlert, info: Info }
</script>

<template>
  <div class="toast-host" aria-live="polite">
    <TransitionGroup name="toast">
      <div
        v-for="item in toastState.items"
        :key="item.id"
        class="toast"
        :class="item.type"
        :role="item.type === 'error' ? 'alert' : 'status'"
      >
        <component :is="ICONS[item.type]" class="toast-icon" :size="16" />
        <span>{{ item.message }}</span>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toast-host {
  position: fixed;
  left: 0;
  right: 0;
  bottom: var(--space-6);
  z-index: 1100;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  padding: 0 var(--space-4);
  pointer-events: none;
}

.toast {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  max-width: min(480px, 100%);
  padding: 10px 14px;
  border-radius: var(--radius-md);
  background: var(--color-toast-bg);
  color: var(--color-toast-text);
  font-size: var(--text-sm);
  line-height: 1.5;
  box-shadow: inset 0 1px 0 var(--color-toast-highlight), var(--shadow-lg);
  word-break: break-word;
}

/* 支持模糊的浏览器：半透明深色底 + 模糊背后的页面；不支持时保持上面的不透明底，文字不会看不清 */
@supports ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
  .toast {
    background: var(--color-toast-glass);
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
  }
}

.toast-icon {
  flex-shrink: 0;
  margin-top: 2px;
}

.toast.success .toast-icon {
  color: var(--color-toast-success);
}

.toast.error .toast-icon {
  color: var(--color-toast-error);
}

.toast.info .toast-icon {
  color: var(--color-toast-info);
}

.toast-enter-active,
.toast-leave-active {
  transition: opacity 200ms var(--ease), transform 200ms var(--ease);
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
</style>
