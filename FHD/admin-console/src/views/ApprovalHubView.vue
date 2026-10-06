<template>
  <main class="approval-hub-view" id="view-autonomy-approval-hub">
    <header class="page-header">
      <div><h2>产品问题工单审批</h2><p>共享 Work Order 与完整闸门时间线；每 30 秒刷新</p></div>
      <div class="header-actions">
        <span v-if="updatedAt" class="updated-at">更新于 {{ formatTime(updatedAt) }}</span>
        <button class="btn btn-secondary" :disabled="loading" @click="refresh">{{ loading ? '刷新中…' : '刷新工单' }}</button>
      </div>
    </header>
    <p v-if="error" class="banner-error">工单刷新失败：{{ error }}</p>
    <section v-if="!orders.length && !error" class="panel empty">当前没有共享工单</section>
    <section v-for="item in orders" :key="item.wo_id" class="panel work-order">
      <header class="panel-head"><h3>{{ item.wo_id }}</h3><span class="risk">{{ item.status }}</span></header>
      <dl class="facts">
        <dt>客户 / 租户</dt><dd>{{ item.context?.customer_user_id || item.context?.tenant_id || '—' }}</dd>
        <dt>客户实例</dt><dd>{{ item.context?.client_instance_id || '—' }}</dd>
        <dt>版本 / Git SHA</dt><dd>{{ item.context?.product_version || '—' }} · {{ item.context?.git_sha || '—' }}</dd>
        <dt>平台</dt><dd>{{ item.context?.platform || '—' }}</dd>
        <dt>客户问题 / 实际</dt><dd>{{ item.context?.actual || item.reason || '—' }}</dd>
        <dt>预期</dt><dd>{{ item.context?.expected || '—' }}</dd>
        <dt>支持包 SHA256</dt><dd>{{ item.context?.support_bundle_sha256 || '—' }}</dd>
        <dt>闸门</dt><dd>{{ Object.entries(item.gates || {}).map(([k, v]) => `${k}: ${v}`).join(' · ') || '暂无收据' }}</dd>
      </dl>
      <details><summary>工单证据、诊断、PR、CI 与时间线</summary><pre class="payload">{{ pretty(item) }}</pre></details>
      <div v-if="ticketIdOf(item)" class="ticket-trail">
        <div class="drawer-actions">
          <button class="btn btn-secondary" :disabled="trails[item.wo_id]?.loading" @click="loadTrail(item)">{{ trails[item.wo_id]?.ticket ? '刷新客户工单' : `查看客户工单 #${ticketIdOf(item)}` }}</button>
          <button v-if="obj(trails[item.wo_id]?.ticket?.evidence).support_bundle_base64" class="btn btn-secondary" @click="downloadBundle(item)">下载支持包（先校验 SHA256）</button>
          <span v-if="trails[item.wo_id]?.ticket" class="muted">{{ trails[item.wo_id]?.ticket?.ticket_no }} · {{ trails[item.wo_id]?.ticket?.lifecycle_label }}（{{ trails[item.wo_id]?.ticket?.status }}）</span>
        </div>
        <p v-if="trails[item.wo_id]?.error" class="banner-error">{{ trails[item.wo_id]?.error }}</p>
        <ol class="timeline"><li v-for="(row, index) in timelineOf(item)" :key="index"><time>{{ formatTime(row.at) }}</time>{{ row.label }}</li></ol>
      </div>
      <div v-if="item.can_decide" class="drawer-actions">
        <button class="btn btn-primary" :disabled="acting" @click="decide(item, 'approved')">批准</button>
        <button class="btn btn-danger" :disabled="acting" @click="decide(item, 'rejected')">拒绝</button>
        <button class="btn btn-secondary" :disabled="acting" @click="decide(item, 'held')">暂缓</button>
      </div>
      <p v-else class="muted">决策锁定：必须同一工单已有 RED、GREEN 和 OWNER_INSTANCE_VERIFIED 收据。</p>
    </section>
  </main>
</template>

<script lang="ts">
export default { name: 'ApprovalHubView' }
</script>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { xcmaxAdminApi, type OwnerWorkOrder } from '@/api/xcmaxAdmin'
import { appAlert, appPrompt } from '@/utils/appDialog'

type Trail = { loading: boolean; error: string; ticket?: Record<string, unknown>; audits: Record<string, unknown>[] }
const AUDIT_LABELS: Record<string, string> = {
  ticket_created: '客服工单已创建', issue_intake: '客户工单已受理', employee_progress: 'AI 员工回写处理结果',
  customer_issue_resolved: '客户确认已解决', customer_issue_reopen: '客户重新打开工单',
}
const orders = ref<OwnerWorkOrder[]>([])
const trails = ref<Record<string, Trail>>({})
const loading = ref(false)
const acting = ref(false)
const error = ref('')
const updatedAt = ref('')
let timer: ReturnType<typeof setInterval> | undefined

