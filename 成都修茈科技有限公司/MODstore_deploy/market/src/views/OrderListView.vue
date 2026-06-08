<template>
  <div class="order-list-page">
    <div class="order-list-page__head">
      <h2 class="page-title">我的订单</h2>
      <div class="order-list-toolbar" v-if="!loading && orders.length">
        <button
          type="button"
          class="btn btn-ghost order-dismiss-btn"
          :disabled="dismissing"
          @click="dismissNonActive"
        >
          {{ dismissing ? '处理中…' : '清理展示' }}
        </button>
        <span class="order-list-toolbar__hint" title="隐藏已关闭/失败/已退款等，保留待付、已付、退款中"
          >从列表隐藏终态</span
        >
      </div>
    </div>
    <div v-if="err" class="err">{{ err }}</div>
    <div v-if="loading" class="loading">加载中…</div>

    <div v-else>
      <div class="order-filters">
        <button
          v-for="f in filters"
          :key="f.value"
          type="button"
          :class="['filter-btn', { active: currentFilter === f.value }]"
          @click="setFilter(f.value)"
        >
          {{ f.label }}
        </button>
      </div>

      <div v-if="!orders.length" class="empty">暂无订单</div>
      <div v-else class="order-list">
        <div
          v-for="order in orders"
          :key="order.out_trade_no"
          class="order-card"
          @click="goDetail(order)"
        >
          <div class="order-header">
            <span class="order-no">{{ order.out_trade_no }}</span>
            <span :class="['order-status', order.status]">{{ statusText(order.status) }}</span>
          </div>
          <div class="order-body">
            <span class="order-subject">{{ order.subject }}</span>
            <span class="order-amount">¥{{ order.total_amount }}</span>
          </div>
          <div class="order-footer">
            <span class="order-time">{{ formatTime(order.created_at) }}</span>
            <button
              v-if="order.status === 'pending'"
              type="button"
              class="btn-cancel"
              @click.stop="cancelOrder(order)"
            >
              取消
            </button>
            <button
              v-if="order.status === 'paid'"
              type="button"
              class="btn-refund"
              @click.stop="goRefund(order)"
            >
              申请退款
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'

interface OrderRow {
  out_trade_no: string
  status?: string
  subject?: string
  total_amount?: number | string
  created_at?: string
}

const router = useRouter()
const orders = ref<OrderRow[]>([])
const loading = ref(true)
const dismissing = ref(false)
const err = ref('')
const currentFilter = ref('')

const filters = [
  { value: '', label: '全部' },
  { value: 'pending', label: '待支付' },
  { value: 'paid', label: '已支付' },
  { value: 'closed', label: '已关闭' },
]

function statusText(s: string | undefined): string {
  const m: Record<string, string> = {
    pending: '待支付',
    paid: '已支付',
    refunding: '退款中',
    refunded: '已退款',
    partial_refunded: '部分退款',
    failed: '失败',
    closed: '已关闭',
  }
  return (s && m[s]) || s || '—'
}

function formatTime(iso: string | undefined): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return String(iso)
  }
}

async function load() {
  loading.value = true
  err.value = ''
  try {
    const res = await api.paymentOrders(currentFilter.value || undefined)
    orders.value = res.orders || []
  } catch (e) {
    err.value = (e as Error)?.message || String(e)
  } finally {
    loading.value = false
  }
}

async function dismissNonActive() {
  if (dismissing.value) return
  if (!confirm('将已关闭/失败/已退款等从本列表中隐藏（不删单），并保留待支付、已支付、退款中。是否继续？')) return
  dismissing.value = true
  err.value = ''
  try {
    const res = await api.paymentDismissNonActiveOrders()
    if (res?.ok === false) {
      err.value = res?.message || '操作失败'
      return
    }
    await load()
  } catch (e) {
    err.value = (e as Error)?.message || String(e)
  } finally {
    dismissing.value = false
  }
}

function setFilter(v: string) {
  currentFilter.value = v
  void load()
}

function goDetail(order: OrderRow) {
  router.push({ name: 'order-detail', params: { orderId: order.out_trade_no } })
}

function goRefund(order: OrderRow) {
  router.push({ name: 'refunds', query: { order_no: order.out_trade_no } })
}

async function cancelOrder(order: OrderRow) {
  if (!confirm('确定取消该待支付订单？')) return
  try {
    await api.paymentCancelOrder(order.out_trade_no)
    await load()
  } catch (e) {
    alert((e as Error)?.message || String(e))
  }
}

