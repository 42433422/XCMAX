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
          <div class="order-field">
            <span class="label">退款状态</span>
            <span class="value">{{ refundStatusText(order.refund_status) }}</span>
          </div>
          <div class="order-field">
            <span class="label">已退金额</span>
            <span class="value">¥{{ money(order.refunded_amount) }}</span>
          </div>
        </div>

        <div class="actions">
          <router-link to="/plans" class="btn btn-primary">返回套餐页</router-link>
          <router-link :to="{ name: 'wallet-purchased' }" class="btn btn-ghost">已购资产</router-link>
          <button
            v-if="order.status === 'paid'"
            type="button"
            class="btn btn-refund"
            @click="goRefund"
          >
            申请退款
          </button>
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
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'

const route = useRoute()
const router = useRouter()
const orderParamId = computed(() => {
  const p = route.params.orderId
  const v = Array.isArray(p) ? p[0] : p
  return v == null ? '' : String(v)
})
interface OrderDetail {
  out_trade_no?: string
  subject?: string
  total_amount?: number | string
  status?: string
  trade_no?: string
  created_at?: string
  paid_at?: string
  refund_status?: string
  refunded_amount?: number | string
}

const order = ref<OrderDetail | null>(null)
const loading = ref(true)

onMounted(async () => {
  try {
    const res = (await api.paymentQuery(orderParamId.value, { reconcile: true })) as OrderDetail
    order.value = res
  } catch {
    order.value = null
  } finally {
    loading.value = false
  }
})

function statusText(status: string | undefined): string {
  const map: Record<string, string> = {
    pending: '待支付',
    paid: '已支付',
    refunding: '退款中',
    refunded: '已退款',
    partial_refunded: '部分退款',
    failed: '支付失败',
    closed: '已关闭',
  }
  return (status && map[status]) || status || '未知'
}

function refundStatusText(status: string | undefined): string {
  const map: Record<string, string> = {
    none: '无退款',
    pending: '审核中',
    rejected: '已拒绝',
    refunded: '已退回钱包',
    partial_refunded: '部分退回钱包',
  }
  return (status && map[status]) || status || '无退款'
}

function money(value: unknown): string {
  const n = Number(value)
  return Number.isFinite(n) ? n.toFixed(2) : '0.00'
}

function formatTime(iso: string | undefined): string {
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

function goRefund() {
  if (!order.value?.out_trade_no) return
  router.push({ name: 'refunds', query: { order_no: order.value.out_trade_no } })
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

.status-refunding {
  color: #c7d2fe;
}

.status-refunded,
.status-partial_refunded {
  color: #93c5fd;
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

.btn-refund {
  background: rgba(99, 102, 241, 0.15);
  border: 1px solid rgba(129, 140, 248, 0.45);
  color: #c7d2fe;
}

.btn-refund:hover {
  border-color: rgba(199, 210, 254, 0.8);
}

@media (max-width: 768px) {
  .order-detail-page {
    padding-top: 24px;
    align-items: flex-start;
  }
  .order-container {
    padding: 0 12px;
  }
  .order-card {
    padding: 18px;
  }
  .order-field {
    align-items: flex-start;
    gap: 12px;
  }
  .order-field .value {
    max-width: 58vw;
  }
  .actions .btn {
    width: 100%;
    text-align: center;
  }
}

html[data-workbench-theme='light'] .order-detail-page {
  background: #f5f5f7;
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .loading,
html[data-workbench-theme='light'] .not-found {
  color: #86868b;
}
html[data-workbench-theme='light'] .order-card {
  background: #ffffff;
  border-color: rgba(0, 0, 0, 0.06);
}
html[data-workbench-theme='light'] .order-field {
  border-bottom-color: rgba(0, 0, 0, 0.06);
}
html[data-workbench-theme='light'] .order-field .label {
  color: #86868b;
}
html[data-workbench-theme='light'] .status-pending {
  color: #c47f17;
}
html[data-workbench-theme='light'] .status-paid {
  color: #248a3d;
}
html[data-workbench-theme='light'] .status-refunding {
  color: #6366f1;
}
html[data-workbench-theme='light'] .status-refunded,
html[data-workbench-theme='light'] .status-partial_refunded {
  color: #0071e3;
}
html[data-workbench-theme='light'] .status-failed {
  color: #d32f2f;
}
html[data-workbench-theme='light'] .status-closed {
  color: #86868b;
}
html[data-workbench-theme='light'] .btn-primary {
  background: #0071e3;
  color: #ffffff;
}
html[data-workbench-theme='light'] .btn-primary:hover {
  opacity: 0.85;
}
html[data-workbench-theme='light'] .btn-ghost {
  color: #86868b;
}
html[data-workbench-theme='light'] .btn-ghost:hover {
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .btn-refund {
  background: rgba(0, 113, 227, 0.08);
  border-color: rgba(0, 113, 227, 0.3);
  color: #0071e3;
}
html[data-workbench-theme='light'] .btn-refund:hover {
  border-color: rgba(0, 113, 227, 0.6);
}
</style>
