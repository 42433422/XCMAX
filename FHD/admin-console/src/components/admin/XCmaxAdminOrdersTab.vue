<template>
  <div class="admin-orders-tab">
    <div class="ot-head">
      <div class="ot-head__title">
        <h2>订单经营</h2>
        <span class="ot-head__meta">数据源 {{ source || '—' }} · 已加载 {{ orders.length }} / 共 {{ total }}</span>
      </div>
      <div class="ot-head__actions">
        <el-select v-model="statusFilter" size="small" class="ot-status-select" aria-label="订单状态" @change="loadOrders">
          <el-option label="全部状态" value="" />
          <el-option label="已支付" value="paid" />
          <el-option label="待支付" value="pending" />
          <el-option label="已关闭" value="closed" />
          <el-option label="已退款" value="refunded" />
        </el-select>
        <el-button size="small" :loading="loading" @click="loadOrders">刷新</el-button>
      </div>
    </div>

    <div class="ot-kpis" role="list" aria-label="订单经营指标">
      <article class="ot-kpi" role="listitem">
        <span class="ot-kpi__label">总订单</span>
        <strong class="ot-kpi__value">{{ summary.total_orders ?? '—' }}</strong>
        <span class="ot-kpi__hint">全部状态合计</span>
      </article>
      <article class="ot-kpi" role="listitem">
        <span class="ot-kpi__label">已支付</span>
        <strong class="ot-kpi__value">{{ summary.paid_orders ?? '—' }} <small>笔</small></strong>
        <span class="ot-kpi__hint">收入 ¥{{ formatAmount(summary.paid_revenue) }}</span>
      </article>
      <article class="ot-kpi" role="listitem">
        <span class="ot-kpi__label">待支付</span>
        <strong class="ot-kpi__value">{{ summary.pending_orders ?? '—' }} <small>笔</small></strong>
        <span class="ot-kpi__hint">需跟进改价或关单</span>
      </article>
      <article class="ot-kpi ot-kpi--wide" role="listitem">
        <span class="ot-kpi__label">状态分布</span>
        <div class="ot-kpi__tags">
          <template v-if="statusEntries.length">
            <el-tag v-for="[st, count] in statusEntries" :key="st" size="small" :type="tagType(st)" effect="light">
              {{ statusLabel(st) }} {{ count }}
            </el-tag>
          </template>
          <span v-else class="ot-kpi__hint">暂无</span>
        </div>
      </article>
    </div>

    <el-alert v-if="error" class="ot-alert" type="error" show-icon :closable="false" :title="error" />

    <AdminSectionNav v-model="section" label="订单分区" :items="[{ value: 'orders', label: '订单列表' }, { value: 'refunds', label: '退款审核' }]" />

    <section v-show="section === 'orders'" class="ot-card" aria-label="订单列表">
      <div class="ot-card__head">
        <h3>订单列表</h3>
        <span class="ot-card__count">{{ orders.length }} / {{ total }}</span>
      </div>
      <div class="ot-table-wrap">
        <el-table :data="orders" height="100%" size="small" row-key="id" class="ot-table">
          <el-table-column label="订单号" min-width="180" show-overflow-tooltip>
            <template #default="{ row }"><span class="mono">{{ orderNo(row) }}</span></template>
          </el-table-column>
          <el-table-column label="商品" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">{{ row.subject || '—' }}</template>
          </el-table-column>
          <el-table-column label="金额" width="110" align="right">
            <template #default="{ row }"><span class="mono">¥{{ formatAmount(row.total_amount) }}</span></template>
          </el-table-column>
          <el-table-column label="用户 ID" width="120" show-overflow-tooltip>
            <template #default="{ row }"><span class="mono">{{ row.user_id ?? '—' }}</span></template>
          </el-table-column>
          <el-table-column label="状态" width="104">
            <template #default="{ row }">
              <el-tag size="small" :type="tagType(row.status)" effect="light">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="创建时间" width="168">
            <template #default="{ row }"><span class="ot-time">{{ row.created_at || '—' }}</span></template>
          </el-table-column>
          <el-table-column label="经营操作" width="200">
            <template #default="{ row }">
              <div class="ot-actions">
                <el-button v-if="String(row.status) === 'pending'" size="small" :loading="busyOrder === orderNo(row)" @click="reprice(row)">改价</el-button>
                <el-button v-if="String(row.status) === 'pending'" size="small" type="danger" plain :loading="busyOrder === orderNo(row)" @click="cancel(row)">取消</el-button>
                <el-button v-if="String(row.status) === 'paid'" size="small" type="warning" plain :loading="busyOrder === orderNo(row)" @click="requestRefund(row)">申请退款</el-button>
                <span v-if="!['pending', 'paid'].includes(String(row.status))" class="ot-muted">终态只读</span>
              </div>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty :description="loading ? '正在读取订单…' : (error || '暂无订单数据')" :image-size="72" />
          </template>
        </el-table>
      </div>
    </section>

    <section v-show="section === 'refunds'" class="ot-card" aria-label="退款审核">
      <div class="ot-card__head">
        <h3>退款审核</h3>
        <el-tag size="small" :type="pendingRefunds.length ? 'warning' : 'success'" effect="light">{{ pendingRefunds.length }} 待审</el-tag>
      </div>
      <div class="ot-table-wrap">
        <el-table :data="pendingRefunds" height="100%" size="small" row-key="id" class="ot-table">
          <el-table-column label="订单号" min-width="180" show-overflow-tooltip>
            <template #default="{ row }"><span class="mono">{{ row.order_no || '—' }}</span></template>
          </el-table-column>
          <el-table-column label="金额" width="110" align="right">
            <template #default="{ row }"><span class="mono">¥{{ formatAmount(row.amount) }}</span></template>
          </el-table-column>
          <el-table-column label="原因" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">{{ row.reason || '—' }}</template>
          </el-table-column>
          <el-table-column label="申请时间" width="168">
            <template #default="{ row }"><span class="ot-time">{{ row.created_at || '—' }}</span></template>
          </el-table-column>
          <el-table-column label="操作" width="200">
            <template #default="{ row }">
              <div class="ot-actions">
                <el-button size="small" type="danger" :loading="busyRefund === Number(row.id)" @click="reviewRefund(row, 'approve')">通过并执行</el-button>
                <el-button size="small" :loading="busyRefund === Number(row.id)" @click="reviewRefund(row, 'reject')">驳回</el-button>
              </div>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty description="暂无待审退款" :image-size="72" />
          </template>
        </el-table>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import AdminSectionNav from './AdminSectionNav.vue'
