/**
 * 会员购买页 · 套餐加载 / 档位比较 / SVIP 揭晓动画 / 结账（由 PaymentPlansView.vue 原单文件机械迁出，行为不变）。
 */
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/infrastructure/http/client'

const SVIP_LADDER_REVEAL_KEY = 'modstore_svip_ladder_reveal'

type PaymentPlan = {
  id: string
  name?: string
  price: number
  description?: string
  features?: string[]
  requires_plan?: string | boolean | null
  [key: string]: unknown
}

export function usePaymentPlans() {
  const router = useRouter()
  const authStore = useAuthStore()

  const plans = ref<PaymentPlan[]>([])
  const myPlan = ref<PaymentPlan | null>(null)
  const loading = ref(true)
  const checkingOut = ref(false)
  const checkingOutId = ref('')
  const errorMsg = ref('')
  const errorBannerRef = ref<HTMLElement | null>(null)

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

  function planTierOrder(planId: string | null | undefined): number {
    const id = String(planId || '').trim()
    return Object.prototype.hasOwnProperty.call(MEMBERSHIP_TIER_ORDER, id)
      ? MEMBERSHIP_TIER_ORDER[id as keyof typeof MEMBERSHIP_TIER_ORDER]
      : -1
  }

  const myPlanTierOrder = computed(() => planTierOrder(myPlan.value?.id))

  /**
   * 当前用户已拥有比该套餐更高的有效档位，不应再购买这一档（降级/重复买低档）。
   * 无会员或 current 为未知 id 时不过滤，避免误伤。
   */
  function isBelowMyPlan(plan: PaymentPlan): boolean {
    if (!plan?.id || isCurrent(plan)) return false
    const cur = myPlanTierOrder.value
    const t = planTierOrder(plan.id)
    if (cur < 0 || t < 0) return false
    return t < cur
  }

  function isSvipLadderPlan(plan: PaymentPlan): boolean {
    return /^plan_svip[2-8]$/.test(String(plan?.id || ''))
  }

  /** SVIP2→0 … SVIP8→6s */
  function svipLadderStaggerDelay(plan: PaymentPlan): string {
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
  function tierOf(plan: PaymentPlan): string {
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

  function isCurrent(plan: PaymentPlan): boolean {
    return Boolean(plan.id && myPlan.value?.id && plan.id === myPlan.value.id)
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
    } catch (e: unknown) {
      errorMsg.value = '加载会员套餐失败：' + (e instanceof Error ? e.message : String(e))
    } finally {
      loading.value = false
      await nextTick()
      startSvipEntryRevealIfDue()
    }
  }

  onMounted(loadPlans)

  async function handleBuy(plan: PaymentPlan) {
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
        if (res.redirect_url) window.location.href = res.redirect_url
        else errorMsg.value = '支付网关未返回跳转地址'
      } else if (res.type === 'precreate' || res.type === 'wechat_native') {
        router.push({ name: 'checkout', params: { orderId: res.order_id } })
      } else {
        errorMsg.value = '未知的支付返回类型：' + (res.type || '空')
      }
    } catch (e: unknown) {
      let detail = e instanceof Error ? e.message : String(e)
      if (e instanceof ApiError && typeof e.status === 'number') {
        detail += `（HTTP ${e.status}）`
      }
      errorMsg.value = '会员购买下单失败：' + detail
    } finally {
      checkingOut.value = false
      checkingOutId.value = ''
    }
  }

  return {
    plans,
    myPlan,
    loading,
    checkingOut,
    checkingOutId,
    errorMsg,
    errorBannerRef,
    svipEntryRevealOverlay,
    hideSvipLadderTiers,
    svipLadderRevealPop,
    hasSvipTier,
    planTierOrder,
    isBelowMyPlan,
    isSvipLadderPlan,
    svipLadderStaggerDelay,
    tierOf,
    visiblePlans,
    isCurrent,
    loadPlans,
    handleBuy,
  }
}
