<template>
  <div class="auth-page">
    <div class="auth-card">
      <h2>邮箱验证码登录</h2>

      <div v-if="err" class="flash flash-err">{{ err }}</div>
      <div v-if="sent" class="flash flash-ok">验证码已发送，请查收邮箱</div>

      <form v-if="!codeSent" @submit.prevent="sendCode">
        <div class="form-group">
          <label>邮箱地址</label>
          <input v-model="email" type="email" class="input" required placeholder="your@email.com" />
        </div>
        <button type="submit" class="btn btn-primary-solid btn-block" :disabled="loading">
          {{ loading ? '发送中...' : '发送验证码' }}
        </button>
      </form>

      <form v-else @submit.prevent="doLogin">
        <div class="form-group">
          <label>邮箱地址</label>
          <input v-model="email" type="email" class="input" disabled />
        </div>
        <div class="form-group">
          <label>验证码</label>
          <input v-model="code" type="text" class="input" required placeholder="6位验证码" maxlength="6" />
        </div>
        <div class="countdown" v-if="countdown > 0">{{ countdown }}s 后可重新发送</div>
        <button v-else class="btn btn-text" @click.prevent="resendCode">重新发送验证码</button>
        <button type="submit" class="btn btn-primary-solid btn-block" :disabled="loading">
          {{ loading ? '登录中...' : '登录' }}
        </button>
      </form>

      <p class="auth-footer">
        <router-link to="/login" class="link">← 返回密码登录</router-link>
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { api } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { pickRedirectFromRoute } from '@/authPaths'

const router = useRouter()
const route = useRoute()
const email = ref('')
const code = ref('')
const err = ref('')
const loading = ref(false)
const sent = ref(false)
const codeSent = ref(false)
const countdown = ref(0)
const authStore = useAuthStore()

let timer: ReturnType<typeof setInterval> | null = null

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error || '请求失败')
}

onMounted(() => {
  const storedEmail = sessionStorage.getItem('login_email')
  if (storedEmail) email.value = storedEmail
})

function startCountdown() {
  countdown.value = 60
  if (timer) clearInterval(timer)
  timer = setInterval(() => {
    countdown.value--
    if (countdown.value <= 0 && timer !== null) clearInterval(timer)
  }, 1000)
}

async function sendCode() {
  err.value = ''
  loading.value = true
  try {
    await api.sendVerificationCode(email.value)
    codeSent.value = true
    sent.value = true
    sessionStorage.setItem('login_email', email.value)
    startCountdown()
  } catch (e: unknown) {
    err.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

async function resendCode() {
  sent.value = false
  await sendCode()
}

async function doLogin() {
  err.value = ''
  loading.value = true
  try {
    await authStore.loginWithCode(email.value, code.value)
    const dest = pickRedirectFromRoute(route)
    await router.replace(dest)
  } catch (e: unknown) {
    err.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-page {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 100%;
  min-height: 0;
  box-sizing: border-box;
  padding: 0 var(--layout-pad-x, 16px) 1rem;
}

.auth-card {
  background: var(--wb-surface-elevated, #ffffff);
  border: 0.5px solid var(--wb-border-default, rgba(0, 0, 0, 0.08));
  border-radius: 12px;
  box-shadow: var(--wb-card-shadow, 0 8px 28px rgba(0, 0, 0, 0.06));
  padding: 32px;
  width: 100%;
  max-width: min(400px, 100%);
  box-sizing: border-box;
}

.auth-card h2 {
  font-size: 20px;
  margin-bottom: 24px;
  text-align: center;
  color: var(--wb-text-primary, #1d1d1f);
}

.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  font-size: 13px;
  color: var(--wb-text-muted, #86868b);
  margin-bottom: 6px;
}

.input {
  width: 100%;
  padding: 10px 12px;
  border: 0.5px solid var(--wb-border-default, rgba(0, 0, 0, 0.12));
  border-radius: 8px;
  font-size: 14px;
  outline: none;
  background: var(--wb-surface-sunken, #f5f5f7);
  color: var(--wb-text-primary, #1d1d1f);
  box-sizing: border-box;
}

.input:focus {
  border-color: var(--wb-accent-primary, #0071e3);
}

.input:disabled {
  opacity: 0.55;
}

.btn-block {
  display: block;
  width: 100%;
  text-align: center;
}

.btn-primary-solid {
  background: var(--wb-text-primary, #1d1d1f);
  color: #ffffff;
  border: none;
  padding: 12px;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  margin-top: 8px;
}

.btn-primary-solid:hover:not(:disabled) {
  opacity: 0.9;
}

.btn-primary-solid:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-text {
  background: none;
  border: none;
  color: var(--wb-text-muted, #86868b);
  cursor: pointer;
  font-size: 13px;
  padding: 4px 0;
  margin-bottom: 8px;
}

.btn-text:hover {
  color: var(--wb-text-primary, #1d1d1f);
}

.countdown {
  font-size: 12px;
  color: var(--wb-text-muted, #86868b);
  text-align: center;
  margin-bottom: 8px;
}

.auth-footer {
  text-align: center;
  margin-top: 20px;
  font-size: 14px;
  color: var(--wb-text-muted, #86868b);
}

.link {
  color: var(--wb-accent-primary, #0071e3);
  text-decoration: none;
}

.link:hover {
  text-decoration: underline;
}

.flash {
  padding: 10px 14px;
  border-radius: 8px;
  margin-bottom: 16px;
  font-size: 13px;
}

.flash-ok {
  background: rgba(52, 211, 153, 0.12);
  color: #059669;
}

.flash-err {
  background: rgba(248, 113, 113, 0.12);
  color: #dc2626;
}
</style>
