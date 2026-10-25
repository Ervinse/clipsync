<script setup>
// 开发环境专用的玻璃效果调节面板：只在 npm run dev 下由 App.vue 挂载，生产构建里不打包。
// 拖动滑块实时改写 <html> 上的设计变量（光斑、玻璃底色、光泽与亮边、卡片模糊）和折射滤镜的幅度，
// 用来对比「当前版本」与「夸张版」，定下数值后写回 style.css。
// 选择记在本浏览器 localStorage（键 glass-tuner），刷新后保持。
import { reactive, ref, watch, onMounted, onUnmounted } from 'vue'
import { SlidersHorizontal, X } from '@lucide/vue'
import toast from '../utils/toast'
import { copyToClipboard } from '../utils/clipboard'

const STORAGE_KEY = 'glass-tuner'

// current 与 style.css 里的数值一致；bold 是把各项都调到很明显的夸张版
const PRESETS = {
  current: { glow: 1, edge: 70, center: false, glass: 0.62, blur: 0, sheen: 1, refract: 16, liquidSurface: false },
  bold: { glow: 3.5, edge: 50, center: true, glass: 0.4, blur: 24, sheen: 2, refract: 50, liquidSurface: true },
}

// 光斑：[形状与位置, 颜色, 当前版本的不透明度]，与 style.css 的 --page-glow 一致
const SPOTS = {
  light: [
    ['42vmax 34vmax at 6% 8%', '62, 99, 221', 0.09],
    ['38vmax 32vmax at 94% 92%', '79, 70, 229', 0.07],
    ['30vmax 26vmax at 82% 14%', '59, 130, 246', 0.06],
    ['28vmax 24vmax at 18% 88%', '99, 102, 241', 0.05],
  ],
  dark: [
    ['42vmax 34vmax at 6% 8%', '123, 147, 240', 0.15],
    ['38vmax 32vmax at 94% 92%', '129, 140, 248', 0.11],
    ['30vmax 26vmax at 82% 14%', '96, 165, 250', 0.09],
    ['28vmax 24vmax at 18% 88%', '139, 135, 245', 0.08],
  ],
}
// 页面中部的一团：卡片多在中间，四角的光斑透不到卡片背后
const CENTER_SPOT = {
  light: ['30vmax 24vmax at 58% 46%', '62, 99, 221', 0.06],
  dark: ['30vmax 24vmax at 58% 46%', '123, 147, 240', 0.1],
}

const SLIDERS = [
  { key: 'glow', label: '光斑浓度', min: 0, max: 6, step: 0.1, unit: '×' },
  { key: 'edge', label: '光斑范围（越小边缘越清楚）', min: 30, max: 90, step: 1, unit: '%' },
  { key: 'glass', label: '玻璃不透明度（越小越透）', min: 0.1, max: 0.95, step: 0.01, unit: '' },
  { key: 'blur', label: '卡片与侧栏模糊', min: 0, max: 40, step: 1, unit: 'px' },
  { key: 'sheen', label: '光泽与亮边', min: 0, max: 3, step: 0.1, unit: '×' },
  { key: 'refract', label: '折射幅度', min: 0, max: 80, step: 1, unit: '' },
]
const SWITCHES = [
  { key: 'center', label: '页面中部加一团光斑' },
  { key: 'liquidSurface', label: '卡片与侧栏也用折射' },
]
const OVERRIDDEN = [
  '--page-glow',
  '--color-glass',
  '--color-glass-subtle',
  '--glass-sheen',
  '--color-highlight',
  '--color-lowlight',
  '--color-glass-rim',
  '--surface-filter',
]

function loadSaved() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY))
    if (saved && typeof saved === 'object') return { ...PRESETS.bold, ...saved }
  } catch {
    // 读不到就用夸张版
  }
  return { ...PRESETS.bold }
}

const state = reactive(loadSaved())
const open = ref(true)
const liquidSupported = document.documentElement.classList.contains('liquid-glass')

const clamp = (v) => Math.min(1, Math.max(0, Math.round(v * 1000) / 1000))
const white = (a) => `rgba(255, 255, 255, ${clamp(a)})`

function apply() {
  const root = document.documentElement
  const theme = root.dataset.theme === 'dark' ? 'dark' : 'light'
  const dark = theme === 'dark'
  const spots = state.center ? [...SPOTS[theme], CENTER_SPOT[theme]] : SPOTS[theme]
  const k = state.sheen

  const filter = []
  if (state.blur > 0) filter.push(`blur(${state.blur}px)`)
  if (state.liquidSurface && liquidSupported) filter.push('url(#cs-liquid)')
  if (filter.length) filter.push('saturate(170%)')

  const vars = {
    '--page-glow': spots
      .map(([shape, rgb, a]) => `radial-gradient(${shape}, rgba(${rgb}, ${clamp(a * state.glow)}), transparent ${state.edge}%)`)
      .join(', '),
    '--color-glass': dark ? `rgba(17, 17, 19, ${state.glass})` : `rgba(255, 255, 255, ${state.glass})`,
    '--color-glass-subtle': dark
      ? `rgba(24, 24, 27, ${clamp(state.glass + 0.04)})`
      : `rgba(249, 249, 250, ${clamp(state.glass + 0.04)})`,
    '--glass-sheen': dark
      ? `linear-gradient(135deg, ${white(0.04 * k)}, rgba(255, 255, 255, 0) 45%)`
      : `linear-gradient(135deg, ${white(0.5 * k)}, ${white(0.12 * k)} 35%, rgba(255, 255, 255, 0) 60%)`,
    '--color-highlight': white((dark ? 0.09 : 0.9) * k),
    '--color-lowlight': dark ? `rgba(0, 0, 0, ${clamp(0.3 * k)})` : `rgba(16, 16, 20, ${clamp(0.05 * k)})`,
    '--color-glass-rim': white((dark ? 0.03 : 0.4) * k),
    '--surface-filter': filter.length ? filter.join(' ') : 'none',
  }
  for (const [name, value] of Object.entries(vars)) root.style.setProperty(name, value)

  document.querySelector('#cs-liquid feDisplacementMap')?.setAttribute('scale', String(state.refract))
}

