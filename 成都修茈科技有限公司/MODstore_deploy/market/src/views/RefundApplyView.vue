<template>
  <div class="refund-page">
    <h1 class="page-title">退款申请</h1>
    <p class="page-desc">填写钱包订单号（商户订单号 / out_trade_no）与原因。审核通过后退款会退回钱包余额，处理进度可在下方列表查看。</p>
    <div v-if="msg" :class="['flash', msgOk ? 'flash-ok' : 'flash-err']">{{ msg }}</div>
    <div class="card">
      <h3 class="card-title">提交申请</h3>
      <div class="form-group">
        <label class="label">订单号</label>
        <input v-model="orderNo" class="input" placeholder="例如 checkout 页或支付回调中的订单号" />
      </div>
      <div class="form-group">
        <div class="label-row">
          <label class="label">原因（5-1000 字）</label>
          <span :class="['counter', { invalid: reasonCount > REFUND_REASON_MAX }]">{{ reasonCount }}/1000</span>
        </div>
        <textarea v-model="reason" class="input" rows="4" placeholder="请说明退款原因，便于管理员审核" />
      </div>
      <button type="button" class="btn btn-primary" :disabled="submitting || !canSubmit" @click="submit">
        {{ submitting ? '提交中…' : '提交申请' }}
      </button>
    </div>
    <div class="card">
      <h3 class="card-title">我的退款记录</h3>
      <div v-if="listLoading" class="loading">加载中…</div>
      <table v-else-if="rows.length" class="tbl">
        <thead>
          <tr>
            <th>订单号</th>
            <th>金额</th>
            <th>原因</th>
            <th>状态</th>
            <th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.id">
            <td>{{ r.order_no }}</td>
            <td>¥{{ Number(r.amount).toFixed(2) }}</td>
            <td class="reason-cell">{{ r.reason || '—' }}</td>
            <td>
              <span :class="['status-pill', `status-${refundStatusTone(r.status || '')}`]">
                {{ refundStatusText(r.status || '') }}
              </span>
            </td>
            <td>{{ formatRefundTime(r.created_at) }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">暂无记录</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api'
import {
  REFUND_REASON_MAX,
  formatRefundTime,
  refundStatusText,
  refundStatusTone,
  validateRefundForm,
} from '../refundStatus'

const route = useRoute()
const orderNo = ref('')
const reason = ref('')
const submitting = ref(false)
const msg = ref('')
const msgOk = ref(true)
interface RefundRow {
  id: number | string
  order_no: string
  amount: number | string
  reason?: string
  status?: string
  created_at?: string
}

const listLoading = ref(true)
const rows = ref<RefundRow[]>([])
const reasonCount = computed(() => reason.value.trim().length)
const canSubmit = computed(() => !validateRefundForm(orderNo.value, reason.value))

async function loadList() {
  listLoading.value = true
  try {
    const res = await api.refundsMy()
    rows.value = res.refunds || []
  } catch {
    rows.value = []
  } finally {
    listLoading.value = false
  }
}

async function submit() {
  msg.value = ''
  const validation = validateRefundForm(orderNo.value, reason.value)
  if (validation) {
    msgOk.value = false
    msg.value = validation
    return
  }
  submitting.value = true
  try {
    await api.refundsApply(orderNo.value.trim(), reason.value.trim())
    msgOk.value = true
    msg.value = '已提交申请，审核通过后将退回钱包余额'
    orderNo.value = ''
    reason.value = ''
    await loadList()
  } catch (e) {
    msgOk.value = false
    msg.value = (e as Error)?.message || String(e)
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  const q = route.query.order_no
  if (typeof q === 'string' && q.trim()) orderNo.value = q.trim()
  void loadList()
})
</script>

<style scoped>
.refund-page {
  max-width: 720px;
  margin: 0 auto;
  padding: var(--page-pad-y, 1.5rem) var(--layout-pad-x, 1rem);
}
.page-title {
  font-size: 1.75rem;
  margin: 0 0 0.5rem;
  color: #fff;
}
.page-desc {
  color: rgba(255, 255, 255, 0.45);
  margin: 0 0 1.25rem;
  font-size: 0.9rem;
}
.card {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 1.25rem;
  margin-bottom: 1rem;
}
.card-title {
  margin: 0 0 1rem;
  font-size: 1rem;
  color: rgba(255, 255, 255, 0.85);
}
.form-group {
  margin-bottom: 1rem;
}
.label {
  display: block;
  margin-bottom: 0.35rem;
  color: rgba(255, 255, 255, 0.65);
  font-size: 0.85rem;
}
.label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 0.35rem;
}
.label-row .label {
  margin-bottom: 0;
}
.counter {
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.45);
}
.counter.invalid {
  color: #f8a0a8;
}
.input {
  width: 100%;
  box-sizing: border-box;
  padding: 0.5rem 0.65rem;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.15);
  background: rgba(0, 0, 0, 0.25);
  color: #fff;
}
.tbl {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}
.tbl th,
.tbl td {
  text-align: left;
  padding: 0.5rem 0.35rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.8);
}
.reason-cell {
  max-width: 220px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.status-pill {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 0.15rem 0.5rem;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.06);
  white-space: nowrap;
}
.status-pending {
  color: #fde68a;
  border-color: rgba(253, 230, 138, 0.25);
}
.status-approved {
  color: #9be7af;
  border-color: rgba(155, 231, 175, 0.25);
}
.status-rejected,
.status-failed {
  color: #f8a0a8;
  border-color: rgba(248, 160, 168, 0.25);
}
.flash {
  padding: 0.75rem 1rem;
  border-radius: 8px;
  margin-bottom: 1rem;
}
.flash-ok {
  background: rgba(40, 167, 69, 0.2);
  color: #9be7af;
}
.flash-err {
  background: rgba(220, 53, 69, 0.15);
  color: #f8a0a8;
}
.loading,
.empty {
  color: rgba(255, 255, 255, 0.5);
}

