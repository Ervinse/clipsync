<script setup>
// 根组件：路由视图 + 全局共用的提示条与对话框。全局样式与设计变量在 style.css
import { setLucideProps } from '@lucide/vue'
import ToastHost from './components/ToastHost.vue'
import DialogHost from './components/DialogHost.vue'

// 图标统一的默认尺寸与线宽（单个图标仍可用 :size 覆盖）
setLucideProps({ size: 16, strokeWidth: 1.75 })
</script>

<template>
  <router-view />
  <ToastHost />
  <DialogHost />
</template>
