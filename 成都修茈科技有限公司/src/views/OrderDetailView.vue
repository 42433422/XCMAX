<template>
  <div class="order-detail-page">
    <div class="order-container">
      <h1 class="page-title">订单详情</h1>

      <div v-if="loading" class="loading">加载中...</div>

      <template v-else-if="order">
        <div class="order-card">
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
          <div class="order-field">
            <span class="label">支付宝交易号</span>
            <span class="value">{{ order.trade_no || '—' }}</span>
          </div>
          <div class="order-field">
            <span class="label">创建时间</span>
            <span class="value">{{ formatTime(order.created_at) }}</span>
          </div>
          <div class="order-field">
            <span class="label">支付时间</span>
            <span class="value">{{ order.paid_at ? formatTime(order.paid_at) : '—' }}</span>
          </div>
        </div>

        <div class="actions">
          <router-link to="/plans" class="btn btn-primary">返回套餐页</router-link>
          <router-link to="/my-store" class="btn btn-ghost">我的商店</router-link>
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
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api'

const route = useRoute()
const order = ref<any>(null)
const loading = ref(true)

function orderId(): string {
  const raw = route.params.orderId
  return Array.isArray(raw) ? String(raw[0] ?? '') : String(raw ?? '')
}

onMounted(async () => {
  try {
    const res = await api.paymentQuery(orderId())
    order.value = res
  } catch {
    order.value = null
  } finally {
    loading.value = false
  }
})

function statusText(status: string | null | undefined): string {
  const map: Record<string, string> = {
    pending: '待支付',
    paid: '已支付',
    failed: '支付失败',
    closed: '已关闭',
  }
  return map[status || ''] || status || '未知'
}

function formatTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}
</script>

<style scoped>
.order-detail-page {
  min-height: 100vh;
  background: #0a0a0a;
  color: #ffffff;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
  display: flex;
  justify-content: center;
  padding-top: 80px;
}

.order-container {
  width: 100%;
  max-width: 480px;
  padding: 0 24px;
}

.page-title {
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

.order-card {
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

.actions {
  display: flex;
  gap: 12px;
  justify-content: center;
  flex-wrap: wrap;
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

@media (max-width: 768px) {
  .order-detail-page {
    padding-top: 64px;
  }
}
</style>
