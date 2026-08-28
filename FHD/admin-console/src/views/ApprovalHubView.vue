<template>
  <div class="approval-hub-view" id="view-autonomy-approval-hub">
    <div class="page-header">
      <div>
        <h2>自治审批中心</h2>
        <p>待办、执行通道与终态回执（页面可见时每 30s 自动刷新）</p>
      </div>
      <div class="header-actions">
        <span v-if="lastUpdatedAt" class="updated-at">更新于 {{ formatTime(lastUpdatedAt) }}</span>
        <span class="pill">待办 {{ summary.waiting }}</span>
        <button class="btn btn-secondary" type="button" :disabled="loading" @click="refreshAll()">
          <i class="fa fa-refresh" :class="{ 'fa-spin': loading }" aria-hidden="true"></i>
          {{ loading ? '刷新中…' : '立即刷新' }}
        </button>
      </div>
    </div>

    <div class="status-grid" aria-label="审批状态概览">
      <article class="status-card">
        <span>可在此执行</span>
        <strong>{{ summary.actionable }}</strong>
      </article>
      <article class="status-card">
        <span>正式流程 / 外部回调</span>
        <strong>{{ externalWaiting }}</strong>
      </article>
      <article class="status-card">
        <span>已执行</span>
        <strong>{{ stateCount('executed') }}</strong>
      </article>
      <article class="status-card" :class="{ 'status-card-alert': openLoopIssues > 0 }">
        <span>异常 / 未闭环</span>
        <strong>{{ openLoopIssues }}</strong>
      </article>
      <article class="status-card">
        <span>已自动归档</span>
        <strong>{{ stateCount('superseded') }}</strong>
      </article>
    </div>

    <p v-if="pendingError" class="banner-error">待办刷新失败，已保留上次结果：{{ pendingError }}</p>
    <p v-if="auditError" class="banner-warning">审计日志暂时不可用：{{ auditError }}</p>

    <div class="hub-grid">
      <section class="panel">
        <header class="panel-head">
          <h3>待办列表</h3>
        </header>
        <div v-if="!pending.length" class="empty">
          <strong>当前没有真正待处理动作</strong>
          <span>已经完成或被新版本替代的发布动作会自动归档，不再反复出现。</span>
        </div>
        <ul v-else class="pending-list">
          <li
            v-for="item in pending"
            :key="item.action_id"
            class="pending-item"
            :class="{ active: selectedId === item.action_id }"
            @click="selectedId = item.action_id"
          >
            <div class="pending-title">
              <code>{{ item.action }}</code>
              <span class="risk" :class="`risk-${riskOf(item)}`">{{ riskOf(item) }}</span>
            </div>
            <div class="pending-meta">
              <span>{{ item.source || '—' }}</span>
              <span>{{ formatTime(item.timestamp || item.approval_requested_at) }}</span>
            </div>
            <div class="execution-row">
              <span class="mode" :class="`mode-${item.execution_mode || 'unknown'}`">
                {{ executionModeLabel(item) }}
              </span>
              <span>{{ item.execution_guidance || '等待执行器校验' }}</span>
            </div>
            <div class="pending-id">{{ item.action_id }}</div>
          </li>
        </ul>
      </section>

      <section class="panel">
        <header class="panel-head">
          <h3>审计日志流</h3>
          <span class="muted">最近 {{ auditItems.length }} 条</span>
        </header>
        <div v-if="!auditItems.length" class="empty">暂无审计记录</div>
        <ul v-else class="audit-list">
          <li v-for="(row, idx) in auditItems" :key="auditKey(row, idx)" class="audit-item">
            <div class="audit-top">
              <strong>{{ row.action || row.decision || 'event' }}</strong>
              <span class="risk" :class="`risk-${String(row.risk_level || row.decision || 'info').toLowerCase()}`">
                {{ row.risk_level || row.decision || '—' }}
              </span>
            </div>
            <div class="audit-meta">
              <span>{{ row.actor || row.approver || row.source || 'system' }}</span>
              <span>{{ formatTime(row.timestamp || row.created_at) }}</span>
            </div>
            <p v-if="row.reason" class="audit-reason">{{ row.reason }}</p>
          </li>
        </ul>
      </section>
    </div>

    <aside v-if="selected" class="drawer" role="dialog" aria-label="动作详情">
      <div class="drawer-head">
        <h3>动作详情</h3>
        <button type="button" class="icon-btn" @click="selectedId = ''" aria-label="关闭">×</button>
      </div>
      <dl class="detail-grid">
        <dt>action_id</dt><dd class="mono">{{ selected.action_id }}</dd>
        <dt>action</dt><dd>{{ selected.action }}</dd>
        <dt>state</dt><dd>{{ selected.state }}</dd>
        <dt>source</dt><dd>{{ selected.source }}</dd>
        <dt>risk</dt><dd>{{ riskOf(selected) }}</dd>
        <dt>decision</dt><dd>{{ selected.risk_decision?.decision || '—' }}</dd>
        <dt>reason</dt><dd>{{ selected.risk_decision?.reason || '—' }}</dd>
        <dt>rollback</dt><dd>{{ selected.risk_decision?.rollback_path || '—' }}</dd>
        <dt>执行方式</dt><dd>{{ selected.execution_mode || '—' }}</dd>
      </dl>
      <p class="execution-guidance">
        {{ selected.execution_guidance || '审批前将再次验证执行器。' }}
      </p>
      <pre class="payload">{{ pretty(selected.payload) }}</pre>
      <div class="drawer-actions">
        <button
          class="btn btn-primary"
          type="button"
          :disabled="acting || selected.admin_execution_ready !== true"
          @click="approveSelected"
        >
          {{ selected.admin_execution_ready === true ? '通过并立即执行' : executionModeLabel(selected) }}
        </button>
        <button class="btn btn-danger" type="button" :disabled="acting" @click="rejectSelected">
          拒绝
        </button>
      </div>
    </aside>
    <div v-if="selected" class="drawer-mask" @click="selectedId = ''" />
  </div>
