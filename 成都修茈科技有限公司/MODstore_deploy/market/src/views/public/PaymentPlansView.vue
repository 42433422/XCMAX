<template>
  <div class="plans-page">
    <Teleport to="body">
      <div
        v-if="svipEntryRevealOverlay"
        class="svip-reveal-overlay"
        role="dialog"
        aria-label="欢迎加入超级会员"
      >
        <div class="svip-reveal-shimmer" />
        <div class="svip-reveal-content">
          <p class="svip-reveal-star" aria-hidden="true">✦</p>
          <h2 class="svip-reveal-h2">欢迎加入超级会员</h2>
          <p class="svip-reveal-p">更多进阶线已开放，下方为你展示可选档位</p>
        </div>
      </div>
    </Teleport>
    <div class="page-header">
      <h1 class="page-title">会员购买</h1>
      <p v-if="hasSvipTier" class="page-desc">
        可在此继续升级、查看各档权益
      </p>
    </div>

    <div v-if="errorMsg" ref="errorBannerRef" class="error-msg error-msg--prominent" role="alert">{{ errorMsg }}</div>

    <div v-if="loading" class="loading">加载中...</div>

    <div v-else class="plans-grid">
      <div
        v-for="plan in visiblePlans"
        :key="plan.id"
        class="plan-card"
        :class="[
          'plan-card',
          isCurrent(plan) ? 'plan-card--current' : '',
          isBelowMyPlan(plan) ? 'plan-card--lower-tier' : '',
          `plan-card--${tierOf(plan)}`,
          hideSvipLadderTiers && isSvipLadderPlan(plan) ? 'plan-card--pre-reveal' : '',
          svipLadderRevealPop && isSvipLadderPlan(plan) ? 'plan-card--reveal-pop' : '',
        ]"
        :style="
          svipLadderRevealPop && isSvipLadderPlan(plan) ? { animationDelay: svipLadderStaggerDelay(plan) } : {}
        "
      >
        <div class="plan-header">
          <div class="plan-title-row">
            <h2 class="plan-name">{{ plan.name }}</h2>
            <span v-if="isCurrent(plan)" class="plan-badge plan-badge--current">当前等级</span>
            <span
              v-else-if="isBelowMyPlan(plan)"
              class="plan-badge plan-badge--superseded"
            >已高于此档</span>
          </div>
          <div class="plan-price">
            <span class="price-symbol">¥</span>
            <span class="price-value">{{ plan.price.toFixed(2) }}</span>
          </div>
          <p class="plan-desc">{{ plan.description }}</p>
        </div>

        <ul class="plan-features">
          <li v-for="(feature, i) in plan.features" :key="i">{{ feature }}</li>
        </ul>

        <button
          class="btn btn-primary"
          :disabled="checkingOut || isCurrent(plan) || isBelowMyPlan(plan)"
          @click="handleBuy(plan)"
        >
          <span v-if="checkingOut && checkingOutId === plan.id">处理中...</span>
          <span v-else-if="isCurrent(plan)">已是此等级</span>
          <span v-else-if="isBelowMyPlan(plan)">不可购买更低档</span>
          <span v-else>立即购买</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/infrastructure/http/client'

const SVIP_LADDER_REVEAL_KEY = 'modstore_svip_ladder_reveal'

const router = useRouter()
const authStore = useAuthStore()
const plans = ref([])
const myPlan = ref(null)
const loading = ref(true)
const checkingOut = ref(false)
const checkingOutId = ref('')
const errorMsg = ref('')
const errorBannerRef = ref(null)

const svipEntryRevealOverlay = ref(false)
const hideSvipLadderTiers = ref(false)
const svipLadderRevealPop = ref(false)

watch(errorMsg, async (m) => {
  if (!m) return
  await nextTick()
  errorBannerRef.value?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
})

