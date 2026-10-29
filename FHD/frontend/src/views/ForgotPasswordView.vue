<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError } from '@/api'
import { authApi } from '@/api/auth'
import ConnectionRecovery from '@/components/login/ConnectionRecovery.vue'

const route = useRoute()
const router = useRouter()

const step = ref<1 | 2>(1)
const email = ref('')
const code = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const loading = ref(false)
const errorMessage = ref('')
const infoMessage = ref('')
const cooldown = ref(0)
const sentEmail = ref('')
const emailInput = ref<HTMLInputElement | null>(null)
let tick: ReturnType<typeof setInterval> | null = null
let redirectTimer: ReturnType<typeof setTimeout> | null = null

const loginBackRoute = computed(() => ({
  name: 'login' as const,
  query: route.query,
}))

const canReset = computed(
  () => code.value.trim().length >= 4 && newPassword.value.length >= 6 && newPassword.value === confirmPassword.value,
)
const passwordMismatch = computed(() => confirmPassword.value.length > 0 && newPassword.value !== confirmPassword.value)
const validationMessage = computed(() => passwordMismatch.value ? '两次输入的密码不一致，请重新核对。'
  : newPassword.value.length > 0 && newPassword.value.length < 6 ? '新密码至少需要 6 位。'
    : code.value.trim().length > 0 && code.value.trim().length < 4 ? '请输入完整的邮箱验证码。' : '')
const emailCooldown = computed(() => sentEmail.value === email.value.trim().toLowerCase() ? cooldown.value : 0)

onBeforeUnmount(() => {
  if (tick) clearInterval(tick)
  if (redirectTimer) clearTimeout(redirectTimer)
})

async function editEmail() {
  if (loading.value) return
  step.value = 1
  code.value = ''; newPassword.value = ''; confirmPassword.value = ''
  errorMessage.value = ''; infoMessage.value = ''
  await nextTick()
  emailInput.value?.focus()
}

function startCooldown(sec: number) {
  cooldown.value = sec
  if (tick) clearInterval(tick)
  tick = setInterval(() => {
    cooldown.value -= 1
    if (cooldown.value <= 0 && tick) {
      clearInterval(tick)
      tick = null
    }
  }, 1000)
}

async function sendCode() {
  if (loading.value || emailCooldown.value > 0) return
  const em = email.value.trim().toLowerCase()
  if (!em || !em.includes('@')) {
    errorMessage.value = '请填写有效邮箱'
    return
  }
  loading.value = true
  errorMessage.value = ''
  infoMessage.value = ''
  try {
    const res = await authApi.sendForgotPasswordCode(em)
    const raw = res as unknown as Record<string, unknown>
    infoMessage.value = (typeof raw.message === 'string' && raw.message) || '若该邮箱已注册，将收到验证码'
    step.value = 2
    sentEmail.value = em
    startCooldown(60)
  } catch (error: unknown) {
    if (error instanceof ApiError) {
      const d = error.data as Record<string, unknown> | undefined
      const errObj = d?.error as Record<string, unknown> | undefined
      errorMessage.value =
        (typeof d?.message === 'string' && d.message) ||
        (typeof errObj?.message === 'string' && (errObj.message as string)) ||
        error.message
    } else {
      errorMessage.value = '验证码发送失败。请先检查连接，再点击获取验证码重试；邮箱填写错误可直接修改。'
    }
  } finally {
    loading.value = false
  }
}

