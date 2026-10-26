<script setup>
// 设置 / 修改 / 清除某样内容的访问码。保存成功后 emit('saved', 后端返回的 { access_code, access_expires_at, ... })
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { X, LoaderCircle, CircleAlert } from '@lucide/vue'
import { useAccessStore, useUserStore } from '../stores'
import { ACCESS_CODE_RE, ACCESS_CODE_RULE, MAX_EXPIRES_HOURS, normalizeCode, isExpired } from '../utils/accessCode'
import { formatDateTime, parseUtc } from '../utils/format'
import toast from '../utils/toast'
import { confirmDialog, dialogState } from '../utils/dialog'

const props = defineProps({
  // { targetType: 'clipboard' | 'text' | 'file', targetId, label, code, expiresAt }
  target: { type: Object, required: true },
})
const emit = defineEmits(['close', 'saved'])

const accessStore = useAccessStore()
const userStore = useUserStore()

const PRESETS = [
  { label: '1 小时', hours: 1 },
  { label: '1 天', hours: 24 },
  { label: '7 天', hours: 168 },
  { label: '30 天', hours: 720 },
  { label: '永久', hours: 0 },
]

const TYPE_LABELS = { clipboard: '云剪切板', text: '文本', file: '文件' }

const code = ref(props.target.code || '')
// 原来的过期时间还没到：默认保持不变，修改访问码时不会顺带改掉有效期
const canKeep = !!props.target.expiresAt && !isExpired(props.target.expiresAt)
const keep = ref(canKeep)
const hours = ref(0)
const saving = ref(false)
const error = ref('')
const codeInput = ref(null)

const normalized = computed(() => normalizeCode(code.value))
const fullCode = computed(() => `${userStore.username}@${normalized.value || '访问码'}`)
const targetText = computed(() => {
  const type = TYPE_LABELS[props.target.targetType]
  return props.target.label ? `${type}「${props.target.label}」` : type
})

const pickPreset = (value) => {
  keep.value = false
  hours.value = value
}

const close = () => emit('close')

// Esc 关闭；全局对话框（清除确认）打开时 Esc 只作用于它
const onKeydown = (event) => {
  if (event.key === 'Escape' && !dialogState.current) close()
}
onMounted(async () => {
  window.addEventListener('keydown', onKeydown)
  await nextTick()
  codeInput.value?.focus()
  codeInput.value?.select()
})
onUnmounted(() => window.removeEventListener('keydown', onKeydown))

const submit = async ({ clear = false } = {}) => {
  error.value = ''
  let expiresAt = null
  if (!clear) {
    if (!ACCESS_CODE_RE.test(normalized.value)) {
      error.value = '访问码需为 ' + ACCESS_CODE_RULE
      return
    }
    if (keep.value && canKeep) {
      expiresAt = parseUtc(props.target.expiresAt).toISOString()
    } else {
      const h = Number(hours.value || 0)
      if (!Number.isInteger(h) || h < 0 || h > MAX_EXPIRES_HOURS) {
        error.value = `有效期必须是 0 到 ${MAX_EXPIRES_HOURS} 之间的整数（小时）`
        return
      }
      expiresAt = h > 0 ? new Date(Date.now() + h * 3600 * 1000).toISOString() : null
    }
  }

  try {
    saving.value = true
    const result = await accessStore.setCode({
      targetType: props.target.targetType,
      targetId: props.target.targetId,
      code: clear ? null : normalized.value,
      expiresAt,
    })
    toast.success(clear ? '访问码已清除' : '访问码已设置')
    emit('saved', result)
    close()
  } catch (err) {
    error.value = err.message || '保存失败'
  } finally {
    saving.value = false
  }
}

const handleClear = async () => {
  const ok = await confirmDialog({
    title: '清除这个访问码？',
    message: '清除后，正在用这个访问码查看的人会立即退出（同一访问码下的其他内容不受影响）。',
    confirmText: '清除',
    danger: true,
  })
  if (ok) submit({ clear: true })
}
</script>

