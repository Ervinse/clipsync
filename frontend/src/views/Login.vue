<script setup>
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { CircleAlert, LoaderCircle, KeyRound } from '@lucide/vue'
import { useUserStore, useQuickStore } from '../stores'
import AuthLayout from '../components/AuthLayout.vue'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const quickStore = useQuickStore()

// 登录过期被带到这里时，query.redirect 是原来所在的页面：登录后回到那里。
// 只接受站内路径（以单个 / 开头），防止被构造成跳到其他网站的链接
const redirectTarget = () => {
  const target = route.query.redirect
  if (typeof target !== 'string' || !target.startsWith('/') || target.startsWith('//')) return '/clipboard'
  if (target.startsWith('/login') || target.startsWith('/register') || target.startsWith('/quick')) return '/clipboard'
  return target
}

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
    router.push(redirectTarget())
  } catch (err) {
    // 拦截器 reject 的是 { status, message }，后端 detail 已放进 message
    error.value = err.message || '登录失败，请检查用户名和密码'
  } finally {
    loading.value = false
  }
}

// ---------- 快速访问：输入「用户名@访问码」直接进入 ----------
const fullCode = ref('')
const quickLoading = ref(false)
const quickError = ref('')

const handleQuick = async () => {
  const value = fullCode.value.trim()
  const at = value.indexOf('@')
  if (at <= 0 || at === value.length - 1 || value.indexOf('@', at + 1) !== -1) {
    quickError.value = '请按「用户名@访问码」的格式输入'
    return
  }
  try {
    quickLoading.value = true
    quickError.value = ''
    await quickStore.login(value)
    router.push('/quick')
  } catch (err) {
    quickError.value = err.message || '访问码无效或已失效'
  } finally {
    quickLoading.value = false
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

    <div class="divider"><span>或</span></div>

    <form class="quick-form" @submit.prevent="handleQuick">
      <label class="field">
        <span class="field-label">快速访问码</span>
        <span class="quick-row">
          <input
            v-model="fullCode"
            class="input input-lg mono"
            type="text"
            autocomplete="off"
            autocapitalize="off"
            spellcheck="false"
            placeholder="用户名@访问码"
            maxlength="200"
            :disabled="quickLoading"
          />
          <button type="submit" class="btn btn-secondary btn-lg" :disabled="quickLoading">
            <LoaderCircle v-if="quickLoading" class="spin" />
            <KeyRound v-else />
            进入
          </button>
        </span>
        <span class="field-hint">免登录查看和修改该访问码下的文本、下载其中的文件</span>
      </label>

      <div v-if="quickError" class="alert alert-danger" role="alert">
        <CircleAlert />
        <span>{{ quickError }}</span>
      </div>
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

.divider {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin: var(--space-6) 0;
  font-size: var(--text-xs);
  color: var(--color-text-tertiary);
}

.divider::before,
.divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--color-border);
}

.quick-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.quick-row {
  display: flex;
  gap: var(--space-2);
}

.quick-row .input {
  flex: 1;
  min-width: 0;
}

.quick-row .btn {
  flex-shrink: 0;
}

.auth-switch {
  margin-top: var(--space-6);
  padding-top: var(--space-6);
  border-top: 1px solid var(--color-border);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}
</style>