// 任一 SVIP 档（含 svip 入门档）算"已是 SVIP"用户；SVIP2~8 仅在此条件下出现在卡片网格里
const SVIP_TIER_IDS = new Set([
  'plan_enterprise',
  'plan_svip2', 'plan_svip3', 'plan_svip4',
  'plan_svip5', 'plan_svip6', 'plan_svip7', 'plan_svip8',
])

const hasSvipTier = computed(() => {
  const id = String(myPlan.value?.id || '').trim()
  return SVIP_TIER_IDS.has(id)
})

/** 会员线序：数值越大档越高，用于禁止「已高等级后购买低等级」 */
const MEMBERSHIP_TIER_ORDER = {
  plan_basic: 0,
  plan_pro: 1,
  plan_enterprise: 2,
  plan_svip2: 3,
  plan_svip3: 4,
  plan_svip4: 5,
  plan_svip5: 6,
  plan_svip6: 7,
  plan_svip7: 8,
  plan_svip8: 9,
}

function planTierOrder(planId) {
  const id = String(planId || '').trim()
  return Object.prototype.hasOwnProperty.call(MEMBERSHIP_TIER_ORDER, id)
    ? MEMBERSHIP_TIER_ORDER[id]
    : -1
}

const myPlanTierOrder = computed(() => planTierOrder(myPlan.value?.id))

/**
 * 当前用户已拥有比该套餐更高的有效档位，不应再购买这一档（降级/重复买低档）。
 * 无会员或 current 为未知 id 时不过滤，避免误伤。
 */
function isBelowMyPlan(plan) {
  if (!plan?.id || isCurrent(plan)) return false
  const cur = myPlanTierOrder.value
  const t = planTierOrder(plan.id)
  if (cur < 0 || t < 0) return false
  return t < cur
}

function isSvipLadderPlan(plan) {
  return /^plan_svip[2-8]$/.test(String(plan?.id || ''))
}

/** SVIP2→0 … SVIP8→6s */
function svipLadderStaggerDelay(plan) {
  const m = String(plan?.id || '').match(/^plan_svip(\d+)$/)
  if (!m) return '0s'
  const n = Math.min(8, Math.max(2, parseInt(m[1], 10) || 2))
  return `${(n - 2) * 0.07}s`
}

let svipLadderPopClearTimer = 0
function startSvipEntryRevealIfDue() {
  if (!hasSvipTier.value) return
  let due = false
  try {
    due = sessionStorage.getItem(SVIP_LADDER_REVEAL_KEY) === '1'
  } catch {
    return
  }
  if (!due) return
  try {
    sessionStorage.removeItem(SVIP_LADDER_REVEAL_KEY)
  } catch {
    /* ignore */
  }
  hideSvipLadderTiers.value = true
  svipEntryRevealOverlay.value = true
  window.setTimeout(() => {
    svipEntryRevealOverlay.value = false
    hideSvipLadderTiers.value = false
    svipLadderRevealPop.value = true
  }, 2300)
  if (svipLadderPopClearTimer) {
    clearTimeout(svipLadderPopClearTimer)
  }
  svipLadderPopClearTimer = window.setTimeout(() => {
    svipLadderRevealPop.value = false
  }, 5200)
}

/** 把后端 plan_id 映射成 tier 关键字，用于卡片渐变色等样式 hook */
function tierOf(plan) {
  const id = String(plan?.id || '')
  if (id === 'plan_basic') return 'vip'
  if (id === 'plan_pro') return 'vip_plus'
  if (id === 'plan_enterprise') return 'svip1'
  if (id.startsWith('plan_svip')) return id.replace('plan_', '') // svip2..svip8
  return 'free'
}

