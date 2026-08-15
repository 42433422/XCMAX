<template>
  <div class="auth-page">
    <div v-if="registrationComplete" class="auth-card auth-card--success" role="status">
      <div class="success-mark" aria-hidden="true">✓</div>
      <p class="source-badge">XCAGI 桌面端</p>
      <h2>账号注册成功</h2>
      <p class="success-lead">网页与 XCAGI 桌面端共用这一个修茈市场账号。</p>
      <div class="next-step">
        <strong>下一步</strong>
        <span>选择套餐并完成支付。权益生效后，再回到 XCAGI 桌面端登录。</span>
      </div>
      <router-link :to="registrationNext" class="btn btn-primary-solid btn-block success-action">
        选择套餐
      </router-link>
    </div>
    <div v-else class="auth-card">
      <p v-if="desktopRegistration" class="source-badge">来自 XCAGI 桌面端</p>
      <h2>注册修茈市场账号</h2>
      <p v-if="desktopRegistration" class="auth-intro">
        桌面端与网页端共用同一账号。在这里完成一次注册即可。
      </p>
      <div v-if="err" class="flash flash-err">{{ err }}</div>
      <form @submit.prevent="doRegister">
        <div class="form-group">
          <label>用户名</label>
          <input class="input" v-model="username" required minlength="2" maxlength="64" autocomplete="username" />
        </div>
        <div class="form-group">
          <label>邮箱（选填）</label>
          <p class="field-hint">不填写也可注册；填写后可用于邮箱登录、验证和密码找回。</p>
          <input
            class="input"
            type="email"
            v-model="email"
            autocomplete="email"
            placeholder="name@example.com"
          />
        </div>
        <div v-if="emailTrimmed" class="form-group form-group-code">
          <label>邮箱验证码（填写邮箱后必填）</label>
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
      <p v-if="desktopRegistration" class="auth-footer">
        已有账号？请关闭本页，回到 XCAGI 桌面端登录
      </p>
      <p v-else class="auth-footer">
        已有账号？<router-link :to="loginRoute" class="link">登录</router-link>
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api'
import {
  isXcagiDesktopRegistration,
  pickRegistrationNextFromRoute,
} from '@/authPaths'

const router = useRouter()
const route = useRoute()
const username = ref('')
const email = ref('')
const verificationCode = ref('')
const password = ref('')
const loading = ref(false)
const sendCodeLoading = ref(false)
const err = ref('')
const cooldown = ref(0)
const registrationComplete = ref(false)
let tick: ReturnType<typeof setInterval> | null = null

const emailTrimmed = computed(() => email.value.trim())
const desktopRegistration = computed(() => isXcagiDesktopRegistration(route))
const registrationNext = computed(() => pickRegistrationNextFromRoute(route))
const loginRoute = computed(() => ({ name: 'login', query: route.query }))

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
    err.value = (e as Error)?.message || String(e)
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
    if (em && !code) {
      err.value = '请先点击「获取验证码」，填写邮件中的 6 位验证码'
      return
    }
    await api.register(username.value, password.value, em, em ? code : '')
    if (desktopRegistration.value) {
      registrationComplete.value = true
      return
    }
    await router.replace(registrationNext.value)
  } catch (e) {
    err.value = (e as Error)?.message || String(e)
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
  border-radius: 12px;
  border: 0.5px solid var(--wb-border-default, rgba(0, 0, 0, 0.08));
  box-shadow: var(--wb-card-shadow, 0 8px 28px rgba(0, 0, 0, 0.06));
  padding: 32px;
  width: 100%;
  max-width: min(400px, 100%);
  box-sizing: border-box;
}
.auth-card h2 {
  font-size: 22px;
  margin-bottom: 24px;
  text-align: center;
  color: var(--wb-text-primary, #1d1d1f);
}
.source-badge {
  width: fit-content;
  margin: 0 auto 10px;
  padding: 4px 10px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--wb-accent-primary, #0071e3) 10%, transparent);
  color: var(--wb-accent-primary, #0071e3);
  font-size: 12px;
  font-weight: 600;
}
.auth-intro,
.success-lead {
  margin: -10px 0 22px;
  color: var(--wb-text-muted, #6e6e73);
  font-size: 14px;
  line-height: 1.65;
  text-align: center;
}
.auth-card--success {
  text-align: center;
}
.success-mark {
  display: grid;
  place-items: center;
  width: 52px;
  height: 52px;
  margin: 0 auto 16px;
  border-radius: 50%;
  background: #e8f7ee;
  color: #18864b;
  font-size: 28px;
  font-weight: 700;
}
.auth-card--success .success-lead {
  margin-top: -8px;
}
.next-step {
  display: grid;
  gap: 6px;
  margin: 0 0 20px;
  padding: 14px 16px;
  border-radius: 10px;
  background: var(--wb-surface-sunken, rgba(0, 0, 0, 0.04));
  color: var(--wb-text-primary, #1d1d1f);
  font-size: 13px;
  line-height: 1.6;
  text-align: left;
}
.success-action {
  display: block;
  box-sizing: border-box;
  text-decoration: none;
}
.form-group { margin-bottom: 16px; }
.form-group label {
  display: block;
  font-size: 13px;
  color: var(--wb-text-muted, #86868b);
  margin-bottom: 6px;
}
.field-hint {
  font-size: 12px;
  color: var(--wb-text-muted, #86868b);
  margin: 0 0 8px;
  line-height: 1.45;
}
.code-row { display: flex; gap: 10px; align-items: stretch; }
.input-code { flex: 1; min-width: 0; }
.btn-send {
  flex-shrink: 0;
  padding: 0 14px;
  font-size: 13px;
  font-weight: 500;
  border-radius: 8px;
  border: 0.5px solid var(--wb-border-default, rgba(0, 0, 0, 0.12));
  background: var(--wb-surface-sunken, rgba(0, 0, 0, 0.04));
  color: var(--wb-text-primary, #1d1d1f);
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.15s ease, opacity 0.15s ease;
}
.btn-send:hover:not(:disabled) {
  background: var(--wb-surface-overlay, rgba(0, 0, 0, 0.06));
}
.btn-send:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.btn-block { width: 100%; }
.auth-footer {
  text-align: center;
  margin-top: 16px;
  font-size: 14px;
  color: var(--wb-text-muted, #86868b);
}
.link {
  color: var(--wb-accent-primary, #0071e3);
  font-weight: 500;
}
</style>