</template>

<script lang="ts">
export default { name: 'ApprovalHubView' }
</script>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  xcmaxAdminApi,
  type AutonomyPendingAction,
} from '@/api/xcmaxAdmin'
import { appAlert, appConfirm, appPrompt } from '@/utils/appDialog'

type AuditRow = Record<string, unknown>

const loading = ref(false)
const acting = ref(false)
const pendingError = ref('')
const auditError = ref('')
const pending = ref<AutonomyPendingAction[]>([])
const auditItems = ref<AuditRow[]>([])
const selectedId = ref('')
const lastUpdatedAt = ref('')
const summary = ref({
  states: {} as Record<string, number>,
  execution_modes: {} as Record<string, number>,
  actionable: 0,
  waiting: 0,
})
let timer: ReturnType<typeof setInterval> | null = null
let refreshInFlight = false

const selected = computed(() => pending.value.find((x) => x.action_id === selectedId.value) || null)
const externalWaiting = computed(() =>
  Number(summary.value.execution_modes.external_callback || 0)
  + Number(summary.value.execution_modes.external_dispatch_required || 0),
)
const openLoopIssues = computed(() =>
  stateCount('approved') + stateCount('execution_failed'),
)

function riskOf(item: AutonomyPendingAction) {
  return String(item.risk_decision?.risk_level || 'unknown').toLowerCase()
}

function auditKey(row: AuditRow, index: number): string | number {
  return typeof row.id === 'string' || typeof row.id === 'number' ? row.id : index
}

function formatTime(value: unknown) {
  const text = String(value || '').trim()
  if (!text) return '—'
  const d = new Date(text)
  if (Number.isNaN(d.getTime())) return text
  return d.toLocaleString()
}

function pretty(value: unknown) {
  try {
    return JSON.stringify(value ?? {}, null, 2)
  } catch {
    return String(value ?? '')
  }
}

function stateCount(state: string) {
  return Number(summary.value.states[state] || 0)
}

function executionModeLabel(item: AutonomyPendingAction) {
  if (item.admin_execution_ready === true) return '可立即执行'
  if (item.execution_mode === 'external_callback') return '外部审批处理中'
  if (item.execution_mode === 'external_dispatch_required') return '需正式发布工作流'
  if (item.execution_mode === 'executor_unavailable') return '执行器不可用'
  return '等待执行通道'
}

function errorMessage(value: unknown) {
  return value instanceof Error ? value.message : String(value)
}

