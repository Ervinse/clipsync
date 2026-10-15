/**
 * 对话框：替代浏览器原生的 confirm / prompt，样式与页面一致。
 *
 * - confirmDialog({ title, message, confirmText, danger }) → Promise<boolean>
 * - promptDialog({ title, message, label, defaultValue, inputType, suffix }) → Promise<string | null>（取消为 null）
 * - copyDialog({ title, message, value }) → Promise<void>：复制失败时展示内容让用户手动复制
 * - choiceDialog({ title, message, choices: [{ value, label, danger }] }) → Promise<value | null>（取消为 null）
 *
 * 显示由 components/DialogHost.vue 负责（挂在 App.vue）。同一时间只有一个对话框，
 * 新打开的会把还没关闭的那个当作「取消」处理。
 */
import { reactive } from 'vue'

export const dialogState = reactive({ current: null })

const CANCEL_RESULT = { confirm: false, prompt: null, copy: undefined, choice: null }

function open(kind, options) {
  const previous = dialogState.current
  if (previous) {
    dialogState.current = null
    previous.resolve(CANCEL_RESULT[previous.kind])
  }
  return new Promise((resolve) => {
    dialogState.current = { kind, ...options, resolve }
  })
}

/** 关闭当前对话框并返回结果；result 省略时按「取消」处理 */
export function closeDialog(result) {
  const current = dialogState.current
  if (!current) return
  dialogState.current = null
  current.resolve(result === undefined ? CANCEL_RESULT[current.kind] : result)
}

export function confirmDialog({ title, message = '', confirmText = '确定', cancelText = '取消', danger = false }) {
  return open('confirm', { title, message, confirmText, cancelText, danger })
}

export function promptDialog({
  title,
  message = '',
  label = '',
  defaultValue = '',
  inputType = 'text',
  suffix = '',
  confirmText = '确定',
  cancelText = '取消',
}) {
  return open('prompt', { title, message, label, defaultValue: String(defaultValue ?? ''), inputType, suffix, confirmText, cancelText })
}

export function copyDialog({ title = '请手动复制', message = '自动复制失败，请选中下面的内容后手动复制。', value }) {
  return open('copy', { title, message, value: String(value ?? '') })
}

export function choiceDialog({ title, message = '', choices, cancelText = '取消' }) {
  return open('choice', { title, message, choices, cancelText })
}
