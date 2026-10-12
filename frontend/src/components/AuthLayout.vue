<script setup>
// 登录 / 注册页共用的布局：左侧品牌介绍（窄屏隐藏），右侧表单（默认插槽）
import { Clipboard, FolderUp, Link } from '@lucide/vue'
import BrandMark from './BrandMark.vue'

defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
})

const FEATURES = [
  { icon: Clipboard, title: '文本实时同步', text: '在一台设备上保存，其他设备立刻看到' },
  { icon: FolderUp, title: '大文件分片上传', text: '上传进度实时可见，存储配额一目了然' },
  { icon: Link, title: '免登录分享', text: '生成访问链接，可设有效期，随时撤销' },
]
</script>

<template>
  <div class="auth">
    <aside class="auth-aside">
      <BrandMark :size="28" />
      <div class="aside-body">
        <h1 class="aside-title">你的剪贴板，<br />在每一台设备上。</h1>
        <p class="aside-text">自托管的剪贴板与文件同步工具。数据只存在你自己的服务器上。</p>
        <ul class="features">
          <li v-for="item in FEATURES" :key="item.title" class="feature">
            <span class="feature-icon"><component :is="item.icon" :size="16" /></span>
            <span>
              <span class="feature-title">{{ item.title }}</span>
              <span class="feature-text">{{ item.text }}</span>
            </span>
          </li>
        </ul>
      </div>
      <p class="aside-footer">ClipSync · 自托管</p>
    </aside>

    <main class="auth-main">
      <div class="auth-panel">
        <BrandMark class="mobile-brand" :size="28" />
        <h2 class="auth-title">{{ title }}</h2>
        <p v-if="subtitle" class="auth-subtitle">{{ subtitle }}</p>
        <slot />
      </div>
    </main>
  </div>
</template>

<style scoped>
.auth {
  display: grid;
  grid-template-columns: minmax(420px, 1fr) minmax(0, 1.1fr);
  min-height: 100vh;
  background: var(--color-bg);
}

.auth-aside {
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: var(--space-10) var(--space-12);
  background: var(--color-bg-subtle);
  border-right: 1px solid var(--color-border);
  overflow: hidden;
}

/* 很淡的网格底纹，增加层次但不抢内容 */
.auth-aside::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image: linear-gradient(var(--color-border) 1px, transparent 1px),
    linear-gradient(90deg, var(--color-border) 1px, transparent 1px);
  background-size: 32px 32px;
  mask-image: radial-gradient(ellipse at 30% 40%, #000 0%, transparent 70%);
  -webkit-mask-image: radial-gradient(ellipse at 30% 40%, #000 0%, transparent 70%);
  opacity: 0.6;
  pointer-events: none;
}

.auth-aside > * {
  position: relative;
}

.aside-body {
  max-width: 420px;
}

.aside-title {
  font-size: var(--text-display);
  font-weight: 600;
  line-height: 1.15;
  letter-spacing: -0.03em;
  color: var(--color-text);
}

.aside-text {
  margin-top: var(--space-4);
  font-size: var(--text-md);
  line-height: 1.6;
  color: var(--color-text-secondary);
}

.features {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  margin-top: var(--space-10);
}

.feature {
  display: flex;
  gap: var(--space-3);
}

.feature-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border-radius: var(--radius-md);
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  box-shadow: var(--shadow-xs);
  color: var(--color-text);
}

.feature-title {
  display: block;
  font-size: var(--text-base);
  font-weight: 500;
  color: var(--color-text);
}

.feature-text {
  display: block;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.aside-footer {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}

.auth-main {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-10) var(--space-6);
}

.auth-panel {
  width: 100%;
  max-width: 360px;
}

.mobile-brand {
  display: none;
  margin-bottom: var(--space-8);
}

.auth-title {
  font-size: var(--text-2xl);
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--color-text);
}

.auth-subtitle {
  margin-top: 6px;
  font-size: var(--text-base);
  color: var(--color-text-secondary);
}

@media (max-width: 900px) {
  .auth {
    grid-template-columns: 1fr;
  }

  .auth-aside {
    display: none;
  }

  .mobile-brand {
    display: inline-flex;
  }

  .auth-main {
    align-items: flex-start;
    padding-top: 12vh;
  }
}
</style>
