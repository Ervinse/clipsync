<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { CircleAlert, CircleCheck, LoaderCircle } from '@lucide/vue'
import { useUserStore } from '../stores'
import AuthLayout from '../components/AuthLayout.vue'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

// 邀请信息里的注册链接带 ?code=，打开后自动填好邀请码（仍可修改）
const codeFromLink = typeof route.query.code === 'string' ? route.query.code.trim().slice(0, 32) : ''

const form = ref({
  username: '',
  password: '',
  confirmPassword: '',
  invite_code: codeFromLink,
})
const loading = ref(false)
const error = ref('')
const success = ref(false)

const handleRegister = async () => {
  // 复制粘贴时容易带上首尾空格：用户名和邀请码先去掉（密码不处理，空格可能是密码的一部分）
  form.value.username = form.value.username.trim()
  form.value.invite_code = form.value.invite_code.trim()

  // 验证
  if (!form.value.username || !form.value.password || !form.value.invite_code) {
    error.value = '请填写所有必填项'
    return
  }

  // 与后端 schemas/user.py 一致：用户名 3-64 位字母数字及 _ . -，密码 8-72 字节
  if (!/^[A-Za-z0-9_.-]{3,64}$/.test(form.value.username)) {
    error.value = '用户名为 3-64 位，只能包含字母、数字、_ . -'
    return
  }

  if (form.value.password.length < 8) {
    error.value = '密码长度至少 8 位'
    return
  }

  if (new TextEncoder().encode(form.value.password).length > 72) {
    error.value = '密码不能超过 72 字节'
    return
  }

  if (form.value.password !== form.value.confirmPassword) {
    error.value = '两次输入的密码不一致'
    return
  }

  try {
    loading.value = true
    error.value = ''

    await userStore.register({
      username: form.value.username,
      password: form.value.password,
      invite_code: form.value.invite_code,
    })

    success.value = true
    setTimeout(() => {
      router.push('/login')
    }, 2000)
  } catch (err) {
    error.value = err.message || '注册失败，请检查信息'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <AuthLayout
    :title="success ? '注册成功' : '创建账号'"
    :subtitle="success ? '' : '需要管理员提供的邀请码'"
  >
    <form v-if="!success" class="auth-form" @submit.prevent="handleRegister">
      <label class="field">
        <span class="field-label">邀请码</span>
        <input
          v-model="form.invite_code"
          class="input input-lg mono"
          type="text"
          autocomplete="off"
          placeholder="输入邀请码"
          :disabled="loading"
        />
      </label>

      <label class="field">
        <span class="field-label">用户名</span>
        <input
          v-model="form.username"
          class="input input-lg"
          type="text"
          autocomplete="username"
          placeholder="3-64 位字母、数字、_ . -"
          :disabled="loading"
        />
      </label>

      <label class="field">
        <span class="field-label">密码</span>
        <input
          v-model="form.password"
          class="input input-lg"
          type="password"
          autocomplete="new-password"
          placeholder="至少 8 位"
          :disabled="loading"
        />
      </label>

      <label class="field">
        <span class="field-label">确认密码</span>
        <input
          v-model="form.confirmPassword"
          class="input input-lg"
          type="password"
          autocomplete="new-password"
          placeholder="再次输入密码"
          :disabled="loading"
        />
      </label>

      <div v-if="error" class="alert alert-danger" role="alert">
        <CircleAlert />
        <span>{{ error }}</span>
      </div>

      <button type="submit" class="btn btn-primary btn-lg btn-block" :disabled="loading">
        <LoaderCircle v-if="loading" class="spin" />
        {{ loading ? '注册中…' : '注册' }}
      </button>
    </form>

    <div v-else class="success" role="status">
      <span class="success-icon"><CircleCheck :size="20" /></span>
      <p>账号已创建，正在跳转到登录页…</p>
    </div>

    <p v-if="!success" class="auth-switch">
      已有账号？
      <router-link to="/login">直接登录</router-link>
    </p>
  </AuthLayout>
</template>

<style scoped>
.auth-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  margin-top: var(--space-8);
}

.auth-form .btn {
  margin-top: var(--space-2);
}

.auth-switch {
  margin-top: var(--space-6);
  padding-top: var(--space-6);
  border-top: 1px solid var(--color-border);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}

.success {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-top: var(--space-6);
  padding: var(--space-4);
  border-radius: var(--radius-md);
  background: var(--color-success-subtle);
  color: var(--color-success);
  font-size: var(--text-base);
}

.success-icon {
  display: flex;
}
</style>
