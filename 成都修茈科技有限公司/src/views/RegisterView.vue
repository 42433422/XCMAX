<template>
  <div class="auth-page">
    <div class="auth-card">
      <h2>注册</h2>
      <div v-if="err" class="flash flash-err">{{ err }}</div>
      <form @submit.prevent="doRegister">
        <div class="form-group">
          <label>用户名</label>
          <input class="input" v-model="username" required minlength="2" maxlength="64" autocomplete="username" />
        </div>
        <div class="form-group">
          <label>邮箱（必填）</label>
          <p class="field-hint">用于登录与找回，请先填写邮箱再获取验证码。</p>
          <input
            class="input"
            type="email"
            v-model="email"
            required
            autocomplete="email"
            placeholder="name@example.com"
          />
        </div>
        <div class="form-group form-group-code">
          <label>邮箱验证码</label>
          <div class="code-row">
            <input
              class="input input-code"
              v-model="verificationCode"
              required
              maxlength="8"
              autocomplete="one-time-code"
              placeholder="6 位数字"
            />
            <button
              type="button"
              class="btn btn-send"
              :disabled="sendDisabled"
              :aria-busy="sendCodeLoading"
              @click="sendCode"
            >
              {{ sendLabel }}
            </button>
          </div>
        </div>
        <div class="form-group">
          <label>密码</label>
          <input class="input" type="password" v-model="password" required minlength="6" autocomplete="new-password" />
        </div>
        <button type="submit" class="btn btn-primary-solid btn-block" :disabled="loading">
          {{ loading ? '注册中...' : '注册' }}
        </button>
      </form>
      <p class="auth-footer">
        已有账号？<router-link to="/login" class="link">登录</router-link>
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'

const router = useRouter()
const username = ref('')
const email = ref('')
const verificationCode = ref('')
const password = ref('')
const loading = ref(false)
const sendCodeLoading = ref(false)
const err = ref('')
const cooldown = ref(0)
let tick = null

const emailTrimmed = computed(() => email.value.trim())

const sendDisabled = computed(
  () => cooldown.value > 0 || loading.value || sendCodeLoading.value || !emailTrimmed.value,
)

const sendLabel = computed(() => {
  if (sendCodeLoading.value) return '发送中…'
  if (cooldown.value > 0) return `${cooldown.value}s 后可重新获取`
  return '获取验证码'
})

function startCooldown(sec = 60) {
  cooldown.value = sec
  tick = setInterval(() => {
    cooldown.value -= 1
    if (cooldown.value <= 0 && tick) {
      clearInterval(tick)
      tick = null
    }
  }, 1000)
}

onUnmounted(() => {
  if (tick) clearInterval(tick)
})

async function sendCode() {
  err.value = ''
  if (!emailTrimmed.value) {
    err.value = '请先填写邮箱'
    return
  }
  if (sendCodeLoading.value) return
  sendCodeLoading.value = true
  try {
    await api.sendRegisterVerificationCode(emailTrimmed.value)
    startCooldown(60)
  } catch (e) {
    err.value = e.message
  } finally {
    sendCodeLoading.value = false
  }
}

async function doRegister() {
  loading.value = true
  err.value = ''
  try {
    const em = emailTrimmed.value
    const code = verificationCode.value.trim()
    if (!em) {
      err.value = '请填写邮箱'
      return
    }
    if (!code) {
      err.value = '请先点击「获取验证码」，填写邮件中的 6 位验证码'
      return
    }
    const res = await api.register(username.value, password.value, em, code)
    localStorage.setItem('modstore_token', res.token)
    await router.push('/')
  } catch (e) {
    err.value = e.message
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-page { display: flex; justify-content: center; padding-top: 60px; }
.auth-card { background: #111111; border-radius: 12px; border: 0.5px solid rgba(255,255,255,0.1); padding: 32px; width: 100%; max-width: 400px; }
.auth-card h2 { font-size: 22px; margin-bottom: 24px; text-align: center; color: #ffffff; }
.form-group { margin-bottom: 16px; }
.form-group label { display: block; font-size: 13px; color: rgba(255,255,255,0.5); margin-bottom: 6px; }
.field-hint { font-size: 12px; color: rgba(255,255,255,0.35); margin: 0 0 8px; line-height: 1.45; }
.code-row { display: flex; gap: 10px; align-items: stretch; }
.input-code { flex: 1; min-width: 0; }
.btn-send {
  flex-shrink: 0;
  padding: 0 14px;
  font-size: 13px;
  font-weight: 500;
  border-radius: 8px;
  border: 0.5px solid rgba(255,255,255,0.2);
  background: rgba(255,255,255,0.08);
  color: rgba(255,255,255,0.85);
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.15s ease, opacity 0.15s ease;
}
.btn-send:hover:not(:disabled) {
  background: rgba(255,255,255,0.12);
}
.btn-send:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.btn-block { width: 100%; }
.auth-footer { text-align: center; margin-top: 16px; font-size: 14px; color: rgba(255,255,255,0.5); }
.link { color: #ffffff; font-weight: 500; }
</style>
