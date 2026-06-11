<template>
  <div class="checkout-page">
    <div class="checkout-container">
      <h1 class="checkout-title">支付订单</h1>

      <div v-if="loading" class="loading">
        <div class="spinner"></div>
        <p>加载订单信息...</p>
      </div>

      <template v-else-if="order">
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
            订单已超时未支付，<router-link to="/plans">重新下单</router-link>
          </p>
          <p v-else class="qr-waiting">等待支付中，支付成功后自动跳转...</p>
        </div>

        <!-- 已支付成功 -->
        <div v-if="order.status === 'paid'" class="success-section">
          <div class="success-icon">✓</div>
          <h2 class="success-title">支付成功</h2>
          <p class="success-desc">权益已发放，请前往"我的商店"查看</p>
          <div class="success-actions">
            <router-link to="/my-store" class="btn btn-primary">查看我的商店</router-link>
            <router-link to="/plans" class="btn btn-ghost">继续选购</router-link>
          </div>
        </div>

        <!-- 支付失败 -->
        <div v-if="order.status === 'failed'" class="failed-section">
          <p>支付失败</p>
          <router-link to="/plans" class="btn btn-primary">重新下单</router-link>
        </div>

        <!-- 已关闭 -->
        <div v-if="order.status === 'closed'" class="closed-section">
          <p>订单已关闭</p>
          <router-link to="/plans" class="btn btn-primary">返回套餐页</router-link>
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
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api'

const route = useRoute()
const order = ref<any>(null)
const loading = ref(true)
const qrCode = ref('')
const pollingTimer = ref<ReturnType<typeof setInterval> | null>(null)

function orderId(): string {
  const raw = route.params.orderId
  return Array.isArray(raw) ? String(raw[0] ?? '') : String(raw ?? '')
}

const qrImageUrl = computed(() => {
  if (!qrCode.value) return ''
  return `https://api.qrserver.com/v1/create-qr-code/?size=280x280&margin=8&data=${encodeURIComponent(qrCode.value)}`
})

const isExpired = computed(() => {
  if (!order.value || order.value.status !== 'pending') return false
  const created = new Date(order.value.created_at).getTime()
  const now = Date.now()
  return (now - created) > 15 * 60 * 1000
})

onMounted(async () => {
  await fetchOrder()
  if (order.value && order.value.status === 'pending' && !isExpired.value) {
    pollingTimer.value = setInterval(pollOrder, 3000)
  }
})

onBeforeUnmount(() => {
  if (pollingTimer.value) {
    clearInterval(pollingTimer.value)
  }
})

async function fetchOrder() {
  try {
    const res = await api.paymentQuery(orderId())
    order.value = res

    if (res.qr_code) {
      qrCode.value = String(res.qr_code)
    }

    if (res.status === 'paid' && pollingTimer.value) {
      clearInterval(pollingTimer.value)
      pollingTimer.value = null
    }
  } catch {
    order.value = null
  } finally {
    loading.value = false
  }
}

async function pollOrder() {
  try {
    const res = await api.paymentQuery(orderId())
    order.value = res
    if (res.qr_code) qrCode.value = String(res.qr_code)

    if (res.status === 'paid' && pollingTimer.value) {
      clearInterval(pollingTimer.value)
      pollingTimer.value = null
    }
  } catch {
    // ignore polling errors
  }
}

function statusText(status) {
  const map = {
    pending: '待支付',
    paid: '已支付',
    failed: '支付失败',
    closed: '已关闭',
  }
  return map[status] || status || '未知'
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

.loading, .not-found {
  text-align: center;
  padding: 48px 0;
  color: rgba(255, 255, 255, 0.5);
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

.qr-expired-hint a {
  color: #ffffff;
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
    padding-top: 64px;
  }
}
</style>
