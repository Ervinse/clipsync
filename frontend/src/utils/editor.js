/**
 * 编辑框共用的小工具：保存快捷键、离开页面前确认放弃未保存的修改
 * （云剪切板页、文本页、快速访问页与文本编辑卡片共用）
 */
import { confirmDialog } from './dialog'

// 快捷键提示：苹果设备用 ⌘，其余用 Ctrl（按键判断两者都认）
export const SAVE_KEY_HINT = /Mac|iPhone|iPad|iPod/i.test(navigator.userAgent) ? '⌘ + S' : 'Ctrl + S'

/** 是否按下了保存快捷键 Ctrl/⌘ + S */
export function isSaveShortcut(event) {
  return (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's'
}

/** 离开页面前确认放弃未保存的修改；message 说明会丢掉什么。返回用户是否同意离开 */
export function confirmDiscardChanges(message = '有文本还没有保存，离开后会丢失。') {
  return confirmDialog({
    title: '放弃未保存的修改？',
    message,
    confirmText: '放弃并离开',
    cancelText: '继续编辑',
    danger: true,
  })
}
