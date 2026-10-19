<script setup>
// 列表加载中的骨架屏：按列表的样子画几块灰色占位，上面有一道光扫过（.skeleton 在 style.css）。
// variant：rows 是一张卡片里的多行（文件列表），cards 是多张卡片（文本、访问码分组、快速访问）。
// 屏幕阅读器只读到「加载中…」，占位块本身对它隐藏
defineProps({
  variant: { type: String, default: 'rows' },
  count: { type: Number, default: 3 },
})

// 各行占位条的宽度错开，看起来像长短不一的真实内容
const WIDTHS = ['46%', '62%', '38%', '54%']
</script>

<template>
  <div class="loading-skeleton" role="status">
    <span class="sr-only">加载中…</span>

    <div v-if="variant === 'rows'" class="sk-list card" aria-hidden="true">
      <div v-for="n in count" :key="n" class="sk-row">
        <span class="skeleton sk-icon"></span>
        <span class="sk-lines">
          <span class="skeleton sk-line" :style="{ width: WIDTHS[(n - 1) % WIDTHS.length] }"></span>
          <span class="skeleton sk-line sk-line-sm"></span>
        </span>
      </div>
    </div>

    <div v-else class="sk-cards" aria-hidden="true">
      <div v-for="n in count" :key="n" class="sk-card card">
        <div class="sk-card-head">
          <span class="skeleton sk-line" :style="{ width: WIDTHS[(n - 1) % WIDTHS.length] }"></span>
        </div>
        <div class="sk-card-body">
          <span class="skeleton sk-line" style="width: 92%"></span>
          <span class="skeleton sk-line" style="width: 78%"></span>
          <span class="skeleton sk-line" style="width: 56%"></span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sk-list {
  overflow: hidden;
}

/* 行高、内边距与文件列表的一行相同，加载完成时页面不跳动 */
.sk-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-height: 56px;
  padding: var(--space-2) var(--space-3) var(--space-2) var(--space-4);
  border-bottom: 1px solid var(--color-border);
}

.sk-row:last-child {
  border-bottom: none;
}

.sk-icon {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
}

.sk-lines {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.sk-line {
  height: 10px;
}

.sk-line-sm {
  width: 22%;
  height: 8px;
}

.sk-cards {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.sk-card {
  overflow: hidden;
}

.sk-card-head {
  display: flex;
  align-items: center;
  min-height: 48px;
  padding: 0 var(--space-4);
  border-bottom: 1px solid var(--color-border);
}

.sk-card-head .sk-line {
  max-width: 220px;
}

.sk-card-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  min-height: 120px;
}
</style>
