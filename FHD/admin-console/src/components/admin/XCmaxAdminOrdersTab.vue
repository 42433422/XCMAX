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
            <th>经营操作</th>
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
            <td class="order-actions">
              <button v-if="String(o.status) === 'pending'" type="button" class="btn-mini" :disabled="busyOrder === orderNo(o)" @click="reprice(o)">改价</button>
              <button v-if="String(o.status) === 'pending'" type="button" class="btn-mini is-danger" :disabled="busyOrder === orderNo(o)" @click="cancel(o)">取消</button>
              <button v-if="String(o.status) === 'paid'" type="button" class="btn-mini is-warn" :disabled="busyOrder === orderNo(o)" @click="requestRefund(o)">申请退款</button>
              <span v-if="!['pending', 'paid'].includes(String(o.status))" class="small">终态只读</span>
            </td>
          </tr>
          <tr v-if="!orders.length && !loading">
            <td colspan="7" class="empty-cell">{{ error || '暂无订单数据' }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="admin-card">
      <div class="card-header">
        <i class="fa fa-undo card-icon" aria-hidden="true"></i>
        <h3>退款审核</h3>
        <span class="status-badge" :class="pendingRefunds.length ? 'badge-warn' : 'badge-ok'">{{ pendingRefunds.length }} 待审</span>
      </div>
      <table class="order-table">
        <thead><tr><th>订单号</th><th>金额</th><th>原因</th><th>申请时间</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="refund in pendingRefunds" :key="String(refund.id)">
            <td class="mono small">{{ refund.order_no }}</td>
            <td>¥{{ formatAmount(refund.amount) }}</td>
            <td>{{ refund.reason }}</td>
            <td class="small">{{ refund.created_at }}</td>
            <td class="order-actions">
              <button type="button" class="btn-mini is-danger" :disabled="busyRefund === Number(refund.id)" @click="reviewRefund(refund, 'approve')">通过并执行</button>
              <button type="button" class="btn-mini" :disabled="busyRefund === Number(refund.id)" @click="reviewRefund(refund, 'reject')">驳回</button>
            </td>
          </tr>
          <tr v-if="!pendingRefunds.length"><td colspan="5" class="empty-cell">暂无待审退款</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { xcmaxAdminApi } from '@/api/xcmaxAdmin'
import { appAlert, appConfirm, appPrompt } from '@/utils/appDialog'

type OrderRow = Record<string, unknown>

const orders = ref<OrderRow[]>([])
const total = ref(0)
const summary = ref<Record<string, unknown>>({})
const source = ref('')
const statusFilter = ref('')
const loading = ref(false)
const error = ref('')
const pendingRefunds = ref<OrderRow[]>([])
const busyOrder = ref('')
const busyRefund = ref<number | null>(null)

function orderNo(order: OrderRow): string {
  return String(order.out_trade_no || order.order_no || order.id || '')
}

function idempotencyKey(prefix: string): string {
  const suffix = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `${prefix}:${suffix}`
}

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
    const [res, refunds] = await Promise.all([
      xcmaxAdminApi.listOrders({ status: statusFilter.value || undefined, limit: 200 }),
      xcmaxAdminApi.listPendingRefunds().catch(() => ({ refunds: [] })),
    ])
    orders.value = Array.isArray(res?.items) ? (res.items as OrderRow[]) : []
    total.value = Number(res?.total ?? 0)
    summary.value = (res?.summary as Record<string, unknown>) ?? {}
    source.value = String(res?.source ?? '')
    pendingRefunds.value = Array.isArray(refunds?.refunds) ? refunds.refunds as OrderRow[] : []
  } catch (e) {
    error.value = `订单数据加载失败：${(e as Error)?.message || String(e)}`
  } finally {
    loading.value = false
  }
}

