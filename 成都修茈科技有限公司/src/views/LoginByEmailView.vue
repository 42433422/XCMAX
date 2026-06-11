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
import { useRouter } from 'vue-router'
import { api } from '../api'

const router = useRouter()
const email = ref('')
const code = ref('')
const err = ref('')
const loading = ref(false)
const sent = ref(false)
const codeSent = ref(false)
const countdown = ref(0)

let timer = null

onMounted(() => {
  const storedEmail = sessionStorage.getItem('login_email')
  if (storedEmail) email.value = storedEmail
})

function startCountdown() {
  countdown.value = 60
  if (timer) clearInterval(timer)
  timer = setInterval(() => {
    countdown.value--
    if (countdown.value <= 0) clearInterval(timer)
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
  } catch (e) {
    err.value = e.message
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
    const res = await api.loginWithCode(email.value, code.value)
    localStorage.setItem('modstore_token', res.token)
    window.location.href = '/'
  } catch (e) {
    err.value = e.message
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-page {
  min-height: 80vh;
  display: flex;
  align-items: center;
  justify-content: center;
}

.auth-card {
  background: #111111;
  border: 0.5px solid rgba(255,255,255,0.1);
  border-radius: 12px;
  padding: 32px;
  width: 100%;
  max-width: 400px;
}

.auth-card h2 {
  font-size: 20px;
  margin-bottom: 24px;
  text-align: center;
}

.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  font-size: 13px;
  color: rgba(255,255,255,0.5);
  margin-bottom: 6px;
}

.input {
  width: 100%;
  padding: 10px 12px;
  border: 0.5px solid rgba(255,255,255,0.15);
  border-radius: 8px;
  font-size: 14px;
  outline: none;
  background: rgba(255,255,255,0.03);
  color: #ffffff;
}

.input:focus {
  border-color: rgba(255,255,255,0.3);
}

.input:disabled {
  opacity: 0.5;
}

.btn-block {
  display: block;
  width: 100%;
  text-align: center;
}

.btn-primary-solid {
  background: #ffffff;
  color: #0a0a0a;
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
  color: rgba(255,255,255,0.5);
  cursor: pointer;
  font-size: 13px;
  padding: 4px 0;
  margin-bottom: 8px;
}

.btn-text:hover {
  color: #ffffff;
}

.countdown {
  font-size: 12px;
  color: rgba(255,255,255,0.3);
  text-align: center;
  margin-bottom: 8px;
}

.auth-footer {
  text-align: center;
  margin-top: 20px;
  font-size: 14px;
  color: rgba(255,255,255,0.4);
}

.link {
  color: #60a5fa;
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
  background: rgba(74,222,128,0.1);
  color: #4ade80;
}

.flash-err {
  background: rgba(255,80,80,0.1);
  color: #ff6b6b;
}
</style>
