<template>
  <div class="admin-orders-tab">
    <div class="page-header">
      <h2>订单经营</h2>
      <div class="header-actions">
        <select v-model="statusFilter" class="form-control" @change="loadOrders">
          <option value="">全部状态</option>
          <option value="paid">已支付</option>
          <option value="pending">待支付</option>
          <option value="closed">已关闭</option>
          <option value="refunded">已退款</option>
        </select>
        <button class="btn btn-secondary" type="button" :disabled="loading" @click="loadOrders">
          <i class="fa fa-refresh" :class="{ 'fa-spin': loading }" aria-hidden="true"></i>
          {{ loading ? '加载中...' : '刷新' }}
        </button>
      </div>
    </div>

    <div class="admin-grid">
      <div class="admin-card">
        <div class="card-header">
          <i class="fa fa-shopping-cart card-icon" aria-hidden="true"></i>
          <h3>总订单</h3>
        </div>
        <dl class="card-info">
          <dt>合计</dt><dd>{{ summary.total_orders ?? '—' }}</dd>
          <dt>数据源</dt><dd>{{ source || '—' }}</dd>
        </dl>
      </div>
      <div class="admin-card">
        <div class="card-header">
          <i class="fa fa-check card-icon" aria-hidden="true"></i>
          <h3>已支付</h3>
        </div>
        <dl class="card-info">
          <dt>笔数</dt><dd>{{ summary.paid_orders ?? '—' }}</dd>
          <dt>收入</dt><dd>¥{{ formatAmount(summary.paid_revenue) }}</dd>
        </dl>
      </div>
      <div class="admin-card">
        <div class="card-header">
          <i class="fa fa-clock-o card-icon" aria-hidden="true"></i>
          <h3>待支付</h3>
        </div>
        <dl class="card-info">
          <dt>笔数</dt><dd>{{ summary.pending_orders ?? '—' }}</dd>
        </dl>
      </div>
      <div class="admin-card">
        <div class="card-header">
          <i class="fa fa-list card-icon" aria-hidden="true"></i>
          <h3>状态分布</h3>
        </div>
        <dl class="card-info">
          <template v-for="(count, st) in summary.by_status" :key="String(st)">
            <dt>{{ st }}</dt>
            <dd>{{ count }}</dd>
          </template>
          <template v-if="!summary.by_status || Object.keys(summary.by_status).length === 0">
            <dt>暂无</dt><dd>0</dd>
          </template>
        </dl>
      </div>
    </div>

    <div class="admin-card">
      <div class="card-header">
        <i class="fa fa-table card-icon" aria-hidden="true"></i>
        <h3>订单列表</h3>
        <span class="status-badge">{{ orders.length }} / {{ total }}</span>
      </div>
      <table class="order-table">
        <thead>
          <tr>
            <th>订单号</th>
            <th>商品</th>
            <th>金额</th>
            <th>用户ID</th>
            <th>状态</th>
            <th>创建时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="o in orders" :key="String(o.out_trade_no || o.order_no || o.id)">
            <td class="mono small">{{ o.out_trade_no || o.order_no || o.id }}</td>
            <td>{{ o.subject }}</td>
            <td>¥{{ formatAmount(o.total_amount) }}</td>
            <td>{{ o.user_id }}</td>
            <td><span :class="['status-badge', statusClass(o.status)]">{{ o.status }}</span></td>
            <td class="small">{{ o.created_at }}</td>
          </tr>
          <tr v-if="!orders.length && !loading">
            <td colspan="6" class="empty-cell">{{ error || '暂无订单数据' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { xcmaxAdminApi } from '@/api/xcmaxAdmin'

type OrderRow = Record<string, unknown>

const orders = ref<OrderRow[]>([])
const total = ref(0)
const summary = ref<Record<string, unknown>>({})
const source = ref('')
const statusFilter = ref('')
const loading = ref(false)
const error = ref('')

function formatAmount(value: unknown): string {
  if (value == null || value === '') return '—'
  return Number(value).toFixed(2)
}

function statusClass(status: unknown): string {
  const s = String(status || '')
  if (s === 'paid') return 'badge-ok'
  if (s === 'pending') return 'badge-warn'
  return 'badge-err'
}

async function loadOrders() {
  loading.value = true
  error.value = ''
  try {
    const res = await xcmaxAdminApi.listOrders({
      status: statusFilter.value || undefined,
      limit: 200,
    })
    orders.value = Array.isArray(res?.items) ? (res.items as OrderRow[]) : []
    total.value = Number(res?.total ?? 0)
    summary.value = (res?.summary as Record<string, unknown>) ?? {}
    source.value = String(res?.source ?? '')
  } catch (e) {
    error.value = `订单数据加载失败：${(e as Error)?.message || String(e)}`
  } finally {
    loading.value = false
  }
}

onMounted(loadOrders)
</script>

<style scoped>
.order-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 0.5rem;
}
.order-table th,
.order-table td {
  text-align: left;
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--border-color, rgba(0, 0, 0, 0.08));
  font-size: 0.85rem;
}
.order-table th {
  font-weight: 600;
  color: var(--text-muted, #666);
}
.empty-cell {
  text-align: center;
  color: var(--text-muted, #999);
  padding: 1.5rem;
}
</style>