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
/* 以下类与 XCmaxAdminView.vue 的 scoped 样式同名，但 Vue scoped 不会注入父级 scope 属性，
   必须在本组件内显式补齐，否则订单面板的卡片/标题/按钮等失去样式。 */
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
  flex-wrap: wrap;
  gap: 12px;
}
.page-header h2 {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  color: #172033;
}
.header-actions {
  display: flex;
  gap: 10px;
}
.admin-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 18px;
}
.admin-card {
  background: rgba(255, 255, 255, 0.92);
  border-radius: 16px;
  border: 1px solid rgba(15, 76, 129, 0.1);
  box-shadow: 0 4px 18px rgba(15, 76, 129, 0.07);
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.card-header {
  display: flex;
  align-items: center;
  gap: 10px;
}
.card-header h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: #172033;
  flex: 1;
}
.card-icon {
  font-size: 18px;
  color: #1890ff;
  width: 22px;
  text-align: center;
}
.card-info {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 6px 14px;
  margin: 0;
  font-size: 13px;
}
.card-info dt {
  color: rgba(23, 32, 51, 0.55);
  font-weight: 600;
  white-space: nowrap;
}
.card-info dd {
  margin: 0;
  color: #172033;
  word-break: break-all;
}
.status-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 10px;
  border-radius: 20px;
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
}
.badge-ok { background: #e6f9f0; color: #10b759; }
.badge-warn { background: #fff7e0; color: #d97706; }
.badge-err { background: #fff1f0; color: #e53e3e; }
.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 8px;
  border: none;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
}
.btn:disabled { opacity: 0.55; cursor: not-allowed; }
.btn-secondary { background: rgba(24, 144, 255, 0.1); color: #1890ff; }
.btn-secondary:not(:disabled):hover { background: rgba(24, 144, 255, 0.18); }

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