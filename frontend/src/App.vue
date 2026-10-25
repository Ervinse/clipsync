<script setup>
// 根组件：路由视图 + 全局共用的提示条与对话框 + 液态折射用的 SVG 滤镜。全局样式与设计变量在 style.css
import { defineAsyncComponent } from 'vue'
import { setLucideProps } from '@lucide/vue'
import ToastHost from './components/ToastHost.vue'
import DialogHost from './components/DialogHost.vue'

// 开发环境专用的玻璃效果调节面板；生产构建时 import.meta.env.DEV 为 false，组件不会打包
const GlassTuner = import.meta.env.DEV ? defineAsyncComponent(() => import('./components/GlassTuner.vue')) : null

// 图标统一的默认尺寸与线宽（单个图标仍可用 :size 覆盖）
setLucideProps({ size: 16, strokeWidth: 1.75 })
</script>

<template>
  <!-- 液态折射滤镜：起伏的噪声纹理经柔化后作位移图，把背后的内容轻微扭曲，像隔着有厚度的玻璃。
       由 style.css 的 .liquid（提示条、吸顶栏）通过 backdrop-filter: url(#cs-liquid) 引用；
       scale 是扭曲幅度，调大前先在浅色、深色下确认背后文字不至于变形难认 -->
  <svg class="liquid-defs" aria-hidden="true" focusable="false">
    <filter id="cs-liquid" x="0" y="0" width="100%" height="100%" color-interpolation-filters="sRGB">
      <feTurbulence type="fractalNoise" baseFrequency="0.006 0.014" numOctaves="2" seed="7" result="noise" />
      <feGaussianBlur in="noise" stdDeviation="2" result="ripple" />
      <feDisplacementMap in="SourceGraphic" in2="ripple" scale="16" xChannelSelector="R" yChannelSelector="G" />
    </filter>
  </svg>
  <router-view />
  <ToastHost />
  <DialogHost />
  <GlassTuner v-if="GlassTuner" />
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
