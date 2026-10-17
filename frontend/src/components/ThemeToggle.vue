<script setup>
// 主题开关：跟随系统 / 浅色 / 深色三档，选择记在本浏览器（utils/theme.js）
import { Monitor, Sun, Moon } from '@lucide/vue'
import { themeMode, setThemeMode } from '../utils/theme'

const OPTIONS = [
  { value: 'system', label: '跟随系统', icon: Monitor },
  { value: 'light', label: '浅色', icon: Sun },
  { value: 'dark', label: '深色', icon: Moon },
]
</script>

<template>
  <div class="theme-toggle" role="group" aria-label="主题">
    <button
      v-for="option in OPTIONS"
      :key="option.value"
      type="button"
      class="theme-option"
      :class="{ active: themeMode === option.value }"
      :aria-pressed="themeMode === option.value"
      :title="option.label"
      @click="setThemeMode(option.value)"
    >
      <component :is="option.icon" :size="14" />
      <span class="sr-only">{{ option.label }}</span>
    </button>
  </div>
</template>

<style scoped>
.theme-toggle {
  display: inline-flex;
  flex-shrink: 0;
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-subtle);
}

.theme-option {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 24px;
  border-radius: var(--radius-sm);
  color: var(--color-text-tertiary);
  transition: background-color var(--duration) var(--ease), color var(--duration) var(--ease);
}

.theme-option:hover {
  color: var(--color-text);
}

.theme-option.active {
  background: var(--color-bg-emphasis);
  color: var(--color-text);
}
</style>
