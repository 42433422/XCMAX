<template>
  <main class="license-page">
    <header class="license-header">
      <p class="eyebrow">XCAGI 使用方案</p>
      <h1>选择适合你的方案</h1>
      <p>个人使用版可免费开通。付费方案完成支付后即可在 XCAGI 登录使用。</p>
    </header>

    <div v-if="errorMessage" class="error" role="alert">{{ errorMessage }}</div>
    <section v-if="personalActivated" class="flow-note allowance-panel" aria-label="个人使用版和活动赠额">
      <strong role="status">个人使用版已开通。请回到 XCAGI 登录。</strong>
      <p id="allowance-status" role="status">{{ allowance?.message || '赠额状态暂未确认，请稍后查询。' }}</p>
      <template v-if="allowance?.status === 'verification_required'">
        <p>完成当前账号邮箱验证后，可按活动规则申请 AI 赠额。验证和领取结果不影响免费方案使用。</p>
        <form v-if="accountLoaded" @submit.prevent="claimAllowance(true)">
          <label for="allowance-email">{{ accountEmail ? '当前账号邮箱' : '首次绑定邮箱' }}</label>
          <input id="allowance-email" v-model.trim="email" type="email" autocomplete="email" :readonly="!!accountEmail" :disabled="checkingOut || sendingCode" required />
          <button type="button" id="send-allowance-code" :disabled="checkingOut || sendingCode || cooldown > 0 || !email" @click="sendCode">
            {{ sendingCode ? '正在发送…' : cooldown > 0 ? `${cooldown} 秒后可重新获取` : '获取验证码' }}
          </button>
          <span v-if="codeSent" role="status">验证码发送请求已受理，请查收邮箱。</span>
          <label for="allowance-code">邮箱验证码</label>
          <input id="allowance-code" v-model.trim="verificationCode" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" maxlength="6" :disabled="checkingOut" required />
          <button type="submit" :disabled="checkingOut || sendingCode || !email || !verificationCode">{{ checkingOut ? '正在确认…' : '验证邮箱并申请赠额' }}</button>
        </form>
        <button v-else type="button" id="reload-account" :disabled="accountLoading" @click="loadAccount">{{ accountLoading ? '正在读取账号…' : '重新读取账号邮箱' }}</button>
      </template>
      <button v-else-if="allowance?.status !== 'granted' && allowance?.status !== 'already_claimed'" type="button" id="claim-allowance" :disabled="checkingOut" @click="claimAllowance()">
        {{ checkingOut ? '正在确认…' : allowance?.status === 'available' ? '领取 AI 赠额' : allowance?.status === 'pending' ? '查询入账结果' : '重新查询赠额' }}
      </button>
    </section>
    <div v-if="loading" class="loading">正在加载方案…</div>
    <section v-else class="license-grid" aria-label="XCAGI 使用方案">
      <article
        v-for="plan in plans"
        :key="plan.id"
        class="license-card"
        :class="{ 'license-card--requested': requestedPlanId === plan.id }"
      >
        <div class="card-top">
          <span class="badge">{{ plan.badge || '使用方案' }}</span>
          <h2>{{ plan.name }}</h2>
          <p v-if="plan.license_type === 'free'" class="price">免费</p>
          <p v-else class="price"><small>¥</small>{{ Number(plan.price || 0).toLocaleString('zh-CN') }}</p>
          <p class="description">{{ plan.description }}</p>
        </div>
        <ul>
          <li v-for="feature in plan.features || []" :key="feature">{{ feature }}</li>
        </ul>
        <button :disabled="checkingOut || ((accountLoading || personalActivated) && plan.license_type === 'free')" @click="buy(plan)">
          {{ planActionLabel(plan) }}
        </button>
      </article>
    </section>

    <aside class="flow-note">
      <strong>接下来</strong>
      <span>付费方案通过支付宝完成支付。方案生效后，回到 XCAGI 登录即可。</span>
    </aside>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api'