async function resetPassword() {
  if (loading.value) return
  if (newPassword.value !== confirmPassword.value) {
    errorMessage.value = '两次输入的密码不一致'
    return
  }
  if (!canReset.value) return

  loading.value = true
  errorMessage.value = ''
  try {
    await authApi.resetForgotPassword(email.value.trim().toLowerCase(), code.value.trim(), newPassword.value)
    infoMessage.value = '密码已重置，正在返回登录…'
    redirectTimer = setTimeout(() => router.push(loginBackRoute.value), 1200)
  } catch (error: unknown) {
    if (error instanceof ApiError) {
      const d = error.data as Record<string, unknown> | undefined
      const errObj = d?.error as Record<string, unknown> | undefined
      errorMessage.value =
        (typeof d?.message === 'string' && d.message) ||
        (typeof errObj?.message === 'string' && (errObj.message as string)) ||
        error.message
    } else {
      errorMessage.value = '重置失败，请检查验证码或稍后重试'
    }
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="login-view" aria-label="忘记密码">
    <section class="login-panel" aria-labelledby="forgot-password-title">
      <router-link class="login-register-corner" :to="loginBackRoute"> 登录 </router-link>

      <h1 id="forgot-password-title" class="login-heading">忘记密码</h1>
      <p class="page-hint">输入注册邮箱，收到验证码后设置新密码。请检查收件箱和垃圾邮件；未收到时可重发或修改邮箱。</p>

      <form v-if="step === 1" class="login-form" @submit.prevent="sendCode">
        <div class="login-field-line">
          <input ref="emailInput" v-model="email" type="email" name="email" aria-label="注册邮箱" autocomplete="email" placeholder="注册邮箱" :disabled="loading" autofocus />
        </div>
        <p v-if="errorMessage" class="login-error" role="alert">{{ errorMessage }}</p>
        <p v-if="infoMessage" class="login-success" role="status">{{ infoMessage }}</p>
        <button class="login-submit" type="submit" :disabled="loading || !email.trim() || emailCooldown > 0">
          <span>{{ loading ? '发送中...' : emailCooldown > 0 ? `${emailCooldown}s 后可重发` : '获取验证码' }}</span>
          <i class="fa fa-long-arrow-right" aria-hidden="true"></i>
        </button>
      </form>

      <form v-else class="login-form" @submit.prevent="resetPassword">
        <div class="login-field-line">
          <input v-model="email" type="email" aria-label="接收验证码的邮箱" disabled />
        </div>
        <button type="button" class="btn-edit-email" :disabled="loading" @click="editEmail">修改邮箱</button>
        <div class="login-field-line code-row">
          <input v-model="code" type="text" maxlength="8" aria-label="邮箱验证码" aria-describedby="password-validation" autocomplete="one-time-code" placeholder="邮箱验证码" :disabled="loading" />
          <button type="button" class="btn-resend" :disabled="loading || cooldown > 0" @click="sendCode">
            {{ cooldown > 0 ? `${cooldown}s` : '重发' }}
          </button>
        </div>
        <div class="login-field-line">
          <input v-model="newPassword" type="password" aria-label="新密码" aria-describedby="password-validation" :aria-invalid="newPassword.length > 0 && newPassword.length < 6" autocomplete="new-password" placeholder="新密码（至少 6 位）" :disabled="loading" />
        </div>
        <div class="login-field-line">
          <input v-model="confirmPassword" type="password" aria-label="确认新密码" aria-describedby="password-validation" :aria-invalid="passwordMismatch" autocomplete="new-password" placeholder="确认新密码" :disabled="loading" />
        </div>
        <p id="password-validation" role="status" :class="{ 'login-error': validationMessage }">{{ validationMessage }}</p>
        <p v-if="errorMessage" class="login-error" role="alert">{{ errorMessage }}</p>
        <p v-if="infoMessage" class="login-success" role="status">{{ infoMessage }}</p>
        <button class="login-submit" type="submit" :disabled="loading || !canReset">
          <span>{{ loading ? '提交中...' : '重置密码' }}</span>
          <i class="fa fa-long-arrow-right" aria-hidden="true"></i>
        </button>
      </form>

      <ConnectionRecovery v-if="errorMessage" :code="step === 1 ? 'AUTH_SEND_CODE' : 'AUTH_PASSWORD_RESET'" />

      <p class="page-footer-link">
        <router-link :to="{ name: 'login-forgot-account', query: route.query }">忘记账号</router-link>
        ·
        <router-link :to="loginBackRoute">返回登录</router-link>
      </p>
    </section>
  </main>
</template>

<style scoped>
.login-view {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 40px 16px;
  background: #f3f4f7;
}

.login-panel {
  position: relative;
  width: min(460px, 100%);
  padding: 48px 40px 32px;
  background: #fff;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.login-register-corner {
  position: absolute;
  top: 0;
  right: 0;
  width: 72px;
  height: 72px;
  display: flex;
  align-items: flex-start;
  justify-content: flex-end;
  padding: 10px 12px 0 0;
  font-size: 13px;
  color: #0052d9;
  text-decoration: none;
  background: linear-gradient(225deg, #e8f3ff 0%, #e8f3ff 48%, transparent 48%);
}

.login-heading {
  margin: 0 0 12px;
  padding-bottom: 14px;
  border-bottom: 1px solid #e6e9ef;
  font-size: 16px;
  font-weight: 500;
  color: #0052d9;
  text-align: center;
}

.page-hint {
  margin: 0 0 24px;
  font-size: 12px;
  line-height: 1.6;
  color: #888;
  text-align: center;
}

.login-field-line {
  border-bottom: 1px solid #dcdfe6;
}

.login-field-line input {
  width: 100%;
  height: 48px;
  border: 0;
  outline: none;
  font-size: 14px;
}

.code-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.code-row input {
  flex: 1;
}

.btn-resend, .btn-edit-email {
  flex-shrink: 0;
  border: 1px solid #0052d9;
  background: #fff;
  color: #0052d9;
  font-size: 12px;
  padding: 6px 10px;
  cursor: pointer;
}

.btn-resend:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.login-error {
  margin: 12px 0 0;
  padding: 8px 10px;
  font-size: 13px;
  color: #e34d59;
  background: #fff1f0;
  border: 1px solid #ffd4d1;
}

.login-success {
  margin: 12px 0 0;
  padding: 8px 10px;
  font-size: 13px;
  color: #067945;
  background: #f0fff4;
  border: 1px solid #b7ebc6;
}

.login-submit {
  margin-top: 28px;
  width: 100%;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 18px;
  border: 0;
  background: #0052d9;
  color: #fff;
  font-size: 16px;
  cursor: pointer;
}

.login-submit:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.page-footer-link {
  margin-top: 20px;
  text-align: center;
  font-size: 13px;
}

.page-footer-link a {
  color: #0052d9;
  text-decoration: none;
}
</style>