const section = ref('orders')
import { computed, onMounted, ref } from 'vue'
import { ElAlert, ElButton, ElEmpty, ElOption, ElSelect, ElTable, ElTableColumn, ElTag } from 'element-plus'
import 'element-plus/dist/index.css'
import { statusLabel } from '../../utils/statusLabel'
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

const statusEntries = computed<[string, number][]>(() => {
  const raw = summary.value.by_status
  if (!raw || typeof raw !== 'object') return []
  return Object.entries(raw as Record<string, unknown>).map(([key, value]) => [key, Number(value) || 0])
})

function orderNo(order: OrderRow): string {
  return String(order.out_trade_no || order.order_no || order.id || '')
}

function tagType(status: unknown): 'success' | 'warning' | 'info' | 'danger' {
  const s = String(status || '')
  if (s === 'paid') return 'success'
  if (s === 'pending') return 'warning'
  if (s === 'refunded') return 'danger'
  return 'info'
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
/* 借鉴 Element Plus 管理后台的列表页布局：指标条 + 工具栏 + 自适应表格，首屏不滚动。 */
.admin-orders-tab {
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: 100%;
  min-height: 0;
  padding: 0;
  overflow: hidden;
}
.ot-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex: 0 0 auto;
}
.ot-head__title {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
  flex-wrap: wrap;
}
.ot-head__title h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #172033;
}
.ot-head__meta {
  color: rgba(23, 32, 51, 0.55);
  font-size: 12px;
}
.ot-head__actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.ot-status-select {
  width: 128px;
}
.ot-kpis {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  flex: 0 0 auto;
}
.ot-kpi {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  padding: 10px 14px;
  border: 1px solid rgba(15, 76, 129, 0.1);
  border-radius: 10px;
  background: #fff;
}
.ot-kpi__label {
  color: rgba(23, 32, 51, 0.55);
  font-size: 12px;
}
.ot-kpi__value {
  color: #172033;
  font-size: 20px;
  font-weight: 700;
  line-height: 1.25;
  font-variant-numeric: tabular-nums;
}
.ot-kpi__value small {
  font-size: 12px;
  font-weight: 600;
  color: rgba(23, 32, 51, 0.55);
}
.ot-kpi__hint {
  overflow: hidden;
  color: rgba(23, 32, 51, 0.5);
  font-size: 11.5px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ot-kpi__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 4px;
}
.ot-alert {
  flex: 0 0 auto;
}
.ot-card {
  display: flex;
  flex: 1 1 0;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  border: 1px solid rgba(15, 76, 129, 0.1);
  border-radius: 12px;
  background: #fff;
}
.ot-card__head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 0 0 auto;
  padding: 8px 12px;
  border-bottom: 1px solid rgba(15, 76, 129, 0.08);
}
.ot-card__head h3 {
  flex: 1;
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: #172033;
}
.ot-card__count {
  color: rgba(23, 32, 51, 0.55);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.ot-table-wrap {
  display: flex;
  flex: 1 1 0;
  flex-direction: column;
  min-height: 0;
}
.ot-table {
  flex: 1 1 0;
  height: 100%;
  min-height: 0;
}
.ot-table :deep(.el-table__inner-wrapper) {
  height: 100%;
}
.ot-table :deep(th.el-table__cell) {
  height: 36px;
  padding: 0;
  background: #f7fafd;
  color: rgba(23, 32, 51, 0.6);
  font-size: 12px;
  font-weight: 600;
}
.ot-table :deep(td.el-table__cell) {
  padding: 5px 0;
  font-size: 12.5px;
}
.ot-table :deep(.cell) {
  padding: 0 10px;
}
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
}
.ot-time {
  color: rgba(23, 32, 51, 0.55);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.ot-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.ot-muted {
  color: rgba(23, 32, 51, 0.4);
  font-size: 12px;
}
@media (max-width: 1099px) {
  .ot-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 899px), (max-height: 619px) {
  .admin-orders-tab {
    height: auto;
    min-height: 100%;
    overflow-y: auto;
  }
  .ot-card { min-height: 320px; }
}
</style>
