/**
 * 格式化工具
 *
 * 后端时间统一为 naive UTC，序列化时不带时区后缀，必须按 UTC 解析，否则会偏差本地时区（如 +8 小时）。
 */

const TZ_SUFFIX = /[zZ]|[+-]\d\d:?\d\d$/

/** 把后端返回的时间字符串按 UTC 解析为 Date；空值返回 null */
export function parseUtc(value) {
  if (!value) return null
  return new Date(TZ_SUFFIX.test(value) ? value : value + 'Z')
}

/** 绝对时间，例如 2026/10/01 14:30；空值显示 fallback */
export function formatDateTime(value, fallback = '-', withYear = true) {
  const date = parseUtc(value)
  if (!date || Number.isNaN(date.getTime())) return fallback
  return date.toLocaleString('zh-CN', {
    ...(withYear ? { year: 'numeric' } : {}),
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** 相对时间：刚刚 / N 分钟前 / N 小时前，超过一天显示绝对时间 */
export function formatRelative(value) {
  const date = parseUtc(value)
  if (!date || Number.isNaN(date.getTime())) return '-'
  const diff = Date.now() - date.getTime()
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return Math.floor(diff / 60000) + ' 分钟前'
  if (diff < 86400000) return Math.floor(diff / 3600000) + ' 小时前'
  return formatDateTime(value, '-', false)
}

/** 字节数格式化；非法值、0、负数都显示 0 B */
export function formatSize(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return +(bytes / 1024 ** i).toFixed(2) + ' ' + units[i]
}
