<script setup>
// 全局对话框：确认、输入、手动复制、多选一四种，由 utils/dialog.js 打开。
// Esc 或点遮罩为取消；输入框打开时自动聚焦，回车提交
import { ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { dialogState, closeDialog } from '../utils/dialog'

const inputValue = ref('')
const inputRef = ref(null)
const confirmRef = ref(null)
const cancelRef = ref(null)

watch(
  () => dialogState.current,
  async (current) => {
    if (!current) return
    inputValue.value = current.kind === 'prompt' ? current.defaultValue : ''
    await nextTick()
    if (current.kind === 'prompt' || current.kind === 'copy') {
      inputRef.value?.focus()
      inputRef.value?.select()
    } else if (current.danger || current.kind === 'choice') {
      // 危险操作与多选一默认聚焦「取消」：误按回车不会直接删除或覆盖
      cancelRef.value?.focus()
    } else {
      confirmRef.value?.focus()
    }
  },
)

const cancel = () => closeDialog()

const submit = () => {
  const current = dialogState.current
  if (!current) return
  // 多选一只能点按钮选择，回车不代替用户做决定
  if (current.kind === 'choice') return
  if (current.kind === 'confirm') closeDialog(true)
  // type="number" 的输入框经 v-model 得到的是数字，调用方按字符串处理，这里统一转成字符串
  else if (current.kind === 'prompt') closeDialog(String(inputValue.value ?? ''))
  else closeDialog()
}

const onKeydown = (event) => {
  if (event.key === 'Escape' && dialogState.current) cancel()
}
onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div v-if="dialogState.current" class="modal-overlay" @mousedown.self="cancel">
    <form
      class="modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="dialog-title"
      @submit.prevent="submit"
    >
      <div class="modal-header">
        <h2 id="dialog-title" class="modal-title">{{ dialogState.current.title }}</h2>
        <p v-if="dialogState.current.message" class="modal-desc">{{ dialogState.current.message }}</p>
      </div>

      <div v-if="dialogState.current.kind === 'prompt'" class="modal-body">
        <label class="field">
          <span v-if="dialogState.current.label" class="field-label">{{ dialogState.current.label }}</span>
          <span class="input-with-suffix">
            <input
              ref="inputRef"
              v-model="inputValue"
              class="input"
              :type="dialogState.current.inputType"
            />
            <span v-if="dialogState.current.suffix" class="input-suffix">{{ dialogState.current.suffix }}</span>
          </span>
        </label>
      </div>

      <div v-else-if="dialogState.current.kind === 'copy'" class="modal-body">
        <textarea
          ref="inputRef"
          class="input copy-area mono"
          readonly
          rows="3"
          :value="dialogState.current.value"
        ></textarea>
      </div>

      <div class="modal-footer" :class="{ 'no-body': dialogState.current.kind === 'confirm' || dialogState.current.kind === 'choice' }">
        <template v-if="dialogState.current.kind === 'copy'">
          <button type="submit" class="btn btn-primary">关闭</button>
        </template>
        <template v-else-if="dialogState.current.kind === 'choice'">
          <button ref="cancelRef" type="button" class="btn btn-secondary" @click="cancel">
            {{ dialogState.current.cancelText }}
          </button>
          <button
            v-for="choice in dialogState.current.choices"
            :key="choice.value"
            type="button"
            class="btn"
            :class="choice.danger ? 'btn-danger' : 'btn-primary'"
            @click="closeDialog(choice.value)"
          >
            {{ choice.label }}
          </button>
        </template>
        <template v-else>
          <button ref="cancelRef" type="button" class="btn btn-secondary" @click="cancel">
            {{ dialogState.current.cancelText }}
          </button>
          <button
            ref="confirmRef"
            type="submit"
            class="btn"
            :class="dialogState.current.danger ? 'btn-danger' : 'btn-primary'"
          >
            {{ dialogState.current.confirmText }}
          </button>
        </template>
      </div>
    </form>
  </div>
</template>

<style scoped>
.modal-footer.no-body {
  margin-top: var(--space-5);
}

.input-with-suffix {
  position: relative;
  display: block;
}

.input-with-suffix .input {
  padding-right: 48px;
}

.input-suffix {
  position: absolute;
  right: var(--space-3);
  top: 50%;
  transform: translateY(-50%);
  font-size: var(--text-sm);
  color: var(--color-text-tertiary);
  pointer-events: none;
}

.copy-area {
  height: auto;
  padding: var(--space-2) var(--space-3);
  resize: none;
  word-break: break-all;
}
</style>
