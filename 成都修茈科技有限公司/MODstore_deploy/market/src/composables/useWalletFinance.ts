import { computed, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { ApiError } from '../infrastructure/http/client'
import { useWalletStore } from '../stores/wallet'
import { useAuthStore } from '../stores/auth'
import { WALLET_READ_TIMEOUT_MS } from '../api/wallet'
import {
  errorMessage,
  type PlanRecord,
  type QuotaRecord,
  type RawTransactionRecord,
  type RefundRecord,
  type TransactionRecord,
} from '../views/wallet/walletTypes'
import type { PaymentOrder } from '../types/api'

/** WalletView 资金域：余额 / 套餐 / 充值 / 资金中心 / 交易记录（自 WalletView.vue 原样迁移） */
export function useWalletFinance() {
  const router = useRouter()
  const walletStore = useWalletStore()
  const auth = useAuthStore()
  let accountVersion = 0
  const { balance, membershipReferenceYuan } = storeToRefs(walletStore)

  const transactions = ref<TransactionRecord[]>([])
  const txLoading = ref(true)
  const financeLoading = ref(true)
  const financeError = ref('')
  const txError = ref('')
  const planError = ref('')
  const planLoading = ref(true)
  const financeLoaded = ref(false)
  const txLoaded = ref(false)
  const balanceError = computed(() => walletStore.error || '')
  let overviewPending = false
  const recentOrders = ref<PaymentOrder[]>([])
  const orderListTotal = ref(0)
  const dismissOrdersLoading = ref(false)
  /** 资金页「最近订单」只展示前 N 条，避免与「全部订单」重复堆叠 */
  const RECENT_ORDERS_PANEL_LIMIT = 5
  /** 交易记录表默认只展示最近 N 条，其余由按钮展开 */
  const RECENT_TX_PANEL_LIMIT = 5
  const txListExpanded = ref(false)
  const recentRefunds = ref<RefundRecord[]>([])
  const payAmount = ref<number | null>(null)
  const payNote = ref('')
  const paying = ref(false)
  const payErr = ref('')
  const payHint = ref('')
  const isUpdating = ref(false)
  const amountError = ref('')
  const myPlan = ref<PlanRecord | null>(null)
  const myQuotas = ref<QuotaRecord[]>([])
  const isValidAmount = computed(() => {
    const amt = Number(payAmount.value)
    return !isNaN(amt) && amt > 0
  })

  /** 条长 = 当前余额 / 会员参考线（多笔单随单赠额与退款冲抵的净值；无则当前套餐价取整） */
  const balanceGaugeFill = computed(() => {
    const refY = Math.max(0, Number(membershipReferenceYuan.value ?? 0))
    if (refY <= 0) return 0
    const b = Number(balance.value)
    if (!isFinite(b) || b < 0) return 0
    return Math.min(100, (b / refY) * 100)
  })

  const recentOrdersPanel = computed(() =>
    (recentOrders.value || []).slice(0, RECENT_ORDERS_PANEL_LIMIT)
  )

  const visibleTransactions = computed(() => {
    const list = transactions.value || []
    if (txListExpanded.value || list.length <= RECENT_TX_PANEL_LIMIT) return list
    return list.slice(0, RECENT_TX_PANEL_LIMIT)
  })

  const hiddenTxCount = computed(() => {
    const n = (transactions.value || []).length
    return Math.max(0, n - RECENT_TX_PANEL_LIMIT)
  })

  async function loadMyPlan() {
    const version = accountVersion
    planLoading.value = true
    planError.value = ''
    try {
      const res = await api.paymentMyPlan()
      if (version !== accountVersion) return
      if (!res || !Object.hasOwn(res, 'plan') || !Array.isArray(res.quotas)) throw new Error('套餐信息暂时无法读取')
      myPlan.value = res.plan ?? null
      myQuotas.value = res.quotas || []
    } catch {
      if (version !== accountVersion) return
      planError.value = '套餐信息加载失败，请重试。'
    } finally {
      if (version === accountVersion) planLoading.value = false
    }
  }

  function quotaLabel(t: string): string {
    const m = { employee_count: '员工数', llm_calls: 'LLM 调用', storage_mb: '存储(MB)' }
    return m[t as keyof typeof m] || t
  }

  function txnTypeLabel(type: string | null | undefined): string {
    const m = {
      recharge: '管理员充值',
      admin_self_credit: '管理员本人加款',
      alipay_wallet: '支付宝充值',
      alipay_recharge: '支付宝入账',
      alipay_payment: '支付入账',
      plan_purchase: '套餐购买',
      item_purchase: '商品购买',
      purchase: '购买',
      wallet_refund: '退款入账',
      ai_preauth: 'AI 预授权',
      ai_settle_extra: 'AI 补扣',
      ai_release: 'AI 预授权退还',
      plan_membership_tokens: '会员随单额度',
      plan_membership_tokens_revoke: '会员额度扣回',
      llm_wallet_charge: '大模型扣费',
    }
    return m[type as keyof typeof m] || type || '—'
  }

  function orderStatusText(status: string | null | undefined): string {
    const m = {
      pending: '待支付',
      paid: '已支付',
      refunding: '退款中',
      refunded: '已退款',
      partial_refunded: '部分退款',
      failed: '失败',
      closed: '已关闭',
    }
    return m[status as keyof typeof m] || status || '—'
  }

  function refundStatusText(status: string | null | undefined): string {
    const m = {
      pending: '待审核',
      approved: '已退回钱包',
      rejected: '已拒绝',
      failed: '失败',
    }
    return m[status as keyof typeof m] || status || '—'
  }

  function money(value: unknown): string {
    const n = Number(value)
    return Number.isFinite(n) ? n.toFixed(2) : '0.00'
  }

  function goOrder(order: PaymentOrder): void {
    if (!order?.out_trade_no) return
    router.push({ name: 'order-detail', params: { orderId: order.out_trade_no } })
  }

  async function loadWalletOverview() {
    if (overviewPending) return
    overviewPending = true
    const version = accountVersion
    let walletSnapshotApplied = false
    financeLoading.value = true
    txLoading.value = true
    financeError.value = ''
    txError.value = ''
    try {
      const res = await api.walletOverview(20, 0)
      if (version !== accountVersion) return
      const walletBalance = res?.wallet?.balance
      if (walletBalance === undefined || walletBalance === null || String(walletBalance).trim() === ''
        || !Number.isFinite(Number(walletBalance)) || !Array.isArray(res.transactions)) {
        throw new Error('资金信息暂时无法读取')
      }
      walletStore.setBalance(walletBalance)
      if (res?.wallet?.membership_reference_yuan !== undefined) {
        walletStore.setMembershipReferenceYuan(res.wallet.membership_reference_yuan)
      }
      transactions.value = (res.transactions || []).map(normalizeTransaction)
      txLoaded.value = true
      txLoading.value = false
      walletSnapshotApplied = true
      // The legacy overview only includes balance and transactions. Read each
      // missing finance collection explicitly before presenting it as empty.
      const [orderResult, refunds] = await Promise.all([
        Array.isArray(res.orders) ? Promise.resolve({ orders: res.orders, total: res.order_total }) : api.paymentOrders('', 20, 0, { timeoutMs: WALLET_READ_TIMEOUT_MS }),
        Array.isArray(res.refunds) ? Promise.resolve(res.refunds) : api.refundsMy({ timeoutMs: WALLET_READ_TIMEOUT_MS }).then((data) => data.refunds),
      ])
      if (version !== accountVersion) return
      const orders = orderResult.orders
      if (!Array.isArray(orders) || !Array.isArray(refunds)) throw new Error('资金记录暂时无法读取')
      recentOrders.value = orders
      orderListTotal.value = orderResult.total != null ? Number(orderResult.total) : orders.length
      recentRefunds.value = refunds
      financeLoaded.value = true
    } catch (error: unknown) {
      if (version !== accountVersion) return
      financeError.value = '订单与退款记录加载失败，请重试。'
      if (!walletSnapshotApplied) {
        txError.value = '交易记录加载失败，请重试。'
        walletStore.markBalanceStale('余额加载失败，请重试。')
      }
      // Older servers may lack overview. Only that explicit case uses bounded
      // read fallbacks; timeouts must not start more requests against a stalled server.
      if (!walletSnapshotApplied && error instanceof ApiError && [404, 405].includes(error.status)) {
        await Promise.all([loadBalance(), loadTransactions()])
      }
    } finally {
      if (version === accountVersion) {
        overviewPending = false
        financeLoading.value = false
        txLoading.value = false
      }
    }
  }

  async function dismissNonActiveOrders() {
    if (dismissOrdersLoading.value) return
    if (
      !confirm('将已关闭/失败/已退款等终态单从「订单列表」中隐藏（不删单），并保留待支付、已支付、退款中。是否继续？')
    ) {
      return
    }
    dismissOrdersLoading.value = true
    try {
      const res = await api.paymentDismissNonActiveOrders()
      if (res?.ok === false) {
        payErr.value = res?.message || '清理失败'
      } else {
        payHint.value = `已隐藏 ${Number(res?.dismissed || 0)} 条，列表仅保留可跟进或已成功的单。`
        setTimeout(() => {
          payHint.value = ''
        }, 5000)
      }
      await loadWalletOverview()
    } catch (e: unknown) {
      payErr.value = errorMessage(e)
    } finally {
      dismissOrdersLoading.value = false
    }
  }

  async function loadBalance() {
    try {
      // The wallet page provides an explicit retry button; do not hide a failed
      // read behind three sequential network timeouts.
      await walletStore.refreshBalance(0)
    } catch {
      walletStore.markBalanceStale('余额加载失败，请重试。')
    }
  }

  async function loadTransactions() {
    const version = accountVersion
    txLoading.value = true
    txError.value = ''
    try {
      const res = await api.transactions()
      if (version !== accountVersion) return
      if (!Array.isArray(res.transactions)) throw new Error('交易记录暂时无法读取')
      transactions.value = res.transactions.map(normalizeTransaction)
      txLoaded.value = true
    } catch {
      if (version !== accountVersion) return
      txError.value = '交易记录加载失败，请重试。'
    } finally {
      if (version === accountVersion) txLoading.value = false
    }
  }

  function normalizeTransaction(t: RawTransactionRecord): TransactionRecord {
    return {
      ...t,
      amount: Number(t?.amount ?? 0),
    }
  }

  function validateAmount() {
    const amt = Number(payAmount.value)
    if (!amt || amt <= 0) {
      amountError.value = '请输入大于 0 的金额'
    } else if (amt > 999999) {
      amountError.value = '充值金额不能超过 999,999 元'
    } else {
      amountError.value = ''
    }
  }

  async function startAlipayRecharge() {
    if (!localStorage.getItem('modstore_token')) {
      await router.push({ name: 'login', query: { redirect: '/wallet' } })
      return
    }
    validateAmount()
    if (amountError.value) {
      return
    }
    paying.value = true
    payErr.value = ''
    payHint.value = ''
    const amt = Number(payAmount.value)
    try {
      const res = await api.paymentCheckout({
        wallet_recharge: true,
        total_amount: amt,
        subject: payNote.value.trim() || 'XC AGI 钱包充值',
      })
      if (!res.ok) {
        payErr.value = res.message || '下单失败'
        return
      }
      if (res.type === 'page' || res.type === 'wap') {
        if (res.redirect_url) {
          window.location.href = res.redirect_url
          return
        }
        payErr.value = '未返回支付跳转地址'
        return
      }
      if ((res.type === 'precreate' || res.type === 'wechat_native') && res.order_id) {
        await router.push({ name: 'checkout', params: { orderId: res.order_id } })
        return
      }
      payErr.value = '未知的支付类型'
    } catch (e: unknown) {
      payErr.value = errorMessage(e)
    } finally {
      paying.value = false
    }
  }

  function formatDate(iso: string | null | undefined): string {
    if (!iso) return ''
    return new Date(iso).toLocaleString('zh-CN')
  }

  watch(() => auth.user?.id, () => {
    accountVersion++
    overviewPending = false
    transactions.value = []
    recentOrders.value = []
    orderListTotal.value = 0
    recentRefunds.value = []
    myPlan.value = null
    myQuotas.value = []
    financeLoaded.value = false
    txLoaded.value = false
    financeError.value = ''
    txError.value = ''
    planError.value = ''
    financeLoading.value = false
    txLoading.value = false
    planLoading.value = false
    if (auth.user?.id) {
      void loadWalletOverview()
      void loadMyPlan()
    }
  }, { flush: 'sync' })

  onMounted(() => {
    // 资金区与模型目录分开加载，避免 catalog 慢请求拖死整页「加载中…」
    void loadWalletOverview()
    void loadMyPlan()
  })

  return {
    balance,
    membershipReferenceYuan,
    transactions,
    txLoading,
    financeLoading,
    financeError,
    financeLoaded,
    txError,
    txLoaded,
    balanceError,
    planError,
    planLoading,
    recentOrders,
    orderListTotal,
    dismissOrdersLoading,
    RECENT_ORDERS_PANEL_LIMIT,
    RECENT_TX_PANEL_LIMIT,
    txListExpanded,
    recentRefunds,
    payAmount,
    payNote,
    paying,
    payErr,
    payHint,
    isUpdating,
    amountError,
    myPlan,
    myQuotas,
    isValidAmount,
    balanceGaugeFill,
    recentOrdersPanel,
    visibleTransactions,
    hiddenTxCount,
    loadWalletOverview,
    dismissNonActiveOrders,
    loadMyPlan,
    quotaLabel,
    txnTypeLabel,
    orderStatusText,
    refundStatusText,
    money,
    goOrder,
    loadBalance,
    loadTransactions,
    // 测试兼容面：既有测试经 wrapper.vm 访问原单文件顶层绑定
    normalizeTransaction,
    validateAmount,
    startAlipayRecharge,
    formatDate,
  }
}

export type WalletFinanceApi = ReturnType<typeof useWalletFinance>