<template>
  <div class="modal-overlay" @mousedown.self="close">
    <form
      class="modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="access-code-title"
      @submit.prevent="submit()"
    >
      <div class="modal-header header-with-close">
        <div>
          <h2 id="access-code-title" class="modal-title">{{ target.code ? '修改访问码' : '设置访问码' }}</h2>
          <p class="modal-desc">{{ targetText }}</p>
        </div>
        <button type="button" class="btn-icon" aria-label="关闭" @click="close">
          <X />
        </button>
      </div>

      <div class="modal-body">
        <label class="field">
          <span class="field-label">访问码</span>
          <input
            ref="codeInput"
            v-model="code"
            class="input mono"
            type="text"
            maxlength="32"
            autocomplete="off"
            autocapitalize="off"
            spellcheck="false"
            placeholder="例如 work"
            :disabled="saving"
          />
          <span class="field-hint">{{ ACCESS_CODE_RULE }}。多样内容可以用同一个访问码。</span>
        </label>

        <div class="full-code">
          <span class="full-code-label">在登录页输入</span>
          <span class="mono full-code-value">{{ fullCode }}</span>
        </div>

        <div class="field">
          <span class="field-label">有效期</span>
          <div class="presets">
            <button
              v-if="canKeep"
              type="button"
              class="preset"
              :class="{ active: keep }"
              @click="keep = true"
            >
              保持不变（到 {{ formatDateTime(target.expiresAt) }}）
            </button>
            <button
              v-for="preset in PRESETS"
              :key="preset.label"
              type="button"
              class="preset"
              :class="{ active: !keep && Number(hours || 0) === preset.hours }"
              @click="pickPreset(preset.hours)"
            >
              {{ preset.label }}
            </button>
          </div>
          <span class="input-with-suffix">
            <input
              v-model.number="hours"
              class="input"
              type="number"
              min="0"
              :max="MAX_EXPIRES_HOURS"
              aria-label="有效期（小时）"
              placeholder="0 为永久"
              :disabled="saving"
              @input="keep = false"
            />
            <span class="input-suffix">小时</span>
          </span>
          <span class="field-hint">0 表示永久有效，最长 {{ MAX_EXPIRES_HOURS }} 小时（1 年）</span>
        </div>

        <p class="warn-text">知道完整访问码的人无需登录，就能查看和修改这个访问码下的文本、下载其中的文件，请妥善保管。</p>

        <div v-if="error" class="alert alert-danger" role="alert">
          <CircleAlert />
          <span>{{ error }}</span>
        </div>
      </div>

      <div class="modal-footer">
        <button
          v-if="target.code"
          type="button"
          class="btn btn-danger-outline footer-left"
          :disabled="saving"
          @click="handleClear"
        >
          清除访问码
        </button>
        <button type="button" class="btn btn-secondary" @click="close">取消</button>
        <button type="submit" class="btn btn-primary" :disabled="saving">
          <LoaderCircle v-if="saving" class="spin" />
          保存
        </button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.modal-desc {
  word-break: break-all;
}

.full-code {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  background: var(--color-bg-subtle);
  border: 1px solid var(--color-border);
}

.full-code-label {
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}

.full-code-value {
  font-size: var(--text-sm);
  color: var(--color-text);
  word-break: break-all;
}

.presets {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.preset {
  height: 28px;
  padding: 0 10px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--color-text-secondary);
  transition: all var(--duration) var(--ease);
}

.preset:hover {
  border-color: var(--color-border-hover);
  color: var(--color-text);
}

.preset.active {
  background: var(--color-primary);
  border-color: var(--color-primary);
  color: var(--color-text-inverse);
}

/* 单位是两个字「小时」，比全局的 48px 多留一点 */
.input-with-suffix .input {
  padding-right: 52px;
}

.warn-text {
  font-size: var(--text-xs);
  line-height: 1.6;
  color: var(--color-text-secondary);
}

.footer-left {
  margin-right: auto;
}
</style>