async function refreshAll(options: { silent?: boolean } = {}) {
  if (refreshInFlight) return
  refreshInFlight = true
  if (!options.silent) loading.value = true
  try {
    const [pendingResult, auditResult] = await Promise.allSettled([
      xcmaxAdminApi.fetchPendingAutonomyActions(),
      xcmaxAdminApi.fetchAutonomyAuditLog({ limit: 40, days: 7 }),
    ])
    let refreshed = false
    if (pendingResult.status === 'fulfilled') {
      const pendingRes = pendingResult.value
      pending.value = Array.isArray(pendingRes?.items) ? pendingRes.items : []
      const nextSummary = pendingRes?.summary || {}
      summary.value = {
        states: nextSummary.states || {},
        execution_modes: nextSummary.execution_modes || {},
        actionable: Number(nextSummary.actionable || 0),
        waiting: Number(nextSummary.waiting ?? pending.value.length),
      }
      pendingError.value = ''
      if (selectedId.value && !pending.value.some((x) => x.action_id === selectedId.value)) {
        selectedId.value = ''
      }
      refreshed = true
    } else {
      pendingError.value = errorMessage(pendingResult.reason)
    }
    if (auditResult.status === 'fulfilled') {
      const raw = (auditResult.value as { items?: AuditRow[] })?.items
      auditItems.value = Array.isArray(raw) ? raw : []
      auditError.value = ''
      refreshed = true
    } else {
      auditError.value = errorMessage(auditResult.reason)
    }
    if (refreshed) lastUpdatedAt.value = new Date().toISOString()
  } finally {
    if (!options.silent) loading.value = false
    refreshInFlight = false
  }
}

async function approveSelected() {
  if (!selected.value) return
  const item = selected.value
  if (item.admin_execution_ready !== true) {
    await appAlert(item.execution_guidance || '当前动作不能由管理端直接执行。')
    return
  }
  const confirmed = await appConfirm(
    `确认通过并立即执行 ${item.action}？\n${item.action_id}`,
    { title: '高风险动作确认' },
  )
  if (!confirmed) return
  acting.value = true
  try {
    const result = await xcmaxAdminApi.resumeAutonomyAction(item.action_id)
    await appAlert(`审批与执行均已完成，动作终态：${result.action?.state || 'executed'}`)
    await refreshAll()
  } catch (e: unknown) {
    await appAlert(e instanceof Error ? e.message : String(e))
  } finally {
    acting.value = false
  }
}

async function rejectSelected() {
  if (!selected.value) return
  const reason = await appPrompt('拒绝原因（可选）', '')
  if (reason === null) return
  acting.value = true
  try {
    await xcmaxAdminApi.rejectAutonomyAction(selected.value.action_id, reason || undefined)
    await appAlert('已拒绝')
    selectedId.value = ''
    await refreshAll()
  } catch (e: unknown) {
    await appAlert(e instanceof Error ? e.message : String(e))
  } finally {
    acting.value = false
  }
}

onMounted(async () => {
  await refreshAll()
  timer = setInterval(() => {
    if (document.visibilityState === 'visible' && !acting.value) {
      void refreshAll({ silent: true })
    }
  }, 30_000)
  document.addEventListener('visibilitychange', onVisibilityChange)
})

function onVisibilityChange() {
  if (document.visibilityState === 'visible') void refreshAll({ silent: true })
}

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  timer = null
  document.removeEventListener('visibilitychange', onVisibilityChange)
})
</script>

