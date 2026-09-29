<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '../stores'

const router = useRouter()
const userStore = useUserStore()

const form = ref({
  username: '',
  password: '',
})
const loading = ref(false)
const error = ref('')

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
    error.value = err.response?.data?.detail || '登录失败，请检查用户名和密码'
  } finally {
    loading.value = false
  }
}

const goToRegister = () => {
  router.push('/register')
}
</script>

<template>
  <div class="login-page">
    <div class="login-container">
      <div class="login-header">
        <h1>ClipSync</h1>
        <p>跨设备剪贴板与文件同步</p>
      </div>

      <form class="login-form" @submit.prevent="handleLogin">
        <div class="form-group">
          <label>用户名</label>
          <input
            v-model="form.username"
            type="text"
            placeholder="输入用户名"
            :disabled="loading"
          />
        </div>

        <div class="form-group">
          <label>密码</label>
          <input
            v-model="form.password"
            type="password"
            placeholder="输入密码"
            :disabled="loading"
          />
        </div>

        <div v-if="error" class="error-message">
          {{ error }}
        </div>

        <button type="submit" class="btn-primary" :disabled="loading">
          {{ loading ? '登录中...' : '登录' }}
        </button>

        <div class="form-footer">
          <span>还没有账号？</span>
          <a @click="goToRegister">立即注册</a>
        </div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #0B0E14;
  padding: 2rem;
}

.login-container {
  width: 100%;
  max-width: 420px;
  background: #1E293B;
  border: 1px solid #334155;
  border-radius: 12px;
  padding: 3rem 2.5rem;
}

.login-header {
  text-align: center;
  margin-bottom: 2.5rem;
}

.login-header h1 {
  font-size: 2rem;
  font-weight: 700;
  color: #F8FAFC;
  margin-bottom: 0.5rem;
}

.login-header p {
  font-size: 0.95rem;
  color: #94A3B8;
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.form-group label {
  font-size: 0.9rem;
  font-weight: 500;
  color: #CBD5E1;
}

.form-group input {
  padding: 0.75rem 1rem;
  background: #0F172A;
  border: 1px solid #334155;
  border-radius: 8px;
  color: #F8FAFC;
  font-size: 0.95rem;
  transition: all 0.2s;
}

.form-group input:focus {
  outline: none;
  border-color: #38BDF8;
  box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.1);
}

.form-group input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.form-group input::placeholder {
  color: #64748B;
}

.error-message {
  padding: 0.75rem 1rem;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 8px;
  color: #FCA5A5;
  font-size: 0.9rem;
}

.btn-primary {
  padding: 0.875rem 1.5rem;
  background: #38BDF8;
  color: #0F172A;
  border: none;
  border-radius: 8px;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-primary:hover:not(:disabled) {
  background: #22D3EE;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(56, 189, 248, 0.3);
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.form-footer {
  text-align: center;
  font-size: 0.9rem;
  color: #94A3B8;
}

.form-footer a {
  color: #38BDF8;
  text-decoration: none;
  cursor: pointer;
  margin-left: 0.25rem;
}

.form-footer a:hover {
  text-decoration: underline;
}
</style>