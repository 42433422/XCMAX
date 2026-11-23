<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { authApi } from '@/api/auth'
import modelPaymentApi, { type ModelPaymentPlan } from '@/api/modelPayment'
import { marketBaseUrl } from '@/constants/loginBranding'
import { useMarketUrls, useMarketBrowserHandoff, withQuery } from '@/composables/useMarketBrowserHandoff'

const route = useRoute()
const router = useRouter()
const plans = ref<ModelPaymentPlan[]>([])
const loading = ref(true)
const checkoutPlanId = ref<string | null>(null)
const errorMessage = ref('')
const subscription = ref<Record<string, unknown> | null>(null)
const permanentActivated = computed(() => subscription.value?.active === true && String(subscription.value.plan_id || '').startsWith('saas-permanent-'))
const customizationFrom = ref<number | null>(null)
const standard = computed(() => plans.value.find(plan => plan.id === 'saas-permanent-standard'))
const trial = computed(() => plans.value.find(plan => plan.id === 'saas-trial-30'))
const { plansUrl, marketPlanUrl } = useMarketUrls()
const { handoffError, openMarketUrl } = useMarketBrowserHandoff({
  marketPlanUrl,
  forceRefreshAll: async () => {
    const result = await authApi.getSubscriptionStatus().catch(() => null)
    if (result?.data) subscription.value = result.data
  },
})
const freeExperienceUrl = `${marketBaseUrl()}/account-plans?plan=saas-personal-free&source=xcagi-desktop`
const redirectPath = computed(() => {
  const raw = Array.isArray(route.query.redirect) ? route.query.redirect[0] : route.query.redirect
  return typeof raw === 'string' && raw.startsWith('/') && !raw.startsWith('//') ? raw : '/'
})
const formatYuan = (cents: number) => (cents / 100).toLocaleString('zh-CN', { maximumFractionDigits: 2 })

onMounted(async () => {
  document.title = 'XCAGI 购买与费用'
  try {
    const [planRes, subRes] = await Promise.all([
      modelPaymentApi.getPlans(),
      authApi.getSubscriptionStatus().catch(() => null),
    ])
    if (!planRes?.success) throw new Error('plans unavailable')
    plans.value = planRes.data?.plans || []
    customizationFrom.value = planRes.data?.commercial_terms?.customization_from_cents ?? null
    subscription.value = (subRes as { data?: Record<string, unknown> } | null)?.data || null
  } catch {
    errorMessage.value = '暂时无法加载价格，请稍后重试。'
  } finally {
    loading.value = false
  }
})

async function purchase(planId: string) {
  if (checkoutPlanId.value !== null || permanentActivated.value) return
  checkoutPlanId.value = planId
  errorMessage.value = ''
  try {
    // Authenticate before checkout: the market creates the only order and owns
    // both redirect payments and the existing QR checkout for that same order.
    await openMarketUrl(withQuery(plansUrl.value, { plan: planId, source: 'fhd' }))
    if (handoffError.value) errorMessage.value = '暂时无法前往支付，请重试或重新登录。'
  } catch {
    errorMessage.value = '暂时无法前往支付，请稍后重试。'
  } finally {
    checkoutPlanId.value = null
  }
}
</script>

