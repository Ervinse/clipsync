<script setup>
// 品牌标识：图形（两张错开的卡片，表示两台设备之间同步）+ 可选的文字
defineProps({
  size: { type: Number, default: 24 },
  withText: { type: Boolean, default: true },
})
</script>

<template>
  <span class="brand">
    <svg
      class="brand-mark"
      :width="size"
      :height="size"
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
    >
      <rect width="32" height="32" rx="8" fill="currentColor" />
      <rect class="brand-card" x="8" y="7" width="12" height="14" rx="2.5" stroke-width="2" />
      <rect class="brand-card" x="12" y="11" width="12" height="14" rx="2.5" fill="currentColor" stroke-width="2" />
    </svg>
    <span v-if="withText" class="brand-text">ClipSync</span>
  </span>
</template>

<style scoped>
.brand {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  color: var(--color-text);
}

.brand-mark {
  flex-shrink: 0;
  display: block;
}

/* 卡片描边用页面底色：浅色主题下是白线，深色主题下是深色线 */
.brand-card {
  stroke: var(--color-bg);
}

.brand-text {
  font-size: var(--text-md);
  font-weight: 600;
  letter-spacing: -0.01em;
}
</style>
