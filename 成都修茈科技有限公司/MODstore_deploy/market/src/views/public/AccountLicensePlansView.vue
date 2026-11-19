<template>
  <main class="license-page">
    <header class="license-header">
      <p class="eyebrow">XCAGI 使用方案</p>
      <h1>选择适合你的方案</h1>
      <p>个人使用版可免费开通。付费方案完成支付后即可在 XCAGI 桌面端登录使用。</p>
    </header>

    <div v-if="errorMessage" class="error" role="alert">{{ errorMessage }}</div>
    <div v-if="personalActivated" class="flow-note" role="status">个人使用版已开通，已赠送 5 元 AI 使用额度。请回到 XCAGI 桌面端登录。</div>
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
        <button :disabled="checkingOut || (personalActivated && plan.license_type === 'free')" @click="buy(plan)">
          {{ planActionLabel(plan) }}
        </button>
      </article>
    </section>

    <aside class="flow-note">
      <strong>接下来</strong>
      <span>付费方案通过支付宝完成支付。方案生效后，回到 XCAGI 桌面端登录即可。</span>
    </aside>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api'
import { useAuthStore } from '@/stores/auth'
import type { AccountLicensePlan } from '@/domain/payment/types'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const plans = ref<AccountLicensePlan[]>([])
const loading = ref(true)
const checkingOut = ref(false)
const personalActivated = ref(false)
const checkingOutId = ref('')
const errorMessage = ref('')
const requestedPlanId = computed(() => String(Array.isArray(route.query.plan) ? route.query.plan[0] : route.query.plan || ''))

onMounted(async () => {
  try {
    const result = await api.paymentAccountPlans()
    plans.value = Array.isArray(result?.plans) ? result.plans : []
  } catch {
    errorMessage.value = '暂时无法加载方案，请稍后重试。'
  } finally {
    loading.value = false
  }
})

function planActionLabel(plan: AccountLicensePlan) {
  if (plan.license_type === 'free') {
    if (personalActivated.value) return '已开通'
    return checkingOutId.value === plan.id ? '正在开通…' : '免费开通'
  }
  if (checkingOutId.value === plan.id) return '正在前往支付…'
  return plan.license_type === 'trial' ? '立即体验' : '选择此方案'
}

async function buy(plan: AccountLicensePlan) {
  if (!authStore.hasToken()) {
    await router.push({ name: 'login', query: { redirect: route.fullPath } })
    return
  }
  if (checkingOut.value) return
  checkingOut.value = true
  checkingOutId.value = plan.id
  errorMessage.value = ''
  try {
    if (plan.license_type === 'free') {
      const result = await api.activatePersonalPlan()
      personalActivated.value = result.ok
      if (!result.ok) errorMessage.value = '暂时无法开通个人使用版，请稍后重试。'
      return
    }
    const result = await api.paymentCheckout({ plan_id: plan.id })
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
    errorMessage.value = plan.license_type === 'free' ? '暂时无法开通个人使用版，请确认当前账号尚未开通其他方案。' : '暂时无法前往支付，请稍后重试。'
  } finally {
    checkingOut.value = false
    checkingOutId.value = ''
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
.error { color: #ffd3d3; background: #391a1a; }
.loading { text-align: center; color: #aeb2bb; }
</style>
