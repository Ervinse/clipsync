// 主题：跟随系统 / 浅色 / 深色。选择只存在本浏览器的 localStorage（键 theme，跟随系统时不存），不随账号同步。
// 实际生效的是 <html data-theme="light|dark">，style.css 按它切换颜色变量。
// index.html 里有一段同样规则的内联脚本，在页面渲染前先设好 data-theme，深色用户刷新时不会先闪一下白底。
import { ref } from 'vue'

const STORAGE_KEY = 'theme'
const MODES = ['system', 'light', 'dark']
const media = window.matchMedia('(prefers-color-scheme: dark)')

// 隐私模式或禁用存储时读写 localStorage 会抛错，按「跟随系统」处理
const readMode = () => {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    return MODES.includes(value) ? value : 'system'
  } catch {
    return 'system'
  }
}

export const themeMode = ref(readMode())

// 切换时给 <html> 临时加上 theme-switching，style.css 据此让颜色渐变（时长与 --theme-duration 一致，略留余量）；
// 渐变结束就去掉，平时的悬停、展开等动效不受影响
const SWITCH_CLASS = 'theme-switching'
const SWITCH_MS = 450
let switchTimer = null

const apply = ({ animate = false } = {}) => {
  const root = document.documentElement
  const dark = themeMode.value === 'dark' || (themeMode.value === 'system' && media.matches)
  const theme = dark ? 'dark' : 'light'
  if (root.dataset.theme === theme) return
  if (animate) {
    root.classList.add(SWITCH_CLASS)
    clearTimeout(switchTimer)
    switchTimer = setTimeout(() => root.classList.remove(SWITCH_CLASS), SWITCH_MS)
  }
  root.dataset.theme = theme
}

export const setThemeMode = (mode) => {
  if (!MODES.includes(mode)) return
  themeMode.value = mode
  try {
    if (mode === 'system') localStorage.removeItem(STORAGE_KEY)
    else localStorage.setItem(STORAGE_KEY, mode)
  } catch {
    // 存不下只影响下次打开，本次切换照样生效
  }
  apply({ animate: true })
}

// 跟随系统时，系统深浅色变化立即生效
media.addEventListener('change', () => apply({ animate: true }))

// 其他标签页切换了主题，本页同步
window.addEventListener('storage', (event) => {
  if (event.key === STORAGE_KEY || event.key === null) {
    themeMode.value = readMode()
    apply({ animate: true })
  }
})

// 首次进入页面不做渐变
apply()