<style scoped>
.approval-hub-view {
  position: relative;
  padding: 24px 28px 40px;
  max-width: 1400px;
  margin: 0 auto;
  min-height: 100%;
  background: linear-gradient(135deg, #edf5fb 0%, #e7eef6 100%);
}
.page-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 18px;
}
.page-header h2 {
  margin: 0 0 4px;
  font-size: 22px;
  color: #172033;
}
.page-header p {
  margin: 0;
  color: #64748b;
  font-size: 13px;
}
.header-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}
.updated-at { color: #64748b; font-size: 12px; }
.pill {
  background: #e8f3ff;
  color: #1890ff;
  border-radius: 999px;
  padding: 4px 12px;
  font-size: 12px;
  font-weight: 700;
}
.btn {
  border: 1px solid #d0d7e2;
  background: #fff;
  border-radius: 8px;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 13px;
}
.btn-secondary:hover { border-color: #1890ff; color: #1890ff; }
.btn-primary { background: #1890ff; border-color: #1890ff; color: #fff; }
.btn-danger { background: #fff1f0; border-color: #ffa39e; color: #cf1322; }
.btn:disabled { opacity: 0.6; cursor: not-allowed; }
.banner-error {
  background: #fff1f0;
  color: #cf1322;
  border: 1px solid #ffa39e;
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 12px;
}
.banner-warning {
  background: #fff8e6;
  color: #a16207;
  border: 1px solid #f5d58a;
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 12px;
}
.status-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.status-card {
  background: rgba(255,255,255,0.94);
  border: 1px solid rgba(24,144,255,0.14);
  border-radius: 12px;
  padding: 12px 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.status-card span { color: #64748b; font-size: 12px; }
.status-card strong { color: #0f4c81; font-size: 22px; }
.status-card-alert { border-color: #ffa39e; background: #fff7f6; }
.status-card-alert strong { color: #cf1322; }
.hub-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
@media (max-width: 960px) {
  .hub-grid { grid-template-columns: 1fr; }
  .status-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
.panel {
  background: rgba(255,255,255,0.92);
  border: 1px solid rgba(15,76,129,0.1);
  border-radius: 16px;
  box-shadow: 0 4px 18px rgba(15,76,129,0.07);
  min-height: 420px;
  display: flex;
  flex-direction: column;
}
.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 16px;
  border-bottom: 1px solid #eef2f7;
}
.panel-head h3 { margin: 0; font-size: 15px; }
.muted { color: #94a3b8; font-size: 12px; }
.empty { padding: 28px; color: #94a3b8; text-align: center; display: grid; gap: 8px; }
.empty strong { color: #475569; font-size: 14px; }
.empty span { font-size: 12px; line-height: 1.6; }
.pending-list, .audit-list {
  list-style: none;
  margin: 0;
  padding: 8px;
  overflow: auto;
  flex: 1;
}
.pending-item, .audit-item {
  border: 1px solid #eef2f7;
  border-radius: 10px;
  padding: 10px 12px;
  margin-bottom: 8px;
  cursor: pointer;
  background: #fff;
}
.pending-item.active { border-color: #1890ff; background: #f0f7ff; }
.pending-title, .audit-top {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
}
.pending-meta, .audit-meta {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  margin-top: 6px;
  color: #64748b;
  font-size: 12px;
}
.pending-id, .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; color: #64748b; word-break: break-all; }
.execution-row {
  display: grid;
  gap: 5px;
  margin: 8px 0 6px;
  color: #64748b;
  font-size: 11px;
  line-height: 1.4;
}
.mode { width: fit-content; border-radius: 999px; padding: 2px 8px; font-weight: 700; }
.mode-registered_executor { background: #e8f3ff; color: #0f6fc6; }
.mode-external_callback, .mode-external_dispatch_required { background: #fff7e0; color: #a16207; }
.mode-executor_unavailable, .mode-unknown { background: #f1f5f9; color: #64748b; }
.risk {
  text-transform: uppercase;
  font-size: 10px;
  font-weight: 700;
  border-radius: 999px;
  padding: 2px 8px;
}
.risk-low, .risk-info, .risk-allow { background: #e6f9f0; color: #10b759; }
.risk-medium, .risk-warn, .risk-hold { background: #fff7e0; color: #d97706; }
.risk-high, .risk-critical, .risk-blocked, .risk-prohibited { background: #fff1f0; color: #e53e3e; }
.risk-unknown { background: #f1f5f9; color: #64748b; }
.audit-reason { margin: 6px 0 0; font-size: 12px; color: #334155; }
.drawer-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.35);
  z-index: 40;
}
.drawer {
  position: fixed;
  top: 0;
  right: 0;
  width: min(440px, 92vw);
  height: 100%;
  background: #fff;
  z-index: 50;
  box-shadow: -8px 0 30px rgba(15, 23, 42, 0.18);
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.drawer-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.drawer-head h3 { margin: 0; }
.icon-btn {
  border: none;
  background: transparent;
  font-size: 22px;
  cursor: pointer;
  line-height: 1;
}
.detail-grid {
  display: grid;
  grid-template-columns: 90px 1fr;
  gap: 6px 10px;
  margin: 0;
  font-size: 13px;
}
.detail-grid dt { color: #64748b; }
.detail-grid dd { margin: 0; word-break: break-all; }
.execution-guidance {
  margin: 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: #f8fafc;
  color: #475569;
  font-size: 12px;
  line-height: 1.5;
}
.payload {
  flex: 1;
  overflow: auto;
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 10px;
  padding: 12px;
  font-size: 11px;
  margin: 0;
}
.drawer-actions {
  display: flex;
  gap: 10px;
}
</style>
