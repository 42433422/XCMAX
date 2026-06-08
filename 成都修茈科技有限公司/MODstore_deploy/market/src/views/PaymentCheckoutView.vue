<template>
  <div class="checkout-page">
    <div class="checkout-container">
      <h1 class="checkout-title">支付订单</h1>

      <div v-if="paidConfirmedFlash" role="status" class="confirm-banner confirm-banner--success">
        <strong>支付已确认到账</strong>
        <span class="confirm-banner-sub">系统已向支付宝核对，订单为「已支付」，权益将按套餐生效。</span>
      </div>
      <div
        v-else-if="burstSyncActive && order?.status === 'pending'"
        role="status"
        class="confirm-banner confirm-banner--sync"
      >
        <strong>正在向支付宝确认付款结果…</strong>
        <span class="confirm-banner-sub">请稍候，通常几秒内完成；请勿关闭本页。</span>
      </div>
      <div
        v-else-if="order?.status === 'pending'"
        class="confirm-banner confirm-banner--hint"
      >
        <strong>到账结果以本页「状态」为准</strong>
        <span class="confirm-banner-sub">
          付款成功后系统会自动向支付宝核对；若仍为「待支付」，请点击下方「刷新订单状态」主动对账。
        </span>
      </div>

      <div v-if="loading" class="loading">
        <div class="spinner"></div>
        <p>加载订单信息...</p>
      </div>

      <div v-if="error" class="error-section">
        <div class="error-icon">!</div>
        <h2 class="error-title">加载失败</h2>
        <p class="error-desc">{{ error }}</p>
        <router-link to="/plans" class="btn btn-primary">返回套餐页</router-link>
      </div>

      <template v-else-if="order">
        <div v-if="transientWarning" role="status" class="transient-warning">
          {{ transientWarning }}
        </div>

        <!-- 订单信息 -->
        <div class="order-info">
          <div class="order-field">
            <span class="label">订单号</span>
            <span class="value">{{ order.out_trade_no }}</span>
          </div>
          <div class="order-field">
            <span class="label">商品</span>
            <span class="value">{{ order.subject }}</span>
          </div>
          <div class="order-field">
            <span class="label">金额</span>
            <span class="value price">¥{{ order.total_amount }}</span>
          </div>
          <div class="order-field">
            <span class="label">状态</span>
            <span :class="['value', 'status', `status-${order.status}`]">
              {{ statusText(order.status) }}
            </span>
          </div>
          <div v-if="order.pay_type" class="order-field">
            <span class="label">下单方式</span>
            <span class="value">{{ payTypeLabel(order.pay_type) }}</span>
          </div>
        </div>

        <!-- 浏览器跳转支付（alipay page/wap）：无二维码，需提示回站后自动对账 / 手动刷新 -->
        <div
          v-if="order.status === 'pending' && !qrCode"
          class="pending-redirect-section"
        >
          <p class="pending-redirect-title">等待支付结果同步</p>
          <p class="pending-redirect-desc">
            当前订单为<strong>浏览器跳转支付宝</strong>付款：下单后会跳转到支付宝页面；支付完成后请返回本站，状态会自动更新。
            若您已付款仍显示「待支付」，请点击下方按钮<strong>向支付宝主动对账</strong>（通常立即生效）。
          </p>
          <div class="pending-redirect-actions">
            <button
              type="button"
              class="btn btn-primary"
              :disabled="refreshing"
              @click="manualRefreshStatus"
            >
              {{ refreshing ? '正在向支付宝核对…' : '刷新订单状态（对账）' }}
            </button>
            <button type="button" class="btn btn-ghost" :disabled="refreshing" @click="retryPayment">
              重新发起支付
            </button>
          </div>
          <p class="pending-redirect-foot">
            长时间未更新请核对是否登录了同一账号；仍异常请保存订单号联系客服。
          </p>
        </div>

        <!-- 二维码展示（precreate 模式） -->
        <div v-if="qrCode && order.status === 'pending'" class="qr-section">
          <p class="qr-hint">打开支付宝扫码支付</p>
          <div class="qr-wrapper">
            <img
              v-if="qrImageUrl"
              class="qr-img"
              :src="qrImageUrl"
              width="280"
              height="280"
              alt="支付宝支付二维码"
            />
          </div>
          <p v-if="isExpired" class="qr-expired-hint">
            订单已超时未支付。
            <button type="button" class="btn-retry" @click="retryPayment">重新支付</button>
            <router-link to="/plans" class="link-muted">或返回套餐页</router-link>
          </p>
          <p v-else class="qr-waiting">等待支付中，支付成功后自动跳转...</p>
        </div>

        <!-- 已支付成功 -->
        <div v-if="order.status === 'paid'" class="success-section">
          <div class="success-icon">✓</div>
          <h2 class="success-title">支付成功</h2>
          <p class="success-desc">资金已进入钱包账本，订单消费与权益发放已完成。</p>
          <div class="success-actions">
            <router-link to="/wallet" class="btn btn-primary">查看钱包资金账户</router-link>
            <router-link :to="{ name: 'wallet-purchased' }" class="btn btn-ghost">已购资产</router-link>
            <router-link to="/plans" class="btn btn-ghost">继续选购</router-link>
          </div>
          <p class="refund-hint">
            如需退款，可
            <router-link
              :to="{ name: 'refunds', query: { order_no: order.out_trade_no } }"
              class="refund-link"
            >
              提交退款申请
            </router-link>
            ，处理进度会显示在钱包资金账户中。
          </p>
        </div>

        <!-- 支付失败 -->
        <div v-if="order.status === 'failed'" class="failed-section">
          <p>支付失败</p>
          <router-link to="/plans" class="btn btn-primary">重新下单</router-link>
        </div>

        <!-- 已关闭 -->
        <div v-if="order.status === 'closed'" class="closed-section">
          <p>订单已关闭</p>
          <button type="button" class="btn btn-primary" @click="retryPayment">重新支付</button>
          <router-link to="/plans" class="btn btn-ghost">返回套餐页</router-link>
        </div>
      </template>

      <div v-else class="not-found">
        <p>订单不存在</p>
        <router-link to="/plans" class="btn btn-ghost">返回套餐页</router-link>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const orderParamId = computed(() => {
  const p = route.params.orderId
  const v = Array.isArray(p) ? p[0] : p
  return v == null ? '' : String(v)
})
const authStore = useAuthStore()
interface CheckoutOrder {
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

const qrImageUrl = computed(() => {
  if (!qrCode.value) return ''
  return `https://api.qrserver.com/v1/create-qr-code/?size=280x280&margin=8&data=${encodeURIComponent(qrCode.value)}`
})

const isExpired = computed(() => {
  if (!order.value || order.value.status !== 'pending') return false
  const created = new Date(order.value.created_at || '').getTime()
  if (Number.isNaN(created)) return false
  const now = Date.now()
  return (now - created) > 15 * 60 * 1000
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
  const sign = String(Array.isArray(q.sign) ? q.sign[0] : q.sign ?? '')
  const method = String(Array.isArray(q.method) ? q.method[0] : q.method ?? '')
  const tradeNo = String(Array.isArray(q.trade_no) ? q.trade_no[0] : q.trade_no ?? '')
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
  if (
    order.value?.status === 'pending'
    && looksLikeAlipayReturnQuery(q)
    && orderParamId.value
  ) {
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

async function fetchOrder() {
  try {
    error.value = ''
    transientWarning.value = ''
    const res = await api.paymentQuery(orderParamId.value, { reconcile: true })
    if (isPaymentQueryFailedEnvelope(res)) {
      const msg = (typeof res.message === 'string' && res.message.trim()) ? res.message.trim() : '加载订单失败'
      if (order.value) {
        transientWarning.value = msg
      } else {
        error.value = msg
        stopPolling()
      }
      return
    }
    const o = res as CheckoutOrder
    order.value = o

    if (o.qr_code) {
      qrCode.value = String(o.qr_code)
    } else {
      qrCode.value = ''
    }

    if (o.status === 'paid') {
      void authStore.refreshSession(true)
      if (String(o.plan_id || '').trim() === 'plan_enterprise') {
        try {
          sessionStorage.setItem('modstore_svip_ladder_reveal', '1')
        } catch {
          /* ignore */
        }
      }
    }
    if (o.status === 'paid') {
      stopPolling()
    }
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
        (typeof res.message === 'string' && res.message.trim()) ? res.message.trim() : '订单状态暂时无法确认，正在继续重试'
      return
    }
    transientWarning.value = ''
    const o = res as CheckoutOrder
    order.value = o
    if (o.qr_code) {
      qrCode.value = String(o.qr_code)
    } else {
      qrCode.value = ''
    }

    if (o.status === 'paid') {
      void authStore.refreshSession(true)
      if (String(o.plan_id || '').trim() === 'plan_enterprise') {
        try {
          sessionStorage.setItem('modstore_svip_ladder_reveal', '1')
        } catch {
          /* ignore */
        }
      }
    }
    if (o.status === 'paid') {
      stopPolling()
    }
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
</script>

<style scoped>
.checkout-page {
  min-height: 100vh;
  background: #0a0a0a;
  color: #ffffff;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  display: flex;
  justify-content: center;
  padding-top: 80px;
}

.checkout-container {
  width: 100%;
  max-width: 480px;
  padding: 0 24px;
}

.checkout-title {
  font-size: 24px;
  font-weight: 600;
  text-align: center;
  margin: 0 0 32px;
  letter-spacing: -0.02em;
}

.confirm-banner {
  border-radius: 10px;
  padding: 14px 16px;
  margin: 0 0 20px;
  font-size: 13px;
  line-height: 1.5;
}

.confirm-banner strong {
  display: block;
  margin-bottom: 6px;
  font-size: 14px;
}

.confirm-banner-sub {
  display: block;
  color: rgba(255, 255, 255, 0.72);
  font-weight: 400;
}

.confirm-banner--success {
  border: 1px solid rgba(74, 222, 128, 0.45);
  background: rgba(74, 222, 128, 0.12);
  color: #bbf7d0;
}

.confirm-banner--success .confirm-banner-sub {
  color: rgba(187, 247, 208, 0.85);
}

.confirm-banner--sync {
  border: 1px solid rgba(129, 140, 248, 0.45);
  background: rgba(99, 102, 241, 0.14);
  color: #e0e7ff;
}

.confirm-banner--sync .confirm-banner-sub {
  color: rgba(224, 231, 255, 0.85);
}

.confirm-banner--hint {
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.05);
  color: rgba(255, 255, 255, 0.88);
}

.loading, .not-found {
  text-align: center;
  padding: 48px 0;
  color: rgba(255, 255, 255, 0.5);
}

.transient-warning {
  margin: 0 0 16px;
  padding: 10px 12px;
  border: 1px solid rgba(250, 204, 21, 0.32);
  border-radius: 8px;
  background: rgba(250, 204, 21, 0.08);
  color: #fde68a;
  font-size: 12px;
  line-height: 1.5;
}

.order-info {
  padding: 24px;
  border: 0.5px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  margin-bottom: 24px;
}

.order-field {
  display: flex;
  justify-content: space-between;
  padding: 12px 0;
  border-bottom: 0.5px solid rgba(255, 255, 255, 0.06);
  font-size: 14px;
}

.order-field:last-child {
  border-bottom: none;
}

.order-field .label {
  color: rgba(255, 255, 255, 0.5);
}

.order-field .value {
  font-weight: 500;
  text-align: right;
  max-width: 60%;
  word-break: break-all;
}

.order-field .value.price {
  font-size: 18px;
  font-weight: 600;
}

.status-pending {
  color: #f0a030;
}

.status-paid {
  color: #4ade80;
}

.status-failed {
  color: #ff6b6b;
}

.status-closed {
  color: rgba(255, 255, 255, 0.4);
}

.pending-redirect-section {
  padding: 20px;
  border: 0.5px solid rgba(99, 102, 241, 0.35);
  border-radius: 12px;
  margin-bottom: 24px;
  background: rgba(99, 102, 241, 0.06);
}

.pending-redirect-title {
  margin: 0 0 10px;
  font-size: 15px;
  font-weight: 600;
  color: #e0e7ff;
}

.pending-redirect-desc {
  margin: 0 0 16px;
  font-size: 13px;
  line-height: 1.55;
  color: rgba(255, 255, 255, 0.72);
}

.pending-redirect-desc strong {
  color: rgba(255, 255, 255, 0.92);
  font-weight: 600;
}

.pending-redirect-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 12px;
}

.pending-redirect-foot {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  color: rgba(255, 255, 255, 0.42);
}

.qr-section {
  text-align: center;
  padding: 24px;
  border: 0.5px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  margin-bottom: 24px;
}

.qr-hint {
  font-size: 14px;
  color: rgba(255, 255, 255, 0.5);
  margin: 0 0 16px;
}

.qr-wrapper {
  display: inline-block;
  background: #ffffff;
  padding: 16px;
  border-radius: 12px;
}

.qr-img {
  display: block;
  width: 280px;
  height: 280px;
  max-width: 100%;
}

.qr-expired-hint {
  margin-top: 12px;
  font-size: 13px;
  color: #ff6b6b;
}

.qr-expired-hint a,
.qr-expired-hint .link-muted {
  color: rgba(255, 255, 255, 0.75);
  margin-left: 8px;
}

.btn-retry {
  margin-right: 8px;
  padding: 6px 14px;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.25);
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
  font-size: 13px;
  cursor: pointer;
}

.btn-retry:hover {
  background: rgba(255, 255, 255, 0.14);
}

.closed-section .btn-primary {
  margin-right: 8px;
}

.qr-waiting {
  margin-top: 12px;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.4);
}

.success-section {
  text-align: center;
  padding: 48px 24px;
}

.success-icon {
  width: 64px;
  height: 64px;
  line-height: 64px;
  border-radius: 50%;
  background: rgba(74, 222, 128, 0.1);
  border: 1px solid rgba(74, 222, 128, 0.3);
  font-size: 28px;
  color: #4ade80;
  margin: 0 auto 24px;
}

.success-title {
  font-size: 20px;
  font-weight: 600;
  margin: 0 0 8px;
}

.success-desc {
  font-size: 14px;
  color: rgba(255, 255, 255, 0.5);
  margin: 0 0 24px;
}

.success-actions {
  display: flex;
  gap: 12px;
  justify-content: center;
  flex-wrap: wrap;
}

.refund-hint {
  margin-top: 16px;
  color: rgba(255, 255, 255, 0.5);
  font-size: 13px;
}

.refund-link {
  color: #c7d2fe;
  text-decoration: none;
}

.refund-link:hover {
  color: #ffffff;
}

.failed-section, .closed-section {
  text-align: center;
  padding: 48px 24px;
}

.failed-section p, .closed-section p {
  font-size: 16px;
  color: #ff6b6b;
  margin: 0 0 24px;
}

.closed-section p {
  color: rgba(255, 255, 255, 0.5);
}

.error-section {
  text-align: center;
  padding: 48px 24px;
}

.error-icon {
  width: 64px;
  height: 64px;
  line-height: 64px;
  border-radius: 50%;
  background: rgba(255, 107, 107, 0.1);
  border: 1px solid rgba(255, 107, 107, 0.3);
  font-size: 28px;
  color: #ff6b6b;
  margin: 0 auto 24px;
}

.error-title {
  font-size: 20px;
  font-weight: 600;
  margin: 0 0 8px;
  color: #ff6b6b;
}

.error-desc {
  font-size: 14px;
  color: rgba(255, 255, 255, 0.75);
  margin: 0 auto 24px;
  max-width: 100%;
  text-align: left;
  line-height: 1.55;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.btn {
  display: inline-block;
  padding: 12px 24px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  text-decoration: none;
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

.btn-ghost {
  background: transparent;
  color: rgba(255, 255, 255, 0.6);
}

.btn-ghost:hover {
  color: #ffffff;
}

.spinner {
  width: 32px;
  height: 32px;
  border: 2px solid rgba(255, 255, 255, 0.1);
  border-top-color: #ffffff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin: 0 auto 12px;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 768px) {
  .checkout-page {
    padding-top: 24px;
    align-items: flex-start;
  }
  .checkout-container {
    padding: 0 12px;
  }
  .order-info {
    padding: 18px;
  }
  .order-field {
    align-items: flex-start;
    gap: 12px;
  }
  .order-field .value {
    max-width: 58vw;
    word-break: break-all;
  }
  .qr-img {
    width: min(280px, calc(100vw - 72px));
    height: min(280px, calc(100vw - 72px));
  }
  .success-actions,
  .closed-section {
    flex-direction: column;
  }
  .success-actions .btn,
  .closed-section .btn {
    width: 100%;
  }
}

html[data-workbench-theme='light'] .checkout-page {
  background: #f5f5f7;
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .checkout-title {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .confirm-banner-sub {
  color: #86868b;
}

html[data-workbench-theme='light'] .confirm-banner--success {
  border-color: rgba(34, 197, 94, 0.3);
  background: rgba(34, 197, 94, 0.08);
  color: #16a34a;
}

html[data-workbench-theme='light'] .confirm-banner--success .confirm-banner-sub {
  color: rgba(22, 163, 74, 0.75);
}

html[data-workbench-theme='light'] .confirm-banner--sync {
  border-color: rgba(99, 102, 241, 0.3);
  background: rgba(99, 102, 241, 0.06);
  color: #4f46e5;
}

html[data-workbench-theme='light'] .confirm-banner--sync .confirm-banner-sub {
  color: rgba(79, 70, 229, 0.75);
}

html[data-workbench-theme='light'] .confirm-banner--hint {
  border-color: rgba(0, 0, 0, 0.08);
  background: rgba(0, 0, 0, 0.03);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .loading,
html[data-workbench-theme='light'] .not-found {
  color: #86868b;
}

html[data-workbench-theme='light'] .transient-warning {
  border-color: rgba(234, 179, 8, 0.3);
  background: rgba(234, 179, 8, 0.06);
  color: #a16207;
}

html[data-workbench-theme='light'] .order-info {
  border-color: rgba(0, 0, 0, 0.08);
  background: #ffffff;
}

html[data-workbench-theme='light'] .order-field {
  border-bottom-color: rgba(0, 0, 0, 0.06);
}

html[data-workbench-theme='light'] .order-field .label {
  color: #86868b;
}

html[data-workbench-theme='light'] .order-field .value {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .status-pending {
  color: #d97706;
}

html[data-workbench-theme='light'] .status-paid {
  color: #16a34a;
}

html[data-workbench-theme='light'] .status-failed {
  color: #dc2626;
}

html[data-workbench-theme='light'] .status-closed {
  color: #86868b;
}

html[data-workbench-theme='light'] .pending-redirect-section {
  border-color: rgba(99, 102, 241, 0.2);
  background: rgba(99, 102, 241, 0.04);
}

html[data-workbench-theme='light'] .pending-redirect-title {
  color: #4f46e5;
}

html[data-workbench-theme='light'] .pending-redirect-desc {
  color: #86868b;
}

html[data-workbench-theme='light'] .pending-redirect-desc strong {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .pending-redirect-foot {
  color: #86868b;
}

html[data-workbench-theme='light'] .qr-section {
  border-color: rgba(0, 0, 0, 0.08);
  background: #ffffff;
}

html[data-workbench-theme='light'] .qr-hint {
  color: #86868b;
}

html[data-workbench-theme='light'] .qr-wrapper {
  background: #f5f5f7;
}

html[data-workbench-theme='light'] .qr-expired-hint {
  color: #dc2626;
}

html[data-workbench-theme='light'] .qr-expired-hint a,
html[data-workbench-theme='light'] .qr-expired-hint .link-muted {
  color: #86868b;
}

html[data-workbench-theme='light'] .btn-retry {
  border-color: rgba(0, 0, 0, 0.12);
  background: rgba(0, 0, 0, 0.04);
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .btn-retry:hover {
  background: rgba(0, 0, 0, 0.08);
}

html[data-workbench-theme='light'] .qr-waiting {
  color: #86868b;
}

html[data-workbench-theme='light'] .success-icon {
  background: rgba(34, 197, 94, 0.08);
  border-color: rgba(34, 197, 94, 0.25);
  color: #16a34a;
}

html[data-workbench-theme='light'] .success-title {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .success-desc {
  color: #86868b;
}

html[data-workbench-theme='light'] .refund-hint {
  color: #86868b;
}

html[data-workbench-theme='light'] .refund-link {
  color: #0071e3;
}

html[data-workbench-theme='light'] .refund-link:hover {
  color: #005bb5;
}

html[data-workbench-theme='light'] .failed-section p,
html[data-workbench-theme='light'] .closed-section p {
  color: #dc2626;
}

html[data-workbench-theme='light'] .closed-section p {
  color: #86868b;
}

html[data-workbench-theme='light'] .error-icon {
  background: rgba(220, 38, 38, 0.08);
  border-color: rgba(220, 38, 38, 0.25);
  color: #dc2626;
}

html[data-workbench-theme='light'] .error-title {
  color: #dc2626;
}

html[data-workbench-theme='light'] .error-desc {
  color: #86868b;
}

html[data-workbench-theme='light'] .btn-primary {
  background: #0071e3;
  color: #ffffff;
}

html[data-workbench-theme='light'] .btn-primary:hover {
  background: #005bb5;
  opacity: 1;
}

html[data-workbench-theme='light'] .btn-ghost {
  color: #86868b;
}

html[data-workbench-theme='light'] .btn-ghost:hover {
  color: #1d1d1f;
}

html[data-workbench-theme='light'] .spinner {
  border-color: rgba(0, 0, 0, 0.08);
  border-top-color: #0071e3;
}
</style>