import { xcagiRegistrationSource } from '@/authPaths'
import { useAuthStore } from '@/stores/auth'
import type { AccountLicensePlan, PersonalPlanAllowance, PersonalPlanVerification } from '@/domain/payment/types'
import { asUnknownRecord } from '@/utils/typeNarrowing'
import { ACCESS_TOKEN_KEY, getAccessToken } from '@/infrastructure/storage/tokenStore'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const plans = ref<AccountLicensePlan[]>([])
const loading = ref(true)
const checkingOut = ref(false)
const activePlanId = ref('')
const personalPlan = computed(() => plans.value.find(plan => plan.license_type === 'free'))
const personalActivated = computed(() => !!personalPlan.value && activePlanId.value === personalPlan.value.id)
const allowance = ref<PersonalPlanAllowance | null>(null)
const accountEmail = ref('')
const accountLoaded = ref(false)
const accountLoading = ref(false)
const email = ref('')
const verificationCode = ref('')
const sendingCode = ref(false)
const codeSent = ref(false)
const cooldown = ref(0)
let cooldownTimer: ReturnType<typeof setInterval> | undefined
let disposed = false
let accountToken = getAccessToken()
const checkingOutId = ref('')
const errorMessage = ref('')
const requestedPlanId = computed(() => String(Array.isArray(route.query.plan) ? route.query.plan[0] : route.query.plan || ''))

onMounted(() => {
  window.addEventListener('storage', onStorage)
  void loadPlans()
  void loadAccount()
})
onUnmounted(() => {
  disposed = true
  clearInterval(cooldownTimer)
  window.removeEventListener('storage', onStorage)
})

function onStorage(event: StorageEvent) {
  if (event.key === ACCESS_TOKEN_KEY || event.key === null) syncAccountIdentity()
}

function syncAccountIdentity(): boolean {
  if (disposed || accountToken === getAccessToken()) return false
  accountToken = getAccessToken()
  activePlanId.value = accountEmail.value = email.value = verificationCode.value = ''
  allowance.value = null
  accountLoaded.value = accountLoading.value = checkingOut.value = sendingCode.value = codeSent.value = false
  checkingOutId.value = errorMessage.value = ''
  cooldown.value = 0
  clearInterval(cooldownTimer)
  void loadAccount()
  return true
}

function isCurrentRequest(token: string): boolean {
  return !disposed && !syncAccountIdentity() && token === accountToken
}

async function loadPlans() {
  try {
    const result = await api.paymentAccountPlans()
    if (disposed) return
    plans.value = Array.isArray(result?.plans) ? result.plans : []
  } catch {
    if (!disposed) errorMessage.value = '暂时无法加载方案，请稍后重试。'
  } finally {
    if (!disposed) loading.value = false
  }
}

async function loadAccount() {
  if (disposed || !authStore.hasToken() || accountLoading.value) return
  const token = accountToken
  accountLoading.value = true
  try {
    const result = await api.accountBootstrap()
    if (!isCurrentRequest(token)) return
    activePlanId.value = result.account?.active_plan_id || ''
    allowance.value = result.account?.allowance || null
    accountEmail.value = result.user?.email?.trim() || ''
    email.value = accountEmail.value
    accountLoaded.value = true
  } catch {
    if (isCurrentRequest(token)) accountLoaded.value = false
  } finally {
    if (isCurrentRequest(token)) accountLoading.value = false
  }
}

async function sendCode() {
  if (disposed || syncAccountIdentity()) return
  if (!accountLoaded.value || sendingCode.value || checkingOut.value || cooldown.value > 0 || !email.value.trim()) return
  const token = accountToken
  sendingCode.value = true
  codeSent.value = false
  errorMessage.value = ''
  try {
    const result = asUnknownRecord(await (accountEmail.value ? api.sendVerificationCode(email.value.trim()) : api.sendRegisterVerificationCode(email.value.trim())))
    if (!isCurrentRequest(token)) return
    if (result.ok === false || result.success === false) throw new Error('verification code not sent')
    codeSent.value = true
    cooldown.value = 60
    clearInterval(cooldownTimer)
    cooldownTimer = setInterval(() => { if (--cooldown.value <= 0) clearInterval(cooldownTimer) }, 1000)
  } catch {
    if (isCurrentRequest(token)) errorMessage.value = '验证码暂时无法发送，请检查邮箱后稍后重试。'
  } finally {
    if (isCurrentRequest(token)) sendingCode.value = false
  }
}

async function claimAllowance(verify = false) {
  if (disposed || syncAccountIdentity()) return
  if (!personalPlan.value || (verify && (!accountLoaded.value || !email.value.trim() || !verificationCode.value.trim()))) return
  await buy(personalPlan.value, verify ? { email: email.value.trim(), verification_code: verificationCode.value.trim() } : undefined)
}

function planActionLabel(plan: AccountLicensePlan) {
  if (plan.license_type === 'free') {
    if (personalActivated.value) return '已开通'
    return checkingOutId.value === plan.id ? '正在开通…' : '免费开通'
  }
  if (checkingOutId.value === plan.id) return '正在前往支付…'
  return plan.license_type === 'trial' ? '立即体验' : '选择此方案'
}

