// 玻璃质感里需要脚本的两部分（样式本身在 style.css 的「质感层」与「液态玻璃」）：
// 1. 液态折射：backdrop-filter 引用 SVG 滤镜（App.vue 的 #cs-liquid-light / #cs-liquid-dark）只有 Chromium 内核浏览器（Chrome、Edge）会真正渲染，
//    其他浏览器即使不报错也不生效，所以只在 Chromium 上给 <html> 加 liquid-glass，style.css 据此启用折射，其余保持普通毛玻璃。
// 2. 悬停高光：有鼠标的设备上，把鼠标在按钮 / 可悬停卡片里的位置写成 --mx / --my，style.css 用它画一团跟着鼠标走的柔光。

const HOVER_GLOW_SELECTOR = '.btn-primary, .btn-secondary, .btn-danger-outline, .card-hover'

function supportsLiquidGlass() {
  try {
    // navigator.userAgentData 只有 Chromium 内核提供，比解析 userAgent 字符串可靠
    const isChromium = !!navigator.userAgentData?.brands?.some((item) => item.brand === 'Chromium')
    return isChromium && CSS.supports('backdrop-filter', 'url(#cs-liquid-light) blur(1px)')
  } catch {
    return false
  }
}

if (supportsLiquidGlass()) {
  document.documentElement.classList.add('liquid-glass')
}

if (window.matchMedia('(hover: hover)').matches) {
  let pending = null
  // 每帧最多更新一次，鼠标快速移动时不会反复读写布局
  document.addEventListener(
    'pointermove',
    (event) => {
      if (pending) return
      pending = requestAnimationFrame(() => {
        pending = null
        const el = event.target instanceof Element ? event.target.closest(HOVER_GLOW_SELECTOR) : null
        if (!el) return
        const rect = el.getBoundingClientRect()
        el.style.setProperty('--mx', `${event.clientX - rect.left}px`)
        el.style.setProperty('--my', `${event.clientY - rect.top}px`)
      })
    },
    { passive: true },
  )
}