/** 当前页要显示的卡片：未购 svip 则隐藏 SVIP2~8；已购则全部展示 */
const visiblePlans = computed(() => {
  const list = Array.isArray(plans.value) ? plans.value : []
  const filtered = hasSvipTier.value
    ? list
    : list.filter((p) => !p?.requires_plan)
  return [...filtered].sort((a, b) => {
    const oa = planTierOrder(a?.id)
    const ob = planTierOrder(b?.id)
    if (oa < 0 && ob < 0) {
      return String(a?.id || '').localeCompare(String(b?.id || ''), 'zh')
    }
    if (oa < 0) return 1
    if (ob < 0) return -1
    if (oa !== ob) return oa - ob
    return String(a?.id || '').localeCompare(String(b?.id || ''), 'zh')
  })
})

function isCurrent(plan) {
  return plan?.id && myPlan.value?.id && plan.id === myPlan.value.id
}

async function loadPlans() {
  try {
    const [planRes, myPlanRes] = await Promise.all([
      api.paymentPlans(),
      authStore.hasToken() ? api.paymentMyPlan().catch(() => null) : Promise.resolve(null),
    ])
    plans.value = Array.isArray(planRes?.plans) ? planRes.plans : []
    myPlan.value = myPlanRes?.plan || null
    // 把最新会员状态同步给全局 auth store，导航栏用户名颜色随之更新
    void authStore.refreshMembership()
  } catch (e) {
    errorMsg.value = '加载会员套餐失败：' + (e?.message || String(e))
  } finally {
    loading.value = false
    await nextTick()
    startSvipEntryRevealIfDue()
  }
}

onMounted(loadPlans)

async function handleBuy(plan) {
  if (checkingOut.value) return
  if (isCurrent(plan)) return
  if (isBelowMyPlan(plan)) return
  if (!authStore.hasToken()) {
    router.push({ name: 'login', query: { redirect: '/plans' } })
    return
  }

  checkingOut.value = true
  checkingOutId.value = plan.id
  errorMsg.value = ''

  try {
    const res = await api.paymentCheckout({ plan_id: plan.id })
    if (!res.ok) {
      errorMsg.value = res.message || '会员购买下单失败'
      return
    }
    if (res.type === 'page' || res.type === 'wap') {
      window.location.href = res.redirect_url
    } else if (res.type === 'precreate' || res.type === 'wechat_native') {
      router.push({ name: 'checkout', params: { orderId: res.order_id } })
    } else {
      errorMsg.value = '未知的支付返回类型：' + (res.type || '空')
    }
  } catch (e) {
    let detail = e?.message || String(e)
    if (e instanceof ApiError && typeof e.status === 'number') {
      detail += `（HTTP ${e.status}）`
    }
    errorMsg.value = '会员购买下单失败：' + detail
  } finally {
    checkingOut.value = false
    checkingOutId.value = ''
  }
}
</script>

<style scoped>
.plans-page {
  min-height: 100vh;
  background: #0a0a0a;
  color: #ffffff;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  padding: 80px 24px;
}

.page-header {
  text-align: center;
  margin-bottom: 48px;
}

.page-title {
  font-size: clamp(28px, 4vw, 36px);
  font-weight: 600;
  letter-spacing: -0.02em;
  margin: 0 0 8px;
}

.page-desc {
  font-size: 16px;
  color: rgba(255, 255, 255, 0.5);
  margin: 0;
}

.loading {
  text-align: center;
  padding: 48px;
  color: rgba(255, 255, 255, 0.5);
}

.plans-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 17.5rem), 1fr));
  gap: 16px;
  width: 100%;
  max-width: min(80rem, 100%);
  margin: 0 auto;
  box-sizing: border-box;
}

.plan-card {
  position: relative;
  display: flex;
  flex-direction: column;
  padding: 32px 24px;
  border: 0.5px solid rgba(255, 255, 255, 0.1);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.02);
  transition: all 0.2s ease-out;
  --tier-color: rgba(255, 255, 255, 0.4);
}

.plan-card::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 16px;
  pointer-events: none;
  border-top: 2px solid var(--tier-color);
  opacity: 0.55;
  transition: opacity 0.2s ease;
}

.plan-card:hover::before {
  opacity: 0.85;
}