function usePreset(name) {
  Object.assign(state, PRESETS[name])
}

function showToast() {
  toast.success('这是一条提示，看看它背后的模糊和折射')
}

async function copyValues() {
  const ok = await copyToClipboard(JSON.stringify(state))
  if (ok) toast.success('已复制当前数值，发给 Claude 即可')
  else toast.error('复制失败，请手动记下面板上的数值')
}

watch(
  state,
  () => {
    apply()
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
    } catch {
      // 存不了只是刷新后回到夸张版
    }
  },
  { deep: true },
)

// 切换主题后按新主题重新计算颜色
let observer = null
onMounted(() => {
  apply()
  observer = new MutationObserver(apply)
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
})
onUnmounted(() => {
  observer?.disconnect()
  OVERRIDDEN.forEach((name) => document.documentElement.style.removeProperty(name))
})
</script>

<template>
  <div class="tuner">
    <button
      v-if="!open"
      type="button"
      class="tuner-toggle"
      aria-label="打开玻璃效果调节面板"
      @click="open = true"
    >
      <SlidersHorizontal :size="18" />
    </button>

    <section v-else class="tuner-panel" aria-label="玻璃效果调节面板">
      <header class="tuner-head">
        <span class="tuner-title">玻璃效果调节（仅开发环境）</span>
        <button type="button" class="btn-icon" aria-label="收起面板" @click="open = false">
          <X :size="16" />
        </button>
      </header>

      <div class="tuner-presets">
        <button type="button" class="btn btn-secondary btn-sm" @click="usePreset('current')">当前版本</button>
        <button type="button" class="btn btn-secondary btn-sm" @click="usePreset('bold')">夸张版</button>
      </div>

      <label v-for="item in SLIDERS" :key="item.key" class="tuner-row">
        <span class="tuner-label">
          <span>{{ item.label }}</span>
          <span class="tuner-value">{{ state[item.key] }}{{ item.unit }}</span>
        </span>
        <input
          v-model.number="state[item.key]"
          type="range"
          :min="item.min"
          :max="item.max"
          :step="item.step"
        />
      </label>

      <label v-for="item in SWITCHES" :key="item.key" class="switch tuner-switch">
        <input v-model="state[item.key]" type="checkbox" />
        <span class="switch-track"></span>
        {{ item.label }}
      </label>

      <p v-if="!liquidSupported" class="tuner-note">当前浏览器不支持折射，只有 Chrome / Edge 能看到。</p>

      <div class="tuner-actions">
        <button type="button" class="btn btn-secondary btn-sm" @click="showToast">弹一条提示</button>
        <button type="button" class="btn btn-primary btn-sm" @click="copyValues">复制数值</button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.tuner {
  position: fixed;
  right: var(--space-4);
  bottom: var(--space-4);
  z-index: 1200;
}

.tuner-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: 1px solid var(--color-border-strong);
  background: var(--color-bg);
  color: var(--color-text);
  box-shadow: var(--shadow-md);
}

/* 面板本身用不透明底色，调节时不受玻璃效果影响，数值始终看得清 */
.tuner-panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  width: min(300px, calc(100vw - 32px));
  max-height: calc(100vh - 32px);
  overflow-y: auto;
  padding: var(--space-4);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-lg);
  background: var(--color-bg);
  box-shadow: var(--shadow-lg);
  font-size: var(--text-sm);
}

.tuner-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.tuner-title {
  font-weight: 600;
  color: var(--color-text);
}

.tuner-presets,
.tuner-actions {
  display: flex;
  gap: var(--space-2);
}

.tuner-presets .btn,
.tuner-actions .btn {
  flex: 1;
}

.tuner-row {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.tuner-label {
  display: flex;
  justify-content: space-between;
  gap: var(--space-2);
  color: var(--color-text-secondary);
}

.tuner-value {
  font-variant-numeric: tabular-nums;
  color: var(--color-text);
}

.tuner-row input[type='range'] {
  width: 100%;
  accent-color: var(--color-accent);
}

.tuner-switch {
  font-size: var(--text-sm);
}

.tuner-note {
  font-size: var(--text-xs);
  color: var(--color-warning);
}
</style>
