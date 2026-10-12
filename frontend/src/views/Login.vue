<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { CircleAlert, LoaderCircle } from '@lucide/vue'
import { useUserStore } from '../stores'
import AuthLayout from '../components/AuthLayout.vue'

const router = useRouter()
const userStore = useUserStore()

const form = ref({
  username: '',
  password: '',
})
const loading = ref(false)
// 启动时连不上服务器会被守卫带到这里：先显示原因（token 仍保留，恢复后刷新即可）
const error = ref(userStore.connectionError)

const handleLogin = async () => {
  if (!form.value.username || !form.value.password) {
    error.value = '请输入用户名和密码'
    return
  }

  try {
    loading.value = true
    error.value = ''
    await userStore.login(form.value)
    router.push('/clipboard')
  } catch (err) {
    // 拦截器 reject 的是 { status, message }，后端 detail 已放进 message
    error.value = err.message || '登录失败，请检查用户名和密码'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <AuthLayout title="登录" subtitle="欢迎回来，登录后继续同步">
    <form class="auth-form" @submit.prevent="handleLogin">
      <label class="field">
        <span class="field-label">用户名</span>
        <input
          v-model="form.username"
          class="input input-lg"
          type="text"
          autocomplete="username"
          placeholder="输入用户名"
          :disabled="loading"
        />
      </label>

      <label class="field">
        <span class="field-label">密码</span>
        <input
          v-model="form.password"
          class="input input-lg"
          type="password"
          autocomplete="current-password"
          placeholder="输入密码"
          :disabled="loading"
        />
      </label>

      <div v-if="error" class="alert alert-danger" role="alert">
        <CircleAlert />
        <span>{{ error }}</span>
      </div>

      <button type="submit" class="btn btn-primary btn-lg btn-block" :disabled="loading">
        <LoaderCircle v-if="loading" class="spin" />
        {{ loading ? '登录中…' : '登录' }}
      </button>
    </form>

    <p class="auth-switch">
      还没有账号？
      <router-link to="/register">使用邀请码注册</router-link>
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
</style>