/* 各档位的强调色：用于卡片顶边 + 套餐名 */
.plan-card--vip      { --tier-color: #67e8f9; }
.plan-card--vip_plus { --tier-color: #fde047; }
.plan-card--svip1    { --tier-color: #c084fc; }
.plan-card--svip2    { --tier-color: #f472b6; }
.plan-card--svip3    { --tier-color: #34d399; }
.plan-card--svip4    { --tier-color: #fb923c; }
.plan-card--svip5    { --tier-color: #fb7185; }
.plan-card--svip6    { --tier-color: #818cf8; }
.plan-card--svip7    { --tier-color: #fbbf24; }
.plan-card--svip8    { --tier-color: #f472b6; }

.plan-card--svip8::before {
  border-top: 2px solid transparent;
  background: linear-gradient(90deg, #f87171, #fbbf24, #34d399, #38bdf8, #818cf8, #c084fc, #f472b6);
  background-size: 200% 100%;
  -webkit-mask:
    linear-gradient(#000 0 0) padding-box,
    linear-gradient(#000 0 0);
  -webkit-mask-composite: xor;
          mask-composite: exclude;
  border-radius: 16px;
  opacity: 0.7;
  height: 2px;
  inset: 0 0 auto 0;
  animation: plan-card-rainbow 8s linear infinite;
}
@keyframes plan-card-rainbow {
  0%   { background-position: 0% 50%; }
  100% { background-position: 200% 50%; }
}

.plan-name {
  color: var(--tier-color);
}

.plan-card:hover {
  border-color: rgba(255, 255, 255, 0.15);
  background: rgba(255, 255, 255, 0.04);
}

.plan-card--locked {
  opacity: 0.55;
  filter: grayscale(0.4);
}

.plan-card--locked:hover {
  border-color: rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.02);
}

/* 已拥有更高会员时，更低档位不可再购 */
.plan-card--lower-tier {
  opacity: 0.58;
  filter: grayscale(0.35);
}

.plan-card--lower-tier:hover {
  border-color: rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.02);
}

.plan-card--pre-reveal {
  opacity: 0;
  transform: translateY(14px) scale(0.98);
  filter: blur(2px);
  pointer-events: none;
  transition: none;
}

.plan-card--reveal-pop {
  animation: plan-svip-ladder-pop 0.6s cubic-bezier(0.22, 1, 0.36, 1) both;
}

@keyframes plan-svip-ladder-pop {
  0% {
    opacity: 0;
    transform: translateY(20px) scale(0.94);
    filter: blur(2px);
  }
  100% {
    opacity: 1;
    transform: translateY(0) scale(1);
    filter: blur(0);
  }
}

.plan-card--current {
  border-color: rgba(120, 200, 120, 0.45);
  background: rgba(120, 200, 120, 0.05);
}

.plan-header {
  margin-bottom: 24px;
}

.plan-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.plan-name {
  font-size: 18px;
  font-weight: 600;
  margin: 0;
}

.plan-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  border: 0.5px solid rgba(255, 255, 255, 0.18);
  color: rgba(255, 255, 255, 0.7);
  background: rgba(255, 255, 255, 0.04);
  letter-spacing: 0.02em;
}

.plan-badge--current {
  border-color: rgba(120, 200, 120, 0.4);
  color: rgb(180, 230, 180);
  background: rgba(120, 200, 120, 0.1);
}

.plan-badge--superseded {
  border-color: rgba(150, 150, 150, 0.35);
  color: rgba(200, 200, 200, 0.75);
  background: rgba(120, 120, 120, 0.12);
}

.plan-badge--locked {
  border-color: rgba(255, 200, 80, 0.35);
  color: rgb(245, 200, 110);
  background: rgba(255, 200, 80, 0.08);
}

.plan-price {
  margin-bottom: 8px;
}

.price-symbol {
  font-size: 16px;
  vertical-align: top;
}

.price-value {
  font-size: 32px;
  font-weight: 700;
}

.plan-desc {
  font-size: 14px;
  color: rgba(255, 255, 255, 0.5);
  margin: 0;
}

.plan-features {
  list-style: none;
  margin: 0 0 24px;
  padding: 0;
  flex: 1;
}

.plan-features li {
  padding: 8px 0;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.6);
  border-bottom: 0.5px solid rgba(255, 255, 255, 0.06);
}

.plan-features li:last-child {
  border-bottom: none;
}

.btn {
  width: 100%;
  padding: 12px 16px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease-out;
  border: none;
}

.btn-primary {
  background: #ffffff;
  color: #0a0a0a;
}

.btn-primary:hover {
  opacity: 0.9;
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.error-msg {
  width: 100%;
  max-width: min(42rem, 100%);
  margin: 0 auto 20px;
  padding: 12px 16px;
  background: rgba(255, 80, 80, 0.1);
  border: 0.5px solid rgba(255, 80, 80, 0.2);
  border-radius: 8px;
  color: #ff6b6b;
  text-align: left;
  font-size: 13px;
  line-height: 1.5;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
  box-sizing: border-box;
}

.error-msg--prominent {
  margin-top: 8px;
}

html[data-workbench-theme='light'] .plans-page {
  background: #f5f5f7;
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .page-desc {
  color: #86868b;
}

html[data-workbench-theme='light'] .loading {
  color: #86868b;
}

html[data-workbench-theme='light'] .plan-card {
  background: #ffffff;
  border-color: rgba(0, 0, 0, 0.08);
}

html[data-workbench-theme='light'] .plan-card::before {
  opacity: 0.35;
}

html[data-workbench-theme='light'] .plan-card:hover {
  border-color: rgba(0, 0, 0, 0.12);
  background: rgba(0, 0, 0, 0.02);
}

html[data-workbench-theme='light'] .plan-desc {
  color: #86868b;
}

html[data-workbench-theme='light'] .plan-features li {
  color: #555;
  border-bottom-color: rgba(0, 0, 0, 0.06);
}

html[data-workbench-theme='light'] .plan-badge {
  border-color: rgba(0, 0, 0, 0.1);
  color: #86868b;
  background: rgba(0, 0, 0, 0.04);
}

html[data-workbench-theme='light'] .plan-badge--current {
  border-color: rgba(34, 197, 94, 0.4);
  color: #16a34a;
  background: rgba(34, 197, 94, 0.08);
}

html[data-workbench-theme='light'] .plan-badge--superseded {
  border-color: rgba(0, 0, 0, 0.1);
  color: #86868b;
  background: rgba(0, 0, 0, 0.04);
}

html[data-workbench-theme='light'] .plan-card--current {
  border-color: rgba(34, 197, 94, 0.35);
  background: rgba(34, 197, 94, 0.04);
}

html[data-workbench-theme='light'] .btn-primary {
  background: #0071e3;
  color: #fff;
}

html[data-workbench-theme='light'] .btn-primary:hover {
  background: #0077ed;
  opacity: 1;
}

html[data-workbench-theme='light'] .btn-primary:disabled {
  opacity: 0.5;
}

html[data-workbench-theme='light'] .error-msg {
  background: rgba(220, 38, 38, 0.06);
  border-color: rgba(220, 38, 38, 0.15);
  color: #dc2626;
}

html[data-workbench-theme='light'] .plan-card--vip { --tier-color: #0891b2; }
html[data-workbench-theme='light'] .plan-card--vip_plus { --tier-color: #ca8a04; }
html[data-workbench-theme='light'] .plan-card--svip1 { --tier-color: #7c3aed; }
html[data-workbench-theme='light'] .plan-card--svip2 { --tier-color: #db2777; }
html[data-workbench-theme='light'] .plan-card--svip3 { --tier-color: #059669; }
html[data-workbench-theme='light'] .plan-card--svip4 { --tier-color: #ea580c; }
html[data-workbench-theme='light'] .plan-card--svip5 { --tier-color: #e11d48; }
html[data-workbench-theme='light'] .plan-card--svip6 { --tier-color: #4f46e5; }
html[data-workbench-theme='light'] .plan-card--svip7 { --tier-color: #d97706; }
html[data-workbench-theme='light'] .plan-card--svip8 { --tier-color: #db2777; }

html[data-workbench-theme='light'] .plan-card--locked:hover {
  border-color: rgba(0, 0, 0, 0.08);
  background: rgba(0, 0, 0, 0.02);
}
html[data-workbench-theme='light'] .plan-card--lower-tier:hover {
  border-color: rgba(0, 0, 0, 0.08);
  background: rgba(0, 0, 0, 0.02);
}
html[data-workbench-theme='light'] .plan-badge--locked {
  border-color: rgba(180, 83, 9, 0.25);
  color: #b45309;
  background: rgba(180, 83, 9, 0.06);
}
html[data-workbench-theme='light'] .price-symbol,
html[data-workbench-theme='light'] .price-value {
  color: #1d1d1f;
}

@media (max-width: 768px) {
  .plans-page {
    padding: 64px 16px;
  }

  .plans-grid {
    grid-template-columns: 1fr;
  }
}
</style>

<style>
/* 全屏揭晓层（Teleport 到 body，用非 scoped 保证全屏蒙层与动效） */
.svip-reveal-overlay {
  position: fixed;
  inset: 0;
  z-index: 10000;
  display: flex;
  align-items: center;
  justify-content: center;
  background: radial-gradient(ellipse 80% 60% at 50% 40%, rgba(120, 60, 180, 0.45), rgba(0, 0, 0, 0.92));
  animation: svip-reveal-fade 0.45s ease;
}
.svip-reveal-shimmer {
  position: absolute;
  inset: 0;
  background: linear-gradient(120deg, transparent 0%, rgba(255, 255, 255, 0.06) 50%, transparent 100%);
  background-size: 200% 100%;
  animation: svip-reveal-sweep 2.2s ease-in-out;
  pointer-events: none;
}
.svip-reveal-content {
  position: relative;
  text-align: center;
  padding: 0 24px;
  max-width: 24rem;
}
.svip-reveal-star {
  margin: 0 0 8px;
  font-size: 2rem;
  color: #e9d5ff;
  animation: svip-reveal-twinkle 1.2s ease-in-out infinite alternate;
}
.svip-reveal-h2 {
  margin: 0 0 12px;
  font-size: 1.75rem;
  font-weight: 600;
  color: #fff;
  letter-spacing: 0.02em;
}
.svip-reveal-p {
  margin: 0;
  font-size: 0.95rem;
  line-height: 1.5;
  color: rgba(255, 255, 255, 0.6);
}
@keyframes svip-reveal-fade {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}
@keyframes svip-reveal-sweep {
  0%,
  100% {
    background-position: 0% 50%;
  }
  50% {
    background-position: 100% 50%;
  }
}
@keyframes svip-reveal-twinkle {
  from {
    filter: drop-shadow(0 0 6px rgba(192, 132, 252, 0.4));
  }
  to {
    filter: drop-shadow(0 0 14px rgba(244, 114, 182, 0.55));
  }
}

html[data-workbench-theme='light'] .svip-reveal-overlay {
  background: radial-gradient(ellipse 80% 60% at 50% 40%, rgba(120, 60, 180, 0.2), rgba(255, 255, 255, 0.95));
}

html[data-workbench-theme='light'] .svip-reveal-h2 {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .svip-reveal-p {
  color: #86868b;
}

html[data-workbench-theme='light'] .svip-reveal-star {
  color: #7c3aed;
}

html[data-workbench-theme='light'] .svip-reveal-shimmer {
  background: linear-gradient(120deg, transparent 0%, rgba(0, 0, 0, 0.03) 50%, transparent 100%);
}
</style>