function obj(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {}
}

function ticketIdOf(item: OwnerWorkOrder) {
  for (const row of item.history || []) {
    const ref = obj(row.ref)
    const id = Number(ref.customer_ticket_id || obj(ref.evidence).customer_ticket_id || 0)
    if (id > 0) return id
  }
  return 0
}

function eventTime(value: unknown) {
  const text = String(value || '')
  return Date.parse(/(Z|[+-]\d\d:?\d\d)$/.test(text) ? text : `${text}Z`)
}

function timelineOf(item: OwnerWorkOrder) {
  const rows = (item.history || []).map((row) => {
    const ref = obj(row.ref)
    const label = row.event === 'gate' ? `闸门 ${ref.gate}：${ref.gate_status}`
      : row.event === 'transition' ? `工单状态 ${row.from || '—'} → ${row.to}` : '共享工单已创建'
    return { at: eventTime(row.at), label: row.note ? `${label}（${row.note}）` : label }
  })
  for (const audit of trails.value[item.wo_id]?.audits || []) {
    const note = obj(audit.detail).note
    const label = AUDIT_LABELS[String(audit.event_type)] || String(audit.event_type)
    rows.push({ at: eventTime(audit.created_at), label: note ? `${label}：${note}` : label })
  }
  return rows.sort((a, b) => (a.at || 0) - (b.at || 0))
}

async function loadTrail(item: OwnerWorkOrder) {
  trails.value[item.wo_id] ||= { loading: false, error: '', audits: [] }
  const trail = trails.value[item.wo_id]
  if (trail.loading) return
  trail.loading = true
  trail.error = ''
  try {
    const result = await xcmaxAdminApi.fetchCustomerTicket(ticketIdOf(item))
    trail.ticket = obj(result.ticket)
    trail.audits = Array.isArray(result.audit_logs) ? result.audit_logs : []
  } catch (cause: unknown) {
    trail.error = cause instanceof Error ? cause.message : String(cause)
  } finally { trail.loading = false }
}

async function downloadBundle(item: OwnerWorkOrder) {
  const trail = trails.value[item.wo_id]
  const evidence = obj(trail.ticket?.evidence)
  try {
    const bytes = Uint8Array.from(atob(String(evidence.support_bundle_base64 || '')), (char) => char.charCodeAt(0))
    const hash = new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', bytes))
    const digest = Array.from(hash, (byte) => byte.toString(16).padStart(2, '0')).join('')
    const collected = (item.history || []).map((row) => obj(obj(row.ref).evidence).support_bundle_sha256).filter(Boolean)
    if (digest !== evidence.support_bundle_sha256 || (collected.length && !collected.includes(digest))) {
      throw new Error(`实际 ${digest}`)
    }
    const link = document.createElement('a')
    link.href = URL.createObjectURL(new Blob([bytes], { type: 'application/zip' }))
    link.download = `support-bundle-${trail.ticket?.ticket_no || ticketIdOf(item)}.zip`
    link.click()
    URL.revokeObjectURL(link.href)
  } catch (cause: unknown) {
    trail.error = `支持包 SHA256 校验失败，已阻止下载（${cause instanceof Error ? cause.message : String(cause)}）`
  }
}

function formatTime(value: unknown) {
  const date = new Date(typeof value === 'number' ? value : String(value || ''))
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString()
}

function pretty(value: unknown) {
  try { return JSON.stringify(value ?? {}, null, 2) } catch { return String(value ?? '') }
}

async function refresh() {
  if (loading.value) return
  loading.value = true
  try {
    const result = await xcmaxAdminApi.fetchOwnerWorkOrders()
    orders.value = Array.isArray(result.items) ? result.items : []
    error.value = ''
    updatedAt.value = new Date().toISOString()
  } catch (cause: unknown) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally { loading.value = false }
}

async function decide(item: OwnerWorkOrder, decision: 'approved' | 'rejected' | 'held') {
  if (!item.can_decide || acting.value) return
  const note = decision === 'approved' ? '' : await appPrompt(decision === 'held' ? '暂缓说明（可选）' : '拒绝原因（可选）', '')
  if (note === null) return
  acting.value = true
  try {
    const result = await xcmaxAdminApi.decideOwnerWorkOrder(item.wo_id, decision, note)
    await appAlert(`工单 ${item.wo_id} 已记录为 ${result.decision}，操作人 ${result.actor}`)
    await refresh()
  } catch (cause: unknown) {
    await appAlert(cause instanceof Error ? cause.message : String(cause))
  } finally { acting.value = false }
}

onMounted(() => { void refresh(); timer = setInterval(() => { if (document.visibilityState === 'visible') void refresh() }, 30_000) })
onBeforeUnmount(() => { if (timer) clearInterval(timer) })
</script>

<style scoped src="./ApprovalHubView.css"></style>