async function buy(plan: AccountLicensePlan, verification?: PersonalPlanVerification) {
  if (disposed || syncAccountIdentity()) return
  if (!authStore.hasToken()) {
    await router.push({ name: 'login', query: { redirect: route.fullPath, source: xcagiRegistrationSource(route) } })
    return
  }
  if (checkingOut.value) return
  const token = accountToken
  checkingOut.value = true
  checkingOutId.value = plan.id
  errorMessage.value = ''
  try {
    if (plan.license_type === 'free') {
      const result = await (verification ? api.activatePersonalPlan(verification) : api.activatePersonalPlan())
      if (!isCurrentRequest(token)) return
      if (result.ok) {
        activePlanId.value = result.active_plan_id || plan.id
        allowance.value = result.allowance || null
        verificationCode.value = ''
      } else errorMessage.value = '暂时无法确认个人使用版和赠额状态，请稍后重试。'
      return
    }
    const result = await api.paymentCheckout({ plan_id: plan.id })
    if (!isCurrentRequest(token)) return
    if (!result.ok) {
      errorMessage.value = '暂时无法前往支付，请稍后重试。'
    } else if (result.type === 'page' || result.type === 'wap') {
      window.location.assign(String(result.redirect_url))
    } else if (result.type === 'precreate' || result.type === 'wechat_native') {
      await router.push({ name: 'checkout', params: { orderId: result.order_id } })
    } else {
      errorMessage.value = '暂时无法打开支付页面，请稍后重试。'
    }
  } catch {
    if (!isCurrentRequest(token)) return
    errorMessage.value = plan.license_type === 'free'
      ? personalActivated.value ? '暂时无法确认赠额，请检查邮箱和验证码或稍后重试。免费方案仍可使用。' : '暂时无法开通个人使用版，请确认当前账号尚未开通其他方案。'
      : '暂时无法前往支付，请稍后重试。'
  } finally {
    if (isCurrentRequest(token)) {
      checkingOut.value = false
      checkingOutId.value = ''
    }
  }
}
</script>

<style scoped>
.license-page { min-height: 100vh; padding: 72px 24px; color: #f7f7f8; background: #090a0c; }
.license-header { max-width: 820px; margin: 0 auto 38px; text-align: center; }
.eyebrow { color: #74a7ff; font-weight: 700; letter-spacing: .08em; }
h1 { margin: 8px 0 14px; font-size: clamp(30px, 5vw, 48px); }
.license-header > p:last-child { color: #aeb2bb; line-height: 1.8; }
.license-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 16px; max-width: 1280px; margin: auto; }
.license-card { display: flex; flex-direction: column; padding: 24px; border: 1px solid #292d35; border-radius: 18px; background: #111318; }
.license-card--requested { outline: 2px solid #74a7ff; outline-offset: 3px; }
.badge { display: inline-block; padding: 4px 9px; color: #9ec1ff; background: #17243a; border-radius: 999px; font-size: 12px; }
h2 { min-height: 56px; margin: 14px 0 4px; font-size: 20px; }
.price { margin: 8px 0 16px; font-size: 34px; font-weight: 750; }
.price small { margin-right: 3px; font-size: 16px; }
.description, li { color: #b8bbc2; line-height: 1.65; }
ul { flex: 1; padding-left: 20px; }
button { width: 100%; padding: 12px; color: #fff; background: #246ee9; border: 0; border-radius: 10px; font-weight: 700; cursor: pointer; }
button:disabled { opacity: .55; cursor: wait; }
.flow-note, .error, .loading { max-width: 900px; margin: 26px auto 0; padding: 16px 18px; border-radius: 12px; }
.flow-note { display: grid; gap: 6px; color: #cbd0d8; background: #121820; border: 1px solid #273447; }
.allowance-panel { margin-bottom: 26px; }
.allowance-panel p { margin: 4px 0; line-height: 1.65; }
.allowance-panel form { display: grid; gap: 10px; max-width: 480px; }
.allowance-panel input { padding: 12px; border: 1px solid #485263; border-radius: 8px; color: #f7f7f8; background: #111318; }
.allowance-panel input[readonly] { color: #b8bbc2; }
.allowance-panel > button { max-width: 480px; }
.error { color: #ffd3d3; background: #391a1a; }
.loading { text-align: center; color: #aeb2bb; }
</style>
