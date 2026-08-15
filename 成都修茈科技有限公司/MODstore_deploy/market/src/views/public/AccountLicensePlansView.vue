<template>
  <main class="license-page">
    <header class="license-header">
      <p class="eyebrow">XCAGI 账号授权</p>
      <h1>选择桌面端账号授权</h1>
      <p>这里购买的是 XCAGI 桌面端使用权。VIP / SVIP 是 AI 额度会员，不代替账号授权。</p>
    </header>

    <div v-if="errorMessage" class="error" role="alert">{{ errorMessage }}</div>
    <div v-if="loading" class="loading">正在加载授权方案…</div>
    <section v-else class="license-grid" aria-label="XCAGI 账号授权方案">
      <article
        v-for="plan in plans"
        :key="plan.id"
        class="license-card"
        :class="{ 'license-card--requested': requestedPlanId === plan.id }"
      >
        <div class="card-top">
          <span class="badge">{{ plan.badge || '账号授权' }}</span>
          <h2>{{ plan.name }}</h2>
          <p class="price"><small>¥</small>{{ Number(plan.price || 0).toLocaleString('zh-CN') }}</p>
          <p class="description">{{ plan.description }}</p>
        </div>
        <ul>
          <li v-for="feature in plan.features || []" :key="feature">{{ feature }}</li>
        </ul>
        <button :disabled="checkingOut" @click="buy(plan)">
          {{ checkingOutId === plan.id ? '正在创建订单…' : (plan.license_type === 'trial' ? '开通 30 天试用' : '购买永久授权') }}
        </button>
      </article>
    </section>

    <aside class="flow-note">
      <strong>购买后怎么做？</strong>
      <span>支付成功 → 账号授权生效 → 回到 XCAGI 桌面端 → 使用刚注册的账号登录。</span>
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
const checkingOutId = ref('')
const errorMessage = ref('')
const requestedPlanId = computed(() => String(Array.isArray(route.query.plan) ? route.query.plan[0] : route.query.plan || ''))

onMounted(async () => {
  try {
    const result = await api.paymentAccountPlans()
    plans.value = Array.isArray(result?.plans) ? result.plans : []
  } catch (error) {
    errorMessage.value = `加载账号授权失败：${(error as Error)?.message || String(error)}`
  } finally {
    loading.value = false
  }
})

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
    const result = await api.paymentCheckout({ plan_id: plan.id })
    if (!result.ok) {
      errorMessage.value = result.message || '创建账号授权订单失败'
    } else if (result.type === 'page' || result.type === 'wap') {
      window.location.assign(String(result.redirect_url))
    } else if (result.type === 'precreate' || result.type === 'wechat_native') {
      await router.push({ name: 'checkout', params: { orderId: result.order_id } })
    } else {
      errorMessage.value = '支付服务返回了未知类型，请稍后重试'
    }
  } catch (error) {
    errorMessage.value = `创建账号授权订单失败：${(error as Error)?.message || String(error)}`
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