<template>
  <main class="saas-pricing" aria-label="XCAGI 购买与费用">
    <section class="saas-pricing-panel">
      <h1>{{ permanentActivated ? 'XCAGI 软件已开通' : '软件一次买断，按需定制' }}</h1>
      <p v-if="permanentActivated" role="status">已开通永久使用，无需重复购买软件或体验。可返回应用继续使用。</p>
      <p class="muted">标准功能永久使用。定制按确认需求报价，AI 调用按实际用量付费。</p>
      <p v-if="subscription?.reason === 'trial'" class="saas-trial-hint">体验剩余 {{ subscription.trial_days_remaining ?? '—' }} 天</p>
      <p v-else-if="subscription?.active === false" class="saas-trial-expired" role="status">体验已结束，可购买软件继续使用企业标准功能。</p>
      <p v-if="errorMessage" class="saas-error" role="alert">{{ errorMessage }}</p>
      <p v-if="loading" class="muted">加载中…</p>
      <template v-else>
        <div class="saas-plan-grid">
          <article v-if="standard" class="saas-plan-card saas-plan-card--recommended">
            <span class="saas-badge">永久买断</span>
            <h2>{{ standard.title }}</h2>
            <p class="saas-price"><strong class="saas-price-num">¥{{ formatYuan(standard.amount_cents) }}</strong><span>一次付费</span></p>
            <p class="saas-desc">{{ standard.description }}</p>
            <button class="saas-buy-btn" :disabled="checkoutPlanId !== null || permanentActivated" @click="purchase(standard.id)">{{ permanentActivated ? '已开通永久使用' : checkoutPlanId === standard.id ? '正在前往支付…' : `立即购买 ¥${formatYuan(standard.amount_cents)}` }}</button>
          </article>
          <article class="saas-plan-card">
            <h2>业务定制</h2>
            <p class="saas-price"><strong class="saas-price-num">{{ customizationFrom === null ? '按需求报价' : `¥${formatYuan(customizationFrom)} 起` }}</strong></p>
            <p class="saas-desc">先确认需求、报价与验收内容，再下定制订单。起价不代表全部需求的总价。</p>
            <router-link class="saas-link" to="/enterprise-customer-service">咨询定制</router-link>
          </article>
          <article class="saas-plan-card">
            <h2>AI 使用费</h2>
            <p class="saas-price"><strong class="saas-price-num">按量付费</strong></p>
            <p class="saas-desc">AI 调用与软件费用分开。价格、余额和用量以模型服务页为准。</p>
            <router-link class="saas-link" to="/settings?section=model-payment">查看 AI 费用与充值</router-link>
          </article>
        </div>
        <p><a :href="freeExperienceUrl" target="_blank" rel="noopener noreferrer">免费体验</a> · 个人基础功能，不含企业业务模块。</p>
        <details v-if="trial" class="saas-test-entry" :open="route.query.plan === trial.id">
          <summary>需要验证企业功能？查看体验选项</summary>
          <p>{{ trial.title }}：¥{{ formatYuan(trial.amount_cents) }} / {{ trial.duration_days || 30 }} 天。{{ trial.description }}</p>
          <button class="saas-buy-btn saas-buy-btn--secondary" :disabled="checkoutPlanId !== null || permanentActivated" @click="purchase(trial.id)">{{ permanentActivated ? '已开通永久使用' : checkoutPlanId === trial.id ? '正在前往支付…' : '购买体验' }}</button>
        </details>
      </template>
      <button class="saas-back-link" @click="router.replace(redirectPath)">返回应用</button>
    </section>
  </main>
</template>

<style scoped>
.saas-pricing { min-height: 100vh; display: grid; place-items: center; padding: 32px 16px; background: #f3f4f7; }
.saas-pricing-panel { width: min(1000px, 100%); background: #fff; padding: 32px; box-sizing: border-box; border-radius: 16px; }
.saas-plan-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin: 24px 0; }
.saas-plan-card { display: flex; flex-direction: column; border: 1px solid #e5e7eb; border-radius: 12px; padding: 20px; }
.saas-plan-card--recommended { border-color: #2563eb; }
.saas-badge { align-self: flex-start; font-size: 12px; background: #eaf1ff; color: #245cbe; padding: 4px 8px; border-radius: 6px; }
.saas-price { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.saas-price-num { font-size: 28px; }
.saas-desc, .muted { color: #4b5563; line-height: 1.7; }
.saas-desc { flex: 1; }
.saas-buy-btn, .saas-link { display: block; text-align: center; padding: 12px 16px; background: #2563eb; color: #fff; border: 0; border-radius: 8px; cursor: pointer; text-decoration: none; font: inherit; }
.saas-link, .saas-buy-btn--secondary { background: #eef3fc; color: #245cbe; }
.saas-buy-btn:disabled { opacity: .6; cursor: wait; }
.saas-trial-hint { color: #047857; }
.saas-trial-expired, .saas-error { color: #b91c1c; }
.saas-test-entry { padding: 16px 0; border-top: 1px solid #e5e7eb; }
.saas-test-entry summary { cursor: pointer; }
.saas-back-link { margin-top: 24px; background: none; border: 0; color: #2563eb; cursor: pointer; text-decoration: underline; }
</style>
