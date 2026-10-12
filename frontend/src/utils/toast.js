/**
 * 轻提示（toast）：操作结果的短消息，显示在窗口底部居中，几秒后自动消失。
 *
 * 用法：toast.success('已保存')、toast.error('保存失败：…')、toast.info('…')
 * 显示由 components/ToastHost.vue 负责（挂在 App.vue，所有页面共用一个）。
 */
import { reactive } from 'vue'

// 同时最多显示的条数，超出时最早的一条先消失
const MAX_ITEMS = 3

export const toastState = reactive({ items: [] })

let seq = 0

export function dismissToast(id) {
  const index = toastState.items.findIndex((item) => item.id === id)
  if (index !== -1) toastState.items.splice(index, 1)
}

function push(type, message, duration) {
  const id = ++seq
  toastState.items.push({ id, type, message })
  if (toastState.items.length > MAX_ITEMS) toastState.items.shift()
  setTimeout(() => dismissToast(id), duration)
  return id
}

const toast = {
  success: (message, duration = 2500) => push('success', message, duration),
  info: (message, duration = 2500) => push('info', message, duration),
  // 错误信息通常更长，多留一会儿
  error: (message, duration = 4500) => push('error', message, duration),
}

export default toast
