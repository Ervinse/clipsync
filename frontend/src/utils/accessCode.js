/**
 * 快速访问码：格式规则、有效期上限、过期判断（规则与后端 core/quick_access.py 一致）
 */
import { parseUtc } from './format'

// 4–32 位字母、数字与 _ - .，不区分大小写（统一转小写）
export const ACCESS_CODE_RE = /^[a-z0-9_.-]{4,32}$/
export const ACCESS_CODE_RULE = '4–32 位，只能包含字母、数字和 _ - .，不区分大小写'
// 访问码最长有效期：1 年
export const MAX_EXPIRES_HOURS = 8760

export function normalizeCode(value) {
  return String(value || '').trim().toLowerCase()
}

/** 后端时间为 naive UTC，parseUtc 按 UTC 解析；没有过期时间视为永不过期 */
export function isExpired(expiresAt, now = Date.now()) {
  const date = parseUtc(expiresAt)
  return !!date && date.getTime() <= now
}
