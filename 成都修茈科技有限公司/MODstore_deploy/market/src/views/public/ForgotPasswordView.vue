<template>
  <div class="auth-page">
    <div class="auth-card">
      <h2>忘记密码</h2>
      <div v-if="msg" class="flash flash-ok">{{ msg }}</div>
      <div v-if="err" class="flash flash-err">{{ err }}</div>

      <div v-if="step === 1" class="form-block">
        <div class="form-group">
          <label>注册邮箱</label>
          <input v-model="email" type="email" class="input" required autocomplete="email" />
        </div>
        <button type="button" class="btn btn-primary-solid btn-block" :disabled="sending || countdown > 0" @click="sendCode">
          {{ countdown > 0 ? `${countdown}s 后可重发` : sending ? '发送中…' : '发送验证码' }}
        </button>
      </div>

      <div v-else class="form-block">
        <div class="form-group">
          <label>验证码</label>
          <input v-model="code" class="input" maxlength="16" autocomplete="one-time-code" />
        </div>
        <div class="form-group">
          <label>新密码（至少 6 位）</label>
          <input v-model="newPassword" type="password" class="input" minlength="6" autocomplete="new-password" />
        </div>
        <div class="form-group">
          <label>确认新密码</label>
          <input v-model="confirmPassword" type="password" class="input" minlength="6" autocomplete="new-password" />
        </div>
        <button type="button" class="btn btn-primary-solid btn-block" :disabled="!canReset || resetting" @click="resetPw">
          {{ resetting ? '提交中…' : '重置密码' }}
        </button>
      </div>

      <p class="auth-footer">
        <router-link to="/login" class="link">返回登录</router-link>
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api'

const router = useRouter()
const step = ref(1)
const email = ref('')
const code = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const err = ref('')
const msg = ref('')
const sending = ref(false)
const resetting = ref(false)
const countdown = ref(0)
let timer: ReturnType<typeof setInterval> | null = null

const canReset = computed(
  () =>
    code.value.trim().length >= 4 &&
    newPassword.value.length >= 6 &&
    newPassword.value === confirmPassword.value,
)

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})

function startCooldown(sec: number) {
  countdown.value = sec
  if (timer) clearInterval(timer)
  timer = setInterval(() => {
    countdown.value -= 1
    if (countdown.value <= 0) {
      if (timer) clearInterval(timer)
      timer = null
    }
  }, 1000)
}

async function sendCode() {
  err.value = ''
  msg.value = ''
  const em = email.value.trim().toLowerCase()
  if (!em || !em.includes('@')) {
    err.value = '请填写有效邮箱'
    return
  }
  sending.value = true
  try {
    const res = await api.sendResetPasswordCode(em)
    msg.value = res.message || '若邮箱已注册，将收到验证码'
    step.value = 2
    startCooldown(60)
  } catch (e) {
    err.value = (e as Error)?.message || String(e)
  } finally {
    sending.value = false
  }
}

async function resetPw() {
  err.value = ''
  msg.value = ''
  if (!canReset.value) return
  resetting.value = true
  try {
    await api.resetPassword(email.value.trim().toLowerCase(), code.value.trim(), newPassword.value)
    msg.value = '密码已重置，请使用新密码登录'
    setTimeout(() => router.replace('/login'), 1200)
  } catch (e) {
    err.value = (e as Error)?.message || String(e)
  } finally {
    resetting.value = false
  }
}
</script>

<style scoped>
.auth-page {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 70vh;
  padding: 24px;
  background: #0a0a0a;
  color: #fff;
}
.auth-card {
  width: 100%;
  max-width: 400px;
  background: #141414;
  border-radius: 12px;
  padding: 28px;
  border: 1px solid #2a2a2a;
}
h2 {
  margin-bottom: 20px;
  font-size: 1.35rem;
}
.form-group {
  margin-bottom: 16px;
}
.form-group label {
  display: block;
  margin-bottom: 6px;
  font-size: 0.9rem;
  color: #a1a1aa;
}
.input {
  width: 100%;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid #3f3f46;
  background: #0a0a0a;
  color: #fff;
  box-sizing: border-box;
}
.btn-block {
  width: 100%;
  margin-top: 8px;
}
.btn-primary-solid {
  padding: 12px;
  border: none;
  border-radius: 8px;
  background: #6366f1;
  color: #fff;
  font-weight: 600;
  cursor: pointer;
}
.btn-primary-solid:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.flash {
  padding: 10px 12px;
  border-radius: 8px;
  margin-bottom: 14px;
  font-size: 0.9rem;
}
.flash-err {
  background: rgba(239, 68, 68, 0.15);
  color: #fca5a5;
}
.flash-ok {
  background: rgba(34, 197, 94, 0.15);
  color: #86efac;
}
.auth-footer {
  margin-top: 20px;
  text-align: center;
  font-size: 0.9rem;
  color: #71717a;
}
.link {
  color: #a5b4fc;
  text-decoration: none;
}
.link:hover {
  text-decoration: underline;
}
</style>
