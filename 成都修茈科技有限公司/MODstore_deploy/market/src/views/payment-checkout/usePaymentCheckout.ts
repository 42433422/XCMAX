// 支付结算页主逻辑：订单拉取/轮询对账、支付宝回跳密集确认与重新支付。
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { RouteLocationNormalizedLoaded, Router } from 'vue-router'
import { api } from '../../api'
import { useAuthStore } from '../../stores/auth'

export interface CheckoutOrder {
  out_trade_no?: string
  subject?: string
  total_amount?: number | string
  status?: string
  created_at?: string
  qr_code?: string
  /** 与 Java 下单返回一致：page / wap / precreate / wechat_native */
  pay_type?: string
  plan_id?: string
  order_kind?: string
  item_id?: number | string
}

/** Java 查询接口在业务失败时也可能 HTTP 200 + `{ ok: false, message }`，须与订单 JSON 区分 */
function isPaymentQueryFailedEnvelope(res: unknown): res is { ok: false; message?: string } {
  return typeof res === 'object' && res !== null && (res as { ok?: boolean }).ok === false
}

export function usePaymentCheckout(deps: {
  route: RouteLocationNormalizedLoaded
  router: Router
}) {
  const { route, router } = deps
  const authStore = useAuthStore()

  const orderParamId = computed(() => {
    const p = route.params.orderId
    const v = Array.isArray(p) ? p[0] : p
    return v == null ? '' : String(v)
  })

  const order = ref<CheckoutOrder | null>(null)
  const loading = ref(true)
  const error = ref('')
  const transientWarning = ref('')
  const qrCode = ref('')
  const refreshing = ref(false)
  /** 支付宝同步回跳后的短时密集对账 */
  const burstSyncActive = ref(false)
  /** 刚从待支付变为已支付：给用户明确的「到账」反馈 */
  const paidConfirmedFlash = ref(false)
  const pollingTimer = ref<ReturnType<typeof setInterval> | null>(null)

  const isAccountLicenseOrder = computed(() => String(order.value?.plan_id || '').startsWith('saas-'))
  const isCustomDeliveryOrder = computed(() => String(order.value?.order_kind || '') === 'custom_delivery')
  const planSelectionRoute = computed(() =>
    isCustomDeliveryOrder.value ? '/deliveries' : isAccountLicenseOrder.value ? '/account-plans' : '/plans',
  )

  const qrImageUrl = computed(() => {
    if (!qrCode.value) return ''
    return `https://api.qrserver.com/v1/create-qr-code/?size=280x280&margin=8&data=${encodeURIComponent(qrCode.value)}`
  })

  const isExpired = computed(() => {
    if (!order.value || order.value.status !== 'pending') return false
    const created = new Date(order.value.created_at || '').getTime()
    if (Number.isNaN(created)) return false
    const now = Date.now()
    return now - created > 15 * 60 * 1000
  })

  function stopPolling() {
    if (pollingTimer.value) {
      clearInterval(pollingTimer.value)
      pollingTimer.value = null
    }
  }

  /** 待支付单持续轮询（含超时 UI 场景），方便对账/回调延迟后仍能变为已支付 */
  function startPollingIfPending() {
    stopPolling()
    if (order.value?.status !== 'pending') return
    const intervalMs = isExpired.value ? 10_000 : 3000
    pollingTimer.value = setInterval(pollOrder, intervalMs)
  }

  async function refetchVisiblePending() {
    if (typeof document !== 'undefined' && document.visibilityState !== 'visible') return
    if (!order.value || order.value.status !== 'pending') return
    await fetchOrder()
    startPollingIfPending()
  }

  function onVisibilityChange() {
    void refetchVisiblePending()
  }

  function onPageShow() {
    void refetchVisiblePending()
  }

  /** 支付宝电脑网站支付同步跳转会在 return_url 上带 sign、trade_no、method 等参数（不能做账务依据，但可用来触发立即对账） */
  function looksLikeAlipayReturnQuery(q: Record<string, string | string[] | undefined>): boolean {
    const keys = Object.keys(q)
    if (keys.length === 0) return false
    const sign = String(Array.isArray(q.sign) ? q.sign[0] : (q.sign ?? ''))
    const method = String(Array.isArray(q.method) ? q.method[0] : (q.method ?? ''))
    const tradeNo = String(Array.isArray(q.trade_no) ? q.trade_no[0] : (q.trade_no ?? ''))
    return sign.length > 20 || method.includes('alipay.trade') || tradeNo.length > 8
  }

  async function burstConfirmPaymentFromAlipayReturn() {
    burstSyncActive.value = true
    try {
      for (let i = 0; i < 18; i++) {
        if (order.value?.status === 'paid') return
        await new Promise<void>((resolve) => {
          window.setTimeout(resolve, i === 0 ? 400 : 1700)
        })
        await pollOrder()
      }
    } finally {
      burstSyncActive.value = false
    }
  }

  watch(
    () => order.value?.status,
    (next, prev) => {
      if (next === 'paid' && prev === 'pending') {
        paidConfirmedFlash.value = true
        window.setTimeout(() => {
          paidConfirmedFlash.value = false
        }, 14_000)
      }
    },
  )

  onMounted(async () => {
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', onVisibilityChange)
    }
    if (typeof window !== 'undefined') {
      window.addEventListener('pageshow', onPageShow)
    }
    await fetchOrder()
    startPollingIfPending()
    const q = route.query as Record<string, string | string[] | undefined>
    if (order.value?.status === 'pending' && looksLikeAlipayReturnQuery(q) && orderParamId.value) {
      void burstConfirmPaymentFromAlipayReturn()
    }
  })

  onBeforeUnmount(() => {
    if (typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
    if (typeof window !== 'undefined') {
      window.removeEventListener('pageshow', onPageShow)
    }
    stopPolling()
  })

  function applyOrderSnapshot(nextOrder: CheckoutOrder) {
    order.value = nextOrder
    qrCode.value = nextOrder.qr_code ? String(nextOrder.qr_code) : ''
    if (nextOrder.status !== 'paid') return
    void authStore.refreshSession(true)
    if (String(nextOrder.plan_id || '').trim() === 'plan_enterprise') {
      try {
        sessionStorage.setItem('modstore_svip_ladder_reveal', '1')
      } catch {
        /* ignore */
      }
    }
    stopPolling()
  }

  async function fetchOrder() {
    try {
      error.value = ''
      transientWarning.value = ''
      const res = await api.paymentQuery(orderParamId.value, { reconcile: true })
      if (isPaymentQueryFailedEnvelope(res)) {
        const msg = typeof res.message === 'string' && res.message.trim() ? res.message.trim() : '加载订单失败'
        if (order.value) {
          transientWarning.value = msg
        } else {
          error.value = msg
          stopPolling()
        }
        return
      }
      applyOrderSnapshot(res as CheckoutOrder)
    } catch (err) {
      const msg = (err as Error)?.message || '加载订单信息失败，请重试'
      if (order.value) {
        transientWarning.value = `网络波动，正在继续重试：${msg}`
      } else {
        error.value = msg
        stopPolling()
      }
    } finally {
      loading.value = false
    }
  }

  async function pollOrder() {
    try {
      // 每次轮询都对账：支付宝回跳/异步通知延迟时，仅靠「隔次 reconcile」可能长时间停在待支付
      const res = await api.paymentQuery(orderParamId.value, { reconcile: true })
      if (isPaymentQueryFailedEnvelope(res)) {
        transientWarning.value =
          typeof res.message === 'string' && res.message.trim() ? res.message.trim() : '订单状态暂时无法确认，正在继续重试'
        return
      }
      transientWarning.value = ''
      applyOrderSnapshot(res as CheckoutOrder)
    } catch (err) {
      //  polling errors，不显示错误，避免干扰用户
      console.error('Polling error:', err)
    }
  }

  function statusText(status: string | undefined): string {
    const map: Record<string, string> = {
      pending: '待支付',
      paid: '已支付',
      failed: '支付失败',
      closed: '已关闭',
    }
    return (status && map[status]) || status || '未知'
  }

  function payTypeLabel(payType: string | undefined): string {
    const t = String(payType || '').toLowerCase()
    const map: Record<string, string> = {
      page: '支付宝（电脑网站）',
      wap: '支付宝（手机网站）',
      precreate: '支付宝（扫码）',
      wechat_native: '微信（扫码）',
    }
    return map[t] || payType || '—'
  }

  async function manualRefreshStatus() {
    if (!orderParamId.value || refreshing.value) return
    refreshing.value = true
    try {
      await fetchOrder()
      startPollingIfPending()
    } finally {
      refreshing.value = false
    }
  }

  async function retryPayment() {
    const o = order.value
    if (!o) return
    if (String(o.order_kind || '') === 'custom_delivery') {
      await router.push('/deliveries')
      return
    }
    stopPolling()
    try {
      if ((o.status === 'pending' || o.status === 'closed') && o.out_trade_no) {
        try {
          await api.paymentCancelOrder(o.out_trade_no)
        } catch {
          /* 非待支付等情况下取消会失败，忽略 */
        }
      }
    } catch {
      /* ignore */
    }

    loading.value = true
    error.value = ''
    try {
      const kind = String(o.order_kind || '').toLowerCase()
      const itemId = Number(o.item_id || 0) || 0
      const planId = String(o.plan_id || '').trim()
      const walletRecharge = kind === 'wallet'
      const payload: Record<string, unknown> = {
        plan_id: planId,
        item_id: itemId,
        subject: o.subject || '',
        wallet_recharge: walletRecharge,
      }
      if (walletRecharge) {
        const ta = Number.parseFloat(String(o.total_amount ?? '0'))
        if (ta > 0) payload.total_amount = ta
      }
      const checkout = await api.paymentCheckout(payload)
      if (!checkout.ok) {
        error.value = checkout.message || '重新下单失败'
        return
      }
      if ((checkout.type === 'precreate' || checkout.type === 'wechat_native') && checkout.order_id) {
        await router.replace({ name: 'checkout', params: { orderId: checkout.order_id } })
        order.value = null
        qrCode.value = ''
        await fetchOrder()
        startPollingIfPending()
      } else if (checkout.type === 'page' || checkout.type === 'wap') {
        window.location.href = checkout.redirect_url || ''
      } else {
        error.value = '不支持的支付类型'
      }
    } catch (e) {
      error.value = (e as Error)?.message || '重新支付失败'
    } finally {
      loading.value = false
    }
  }

  return {
    order,
    loading,
    error,
    transientWarning,
    qrCode,
    refreshing,
    burstSyncActive,
    paidConfirmedFlash,
    isAccountLicenseOrder,
    isCustomDeliveryOrder,
    planSelectionRoute,
    qrImageUrl,
    isExpired,
    orderParamId,
    fetchOrder,
    pollOrder,
    statusText,
    payTypeLabel,
    manualRefreshStatus,
    retryPayment,
    refetchVisiblePending,
    looksLikeAlipayReturnQuery,
  }
}
