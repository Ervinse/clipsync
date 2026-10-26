import toast from './toast'
import { copyDialog } from './dialog'

/**
 * 复制并给出反馈：成功弹 successMessage；自动复制失败（权限被拒、旧浏览器）时用 copyDialog
 * 显示内容，让用户手动复制。各页面的「复制」按钮都用它。
 */
export async function copyText(text, successMessage) {
  if (await copyToClipboard(text)) {
    toast.success(successMessage)
  } else {
    copyDialog({ value: text })
  }
}

/**
 * 复制到系统剪贴板
 *
 * navigator.clipboard 只在安全上下文（HTTPS / localhost）可用。项目支持纯 HTTP 内网部署，
 * 不满足时降级到隐藏 textarea + execCommand('copy')。返回是否复制成功。
 */
export async function copyToClipboard(text) {
  if (window.isSecureContext && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // 权限被拒等情况继续走降级方案
    }
  }

  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  let ok = false
  try {
    ok = document.execCommand('copy')
  } catch {
    ok = false
  }
  document.body.removeChild(textarea)
  return ok
}