async function cancel(order: OrderRow) {
  const no = orderNo(order)
  const reason = await appPrompt('请填写取消原因（至少 4 个字）', '', { title: '取消待支付订单' })
  if (!reason) return
  const confirmed = await appConfirm(`确认关闭订单 ${no}？\n\n后端会先关闭支付平台交易，关单失败时不会修改本地订单。`, { title: '确认取消', confirmText: '关闭订单' })
  if (!confirmed) return
  busyOrder.value = no
  try {
    await xcmaxAdminApi.cancelOrder(no, reason, idempotencyKey(`cancel:${no}`))
    await loadOrders()
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : String(e), { title: '取消失败' })
  } finally { busyOrder.value = '' }
}

async function reprice(order: OrderRow) {
  const no = orderNo(order)
  const amountText = await appPrompt(`原金额 ¥${formatAmount(order.total_amount)}，请输入新金额`, '', { title: '人工改价' })
  if (amountText == null) return
  const newAmount = Number(amountText)
  if (!Number.isFinite(newAmount) || newAmount <= 0) {
    await appAlert('新金额必须大于 0')
    return
  }
  const reason = await appPrompt('请填写改价原因（至少 4 个字）', '', { title: '改价审计' })
  if (!reason) return
  const confirmed = await appConfirm('改价不会篡改原支付单：系统会关闭旧交易，并创建一张新金额订单。是否继续？', { title: '确认改价', confirmText: '创建替代订单' })
  if (!confirmed) return
  busyOrder.value = no
  try {
    const result = await xcmaxAdminApi.repriceOrder(no, newAmount, reason, idempotencyKey(`reprice:${no}`))
    if (result?.partial_success || result?.ok === false) {
      await appAlert(String(result?.message || '旧订单已关闭，但新支付单创建失败'), { title: '改价部分成功' })
    }
    await loadOrders()
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : String(e), { title: '改价失败' })
  } finally { busyOrder.value = '' }
}

async function requestRefund(order: OrderRow) {
  const no = orderNo(order)
  const reason = await appPrompt('请填写退款原因（至少 5 个字）', '', { title: '发起退款审核' })
  if (!reason) return
  const confirmed = await appConfirm(`这一步只创建退款审批，不会立即退款。\n\n订单：${no}\n金额：¥${formatAmount(order.total_amount)}`, { title: '确认发起', confirmText: '进入退款审批' })
  if (!confirmed) return
  busyOrder.value = no
  try {
    await xcmaxAdminApi.requestOrderRefund(no, reason, idempotencyKey(`refund:${no}`))
    await loadOrders()
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : String(e), { title: '退款申请失败' })
  } finally { busyOrder.value = '' }
}

async function reviewRefund(refund: OrderRow, action: 'approve' | 'reject') {
  const id = Number(refund.id)
  const note = await appPrompt(action === 'approve' ? '请填写审批备注' : '请填写驳回原因', '', { title: action === 'approve' ? '退款审批' : '驳回退款' })
  if (note == null) return
  const confirmed = await appConfirm(
    action === 'approve'
      ? `通过后会真实执行退款并撤销对应权益。\n\n订单：${refund.order_no}\n金额：¥${formatAmount(refund.amount)}`
      : `确认驳回订单 ${refund.order_no} 的退款申请？`,
    { title: action === 'approve' ? '最后确认' : '确认驳回', confirmText: action === 'approve' ? '执行退款' : '驳回' },
  )
  if (!confirmed) return
  busyRefund.value = id
  try {
    await xcmaxAdminApi.reviewRefund(id, action, note)
    await loadOrders()
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : String(e), { title: '退款审核失败' })
  } finally { busyRefund.value = null }
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
.order-actions { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.btn-mini { border: 1px solid #b8d2ec; border-radius: 7px; background: #eef6ff; color: #1769b0; padding: 5px 8px; font-size: 11px; font-weight: 700; cursor: pointer; }
.btn-mini.is-danger { border-color: #efb7b7; background: #fff2f2; color: #c73a3a; }
.btn-mini.is-warn { border-color: #e8c48d; background: #fff8e9; color: #a96516; }
.btn-mini:disabled { opacity: .5; cursor: wait; }
</style>