onMounted(() => void load())
</script>

<style scoped>
.order-list-page {
  max-width: 720px;
  margin: 0 auto;
  padding: 80px 20px 40px;
  min-height: 100vh;
  background: #0a0a0a;
  color: #fff;
}
.order-list-page__head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px 16px;
  margin-bottom: 20px;
}
.page-title {
  margin: 0;
  font-size: 1.5rem;
}
.order-list-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 10px;
}
.order-dismiss-btn {
  font-size: 12px;
  padding: 6px 12px;
}
.order-list-toolbar__hint {
  font-size: 11px;
  color: #71717a;
  max-width: 200px;
  line-height: 1.3;
}
.err {
  color: #f87171;
  margin-bottom: 12px;
}
.loading {
  color: #a1a1aa;
}
.order-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 20px;
}
.filter-btn {
  padding: 8px 14px;
  border-radius: 8px;
  border: 1px solid #3f3f46;
  background: transparent;
  color: #d4d4d8;
  cursor: pointer;
}
.filter-btn.active {
  border-color: #6366f1;
  background: rgba(99, 102, 241, 0.15);
  color: #fff;
}
.order-card {
  background: #141414;
  border: 1px solid #27272a;
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 12px;
  cursor: pointer;
}
.order-card:hover {
  border-color: #3f3f46;
}
.order-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.order-no {
  font-family: ui-monospace, monospace;
  font-size: 0.85rem;
  color: #a1a1aa;
}
.order-status {
  font-size: 0.85rem;
  padding: 2px 8px;
  border-radius: 6px;
  background: #27272a;
}
.order-status.paid {
  color: #86efac;
}
.order-status.pending {
  color: #fde047;
}
.order-body {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 12px;
}
.order-subject {
  font-weight: 600;
}
.order-amount {
  color: #a5b4fc;
  font-weight: 600;
}
.order-footer {
  margin-top: 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.order-time {
  font-size: 0.8rem;
  color: #71717a;
}
.btn-cancel,
.btn-refund {
  padding: 6px 12px;
  font-size: 0.85rem;
  border-radius: 6px;
  border: 1px solid #52525b;
  background: transparent;
  color: #e4e4e7;
  cursor: pointer;
}
.btn-refund {
  border-color: #6366f1;
  color: #c7d2fe;
}
.empty {
  color: #71717a;
  text-align: center;
  padding: 40px 0;
}

@media (max-width: 640px) {
  .order-list-page {
    padding: 24px 12px 32px;
  }
  .order-header,
  .order-body,
  .order-footer {
    align-items: flex-start;
    flex-direction: column;
  }
  .order-no {
    max-width: 100%;
    word-break: break-all;
  }
  .btn-cancel,
  .btn-refund {
    width: 100%;
    min-height: 40px;
  }
}

html[data-workbench-theme='light'] .order-list-page {
  background: #f5f5f7;
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .order-list-toolbar__hint {
  color: #86868b;
}
html[data-workbench-theme='light'] .err {
  color: #d32f2f;
}
html[data-workbench-theme='light'] .loading {
  color: #86868b;
}
html[data-workbench-theme='light'] .filter-btn {
  border-color: rgba(0, 0, 0, 0.1);
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .filter-btn.active {
  border-color: #0071e3;
  background: rgba(0, 113, 227, 0.08);
  color: #0071e3;
}
html[data-workbench-theme='light'] .order-card {
  background: #ffffff;
  border-color: rgba(0, 0, 0, 0.06);
}
html[data-workbench-theme='light'] .order-card:hover {
  border-color: rgba(0, 0, 0, 0.15);
}
html[data-workbench-theme='light'] .order-no {
  color: #86868b;
}
html[data-workbench-theme='light'] .order-status {
  background: rgba(0, 0, 0, 0.05);
}
html[data-workbench-theme='light'] .order-status.paid {
  color: #248a3d;
}
html[data-workbench-theme='light'] .order-status.pending {
  color: #c47f17;
}
html[data-workbench-theme='light'] .order-amount {
  color: #0071e3;
}
html[data-workbench-theme='light'] .order-time {
  color: #86868b;
}
html[data-workbench-theme='light'] .btn-cancel,
html[data-workbench-theme='light'] .btn-refund {
  border-color: rgba(0, 0, 0, 0.12);
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .btn-refund {
  border-color: #0071e3;
  color: #0071e3;
}
html[data-workbench-theme='light'] .empty {
  color: #86868b;
}
</style>
