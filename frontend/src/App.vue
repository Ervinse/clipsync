<script setup>
// 根组件：路由视图 + 全局共用的提示条与对话框 + 液态折射用的 SVG 滤镜。全局样式与设计变量在 style.css
import { setLucideProps } from '@lucide/vue'
import ToastHost from './components/ToastHost.vue'
import DialogHost from './components/DialogHost.vue'

// 图标统一的默认尺寸与线宽（单个图标仍可用 :size 覆盖）
setLucideProps({ size: 16, strokeWidth: 1.75 })
</script>

<template>
  <!-- 液态折射滤镜：起伏的噪声纹理经柔化后作位移图，把背后的内容扭曲，像隔着有厚度的玻璃。
       由 style.css 的「液态玻璃」部分通过 backdrop-filter: url(#…) 引用（提示条、吸顶栏、卡片、表格、侧栏）；
       scale 是扭曲幅度：浅色 50（扭曲明显）、深色 16（轻度）。调大前先确认背后文字不至于变形难认 -->
  <svg class="liquid-defs" aria-hidden="true" focusable="false">
    <filter id="cs-liquid-light" x="0" y="0" width="100%" height="100%" color-interpolation-filters="sRGB">
      <feTurbulence type="fractalNoise" baseFrequency="0.006 0.014" numOctaves="2" seed="7" result="noise" />
      <feGaussianBlur in="noise" stdDeviation="2" result="ripple" />
      <feDisplacementMap in="SourceGraphic" in2="ripple" scale="50" xChannelSelector="R" yChannelSelector="G" />
    </filter>
    <filter id="cs-liquid-dark" x="0" y="0" width="100%" height="100%" color-interpolation-filters="sRGB">
      <feTurbulence type="fractalNoise" baseFrequency="0.006 0.014" numOctaves="2" seed="7" result="noise" />
      <feGaussianBlur in="noise" stdDeviation="2" result="ripple" />
      <feDisplacementMap in="SourceGraphic" in2="ripple" scale="16" xChannelSelector="R" yChannelSelector="G" />
    </filter>
  </svg>
  <router-view />
  <ToastHost />
  <DialogHost />
</template>

<style scoped>
/* 只用来存放滤镜定义，本身不占位、不显示 */
.liquid-defs {
  position: absolute;
  width: 0;
  height: 0;
  overflow: hidden;
}
</style>