@media (max-width: 720px) {
  .refund-page {
    padding-top: 4rem;
  }
  .card {
    padding: 1rem;
  }
  .tbl,
  .tbl thead,
  .tbl tbody,
  .tbl tr,
  .tbl th,
  .tbl td {
    display: block;
  }
  .tbl thead {
    display: none;
  }
  .tbl tr {
    padding: 0.75rem 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  }
  .tbl td {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    border-bottom: 0;
    padding: 0.35rem 0;
  }
  .tbl td::before {
    color: rgba(255, 255, 255, 0.45);
  }
  .tbl td:nth-child(1)::before { content: '订单号'; }
  .tbl td:nth-child(2)::before { content: '金额'; }
  .tbl td:nth-child(3)::before { content: '原因'; }
  .tbl td:nth-child(4)::before { content: '状态'; }
  .tbl td:nth-child(5)::before { content: '时间'; }
  .reason-cell {
    max-width: min(56vw, 260px);
  }
}

html[data-workbench-theme='light'] .refund-page { background: #f5f5f7; color: #1d1d1f; }
html[data-workbench-theme='light'] .page-title { color: #1d1d1f; }
html[data-workbench-theme='light'] .page-desc { color: #86868b; }
html[data-workbench-theme='light'] .card { background: #ffffff; border-color: rgba(0,0,0,0.06); }
html[data-workbench-theme='light'] .card-title { color: #1d1d1f; }
html[data-workbench-theme='light'] .label { color: #86868b; }
html[data-workbench-theme='light'] .counter { color: #86868b; }
html[data-workbench-theme='light'] .counter.invalid { color: #dc2626; }
html[data-workbench-theme='light'] .input { border-color: rgba(0,0,0,0.1); background: #ffffff; color: #1d1d1f; }
html[data-workbench-theme='light'] .tbl th,
html[data-workbench-theme='light'] .tbl td { border-bottom-color: rgba(0,0,0,0.06); color: #1d1d1f; }
html[data-workbench-theme='light'] .status-pill { border-color: rgba(0,0,0,0.08); background: rgba(0,0,0,0.03); }
html[data-workbench-theme='light'] .status-pending { color: #b45309; border-color: rgba(180,83,9,0.2); }
html[data-workbench-theme='light'] .status-approved { color: #16a34a; border-color: rgba(22,163,74,0.2); }
html[data-workbench-theme='light'] .status-rejected,
html[data-workbench-theme='light'] .status-failed { color: #dc2626; border-color: rgba(220,38,38,0.2); }
html[data-workbench-theme='light'] .flash-ok { background: rgba(34,197,94,0.08); color: #16a34a; }
html[data-workbench-theme='light'] .flash-err { background: rgba(220,53,69,0.08); color: #dc2626; }
html[data-workbench-theme='light'] .loading,
html[data-workbench-theme='light'] .empty { color: #86868b; }
html[data-workbench-theme='light'] .btn-primary { background: #0071e3; color: #ffffff; border-color: #0071e3; }
html[data-workbench-theme='light'] .btn-primary:hover:not(:disabled) { background: #005bb5; }
</style>
