<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '../stores'

const router = useRouter()
const userStore = useUserStore()

const form = ref({
  username: '',
  password: '',
  confirmPassword: '',
  invite_code: '',
})
const loading = ref(false)
const error = ref('')
const success = ref(false)

const handleRegister = async () => {
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

const goToLogin = () => {
  router.push('/login')
}
</script>

<template>
  <div class="register-page">
    <div class="register-container">
      <div class="register-header">
        <h1>注册 ClipSync</h1>
        <p>创建账号开始使用</p>
      </div>

      <form v-if="!success" class="register-form" @submit.prevent="handleRegister">
        <div class="form-group">
          <label>用户名 *</label>
          <input
            v-model="form.username"
            type="text"
            placeholder="输入用户名"
            :disabled="loading"
          />
        </div>

        <div class="form-group">
          <label>密码 *</label>
          <input
            v-model="form.password"
            type="password"
            placeholder="至少 8 位"
            :disabled="loading"
          />
        </div>

        <div class="form-group">
          <label>确认密码 *</label>
          <input
            v-model="form.confirmPassword"
            type="password"
            placeholder="再次输入密码"
            :disabled="loading"
          />
        </div>

        <div class="form-group">
          <label>邀请码 *</label>
          <input
            v-model="form.invite_code"
            type="text"
            placeholder="输入邀请码"
            :disabled="loading"
          />
        </div>

        <div v-if="error" class="error-message">
          {{ error }}
        </div>

        <button type="submit" class="btn-primary" :disabled="loading">
          {{ loading ? '注册中...' : '注册' }}
        </button>

        <div class="form-footer">
          <span>已有账号？</span>
          <a @click="goToLogin">立即登录</a>
        </div>
      </form>

      <div v-else class="success-message">
        <div class="success-icon">✓</div>
        <h2>注册成功！</h2>
        <p>正在跳转到登录页面...</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.register-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #0B0E14;
  padding: 2rem;
}

.register-container {
  width: 100%;
  max-width: 420px;
  background: #1E293B;
  border: 1px solid #334155;
  border-radius: 12px;
  padding: 3rem 2.5rem;
}

.register-header {
  text-align: center;
  margin-bottom: 2.5rem;
}

.register-header h1 {
  font-size: 2rem;
  font-weight: 700;
  color: #F8FAFC;
  margin-bottom: 0.5rem;
}

.register-header p {
  font-size: 0.95rem;
  color: #94A3B8;
}

.register-form {
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

.success-message {
  text-align: center;
  padding: 2rem 0;
}

.success-icon {
  width: 64px;
  height: 64px;
  margin: 0 auto 1.5rem;
  background: rgba(34, 211, 238, 0.15);
  border: 2px solid #22D3EE;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 2rem;
  color: #22D3EE;
  font-weight: bold;
}

.success-message h2 {
  font-size: 1.5rem;
  color: #F8FAFC;
  margin-bottom: 0.5rem;
}

.success-message p {
  color: #94A3B8;
  font-size: 0.95rem;
}
</style>