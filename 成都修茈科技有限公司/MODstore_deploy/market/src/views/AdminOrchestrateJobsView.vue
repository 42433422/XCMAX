<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useAuthStore } from '../stores/auth'
import { api } from '../api'

const authStore = useAuthStore()
const { isAdmin } = storeToRefs(authStore)

interface SubResult {
  ok?: boolean
  employee_id?: string
  error?: string
  result?: Record<string, unknown> | null
}

interface OrchestrateResult {
  ok?: boolean
  results?: SubResult[]
  subtask_count?: number
  handoff_chain?: { depth?: number; to_employee_id?: string; task_brief?: string }[]
  source?: string
}

interface JobRow {
  job_id: string
  status: string
  task_description: string
  submitted_at: string | null
  started_at: string | null
  completed_at: string | null
  result: OrchestrateResult | null
  error: string | null
}

const items = ref<JobRow[]>([])
const loading = ref(false)
const errorMsg = ref('')
const selected = ref<JobRow | null>(null)
const autoRefresh = ref(true)
const refreshSeconds = 6

let timer: number | null = null

const summary = computed(() => {
  const total = items.value.length
  const running = items.value.filter(
    (j) => j.status === 'running' || j.status === 'pending',
  ).length
  const failed = items.value.filter((j) => j.status === 'failed').length
  const done = items.value.filter((j) => j.status === 'done').length
  return { total, running, failed, done }
})

async function load(silent = false) {
  if (!isAdmin.value) return
  if (!silent) loading.value = true
  errorMsg.value = ''
  try {
    const r = (await api.opsOrchestrateJobs(50)) as { items?: JobRow[] }
    items.value = Array.isArray(r?.items) ? r.items : []
    if (selected.value) {
      const fresh = items.value.find((j) => j.job_id === selected.value!.job_id)
      if (fresh) selected.value = fresh
    }
  } catch (err: unknown) {
    errorMsg.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

function statusClass(s: string): string {
  switch (s) {
    case 'running':
      return 'oj-status oj-status--running'
    case 'done':
      return 'oj-status oj-status--done'
    case 'failed':
      return 'oj-status oj-status--failed'
    case 'pending':
      return 'oj-status oj-status--pending'
    default:
      return 'oj-status'
  }
}

function statusLabel(s: string): string {
  return (
    {
      pending: '待启动',
      running: '执行中',
      done: '已完成',
      failed: '失败',
    } as Record<string, string>
  )[s] ?? s
}

function fmt(ts: string | null): string {
  if (!ts) return '—'
  return ts.replace('T', ' ').slice(0, 19)
}

function openDetail(row: JobRow) {
  selected.value = row
}

function closeDetail() {
  selected.value = null
}

function startTimer() {
  stopTimer()
  if (!autoRefresh.value) return
  timer = window.setInterval(() => {
    load(true)
  }, refreshSeconds * 1000)
}

function stopTimer() {
  if (timer != null) {
    window.clearInterval(timer)
    timer = null
  }
}

function toggleAutoRefresh() {
  autoRefresh.value = !autoRefresh.value
  if (autoRefresh.value) startTimer()
  else stopTimer()
}

onMounted(() => {
  if (isAdmin.value) {
    load()
    startTimer()
  }
})

onBeforeUnmount(() => stopTimer())
</script>

<template>
  <div v-if="!isAdmin" class="oj-denied">
    <p>需要管理员权限才能访问此页面</p>
    <router-link to="/" class="btn btn-primary">返回首页</router-link>
  </div>
  <div v-else class="oj-page">
    <header class="oj-header">
      <div class="oj-title-row">
        <h2 class="oj-title">任务编排流水</h2>
        <span class="oj-subtitle">实时查看 task_router 拆解 + 各员工执行状态</span>
      </div>
      <div class="oj-stats">
        <span class="oj-stat">总数 <strong>{{ summary.total }}</strong></span>
        <span class="oj-stat oj-stat--running" v-if="summary.running">执行中 <strong>{{ summary.running }}</strong></span>
        <span class="oj-stat oj-stat--done" v-if="summary.done">已完成 <strong>{{ summary.done }}</strong></span>
        <span class="oj-stat oj-stat--failed" v-if="summary.failed">失败 <strong>{{ summary.failed }}</strong></span>
      </div>
      <div class="oj-actions">
        <button
          type="button"
          class="oj-btn"
          :class="{ 'oj-btn--active': autoRefresh }"
          @click="toggleAutoRefresh"
        >
          {{ autoRefresh ? `⟳ 每 ${refreshSeconds}s 刷新` : '自动刷新' }}
        </button>
        <button type="button" class="oj-btn" :disabled="loading" @click="load(false)">
          {{ loading ? '加载中…' : '刷新' }}
        </button>
        <router-link
          class="oj-btn"
          :to="{ name: 'admin-duty-employees' }"
        >← 返回值班图</router-link>
      </div>
    </header>

    <div v-if="errorMsg" class="oj-flash oj-flash--err">{{ errorMsg }}</div>

    <div class="oj-grid">
      <div class="oj-list">
        <table class="oj-table" v-if="items.length">
          <thead>
            <tr>
              <th style="width: 88px">状态</th>
              <th>任务摘要</th>
              <th style="width: 88px">子任务</th>
              <th style="width: 96px">handoff</th>
              <th style="width: 168px">提交时间</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in items"
              :key="row.job_id"
              :class="{ 'is-active': selected?.job_id === row.job_id }"
              @click="openDetail(row)"
            >
              <td>
                <span :class="statusClass(row.status)">{{ statusLabel(row.status) }}</span>
              </td>
              <td>
                <div class="oj-task">{{ row.task_description || '(无描述)' }}</div>
                <div class="oj-meta">
                  job_id <code>{{ row.job_id.slice(0, 8) }}…</code>
                  <span v-if="row.result?.source" class="oj-source">来源: {{ row.result.source }}</span>
                </div>
              </td>
              <td>{{ row.result?.subtask_count ?? '—' }}</td>
              <td>{{ row.result?.handoff_chain?.length ?? 0 }}</td>
              <td>{{ fmt(row.submitted_at) }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else-if="!loading" class="oj-empty">暂无编排任务。在「值班图」上点「下达任务」即可派发。</p>
      </div>

      <aside class="oj-detail" v-if="selected">
        <div class="oj-detail__head">
          <span :class="statusClass(selected.status)">{{ statusLabel(selected.status) }}</span>
          <code class="oj-job-id">{{ selected.job_id }}</code>
          <button type="button" class="oj-btn oj-btn--ghost" @click="closeDetail">关闭</button>
        </div>
        <p class="oj-detail__brief">{{ selected.task_description }}</p>
        <p class="oj-meta">
          submitted: {{ fmt(selected.submitted_at) }} ·
          started: {{ fmt(selected.started_at) }} ·
          completed: {{ fmt(selected.completed_at) }}
        </p>
        <p v-if="selected.error" class="oj-flash oj-flash--err">{{ selected.error }}</p>

        <section v-if="selected.result?.results?.length">
          <h4 class="oj-subhead">子任务执行（{{ selected.result?.subtask_count ?? selected.result.results.length }} 步）</h4>
          <ul class="oj-sub-list">
            <li
              v-for="(sub, idx) in selected.result.results"
              :key="`${selected.job_id}-${idx}`"
              :class="['oj-sub', sub.ok === false ? 'oj-sub--fail' : 'oj-sub--ok']"
            >
              <div class="oj-sub__head">
                <span class="oj-sub__icon">{{ sub.ok === false ? '✗' : '✓' }}</span>
                <strong class="oj-sub__name">{{ sub.employee_id || '未知员工' }}</strong>
                <span v-if="sub.error" class="oj-sub__err">{{ sub.error }}</span>
              </div>
              <pre v-if="sub.result" class="oj-sub__result">{{
                JSON.stringify(sub.result, null, 2).slice(0, 4000)
              }}</pre>
            </li>
          </ul>
        </section>

        <section v-if="selected.result?.handoff_chain?.length">
          <h4 class="oj-subhead">实时 handoff（{{ selected.result.handoff_chain.length }} 跳）</h4>
          <ol class="oj-handoff">
            <li v-for="(h, idx) in selected.result.handoff_chain" :key="idx">
              <span class="oj-depth">depth {{ h.depth ?? 0 }}</span>
              → <strong>{{ h.to_employee_id }}</strong>
              <span v-if="h.task_brief" class="oj-h-brief">{{ h.task_brief }}</span>
            </li>
          </ol>
        </section>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.oj-page {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  width: 100%;
  padding: 16px 20px;
  gap: 12px;
}

.oj-header {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
}
.oj-title-row {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.oj-title {
  margin: 0;
  font-size: 1.05rem;
  color: var(--color-text-primary, #e5e7eb);
}
.oj-subtitle {
  font-size: 0.78rem;
  color: var(--color-text-muted, #888);
}

.oj-stats {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.oj-stat {
  font-size: 0.76rem;
  padding: 3px 8px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.06);
  color: var(--color-text-secondary, #aaa);
}
.oj-stat strong {
  color: var(--color-text-primary, #e5e7eb);
}
.oj-stat--running { color: #818cf8; background: rgba(129, 140, 248, 0.12); }
.oj-stat--done    { color: #34d399; background: rgba(52, 211, 153, 0.12); }
.oj-stat--failed  { color: #f87171; background: rgba(248, 113, 113, 0.12); }

.oj-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.oj-btn {
  display: inline-flex;
  align-items: center;
  padding: 5px 10px;
  font-size: 0.8rem;
  border-radius: 6px;
  border: 1px solid var(--color-border-subtle, #444);
  background: var(--color-bg-elevated, #1e1e2e);
  color: var(--color-text-primary, #e0e0e0);
  cursor: pointer;
  text-decoration: none;
}
.oj-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.oj-btn--active {
  border-color: #34d399;
  color: #34d399;
  background: rgba(52, 211, 153, 0.1);
}
.oj-btn--ghost { background: transparent; }

.oj-flash {
  padding: 8px 10px;
  border-radius: 6px;
  font-size: 0.82rem;
}
.oj-flash--err {
  color: #fca5a5;
  background: rgba(239, 68, 68, 0.12);
  border: 1px solid rgba(239, 68, 68, 0.3);
}

.oj-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 460px;
  gap: 12px;
  flex: 1;
  min-height: 0;
}
@media (max-width: 1100px) {
  .oj-grid { grid-template-columns: 1fr; }
  .oj-detail { order: -1; }
}

.oj-list {
  border: 1px solid var(--color-border-subtle, #2a2a3a);
  border-radius: 8px;
  overflow: auto;
  background: var(--color-bg-elevated, #14141e);
}
.oj-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.82rem;
}
.oj-table thead th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: var(--color-bg-elevated, #14141e);
  text-align: left;
  font-weight: 600;
  color: var(--color-text-muted, #888);
  padding: 8px 10px;
  border-bottom: 1px solid var(--color-border-subtle, #2a2a3a);
}
.oj-table tbody tr {
  cursor: pointer;
  transition: background 0.12s;
}
.oj-table tbody tr:hover {
  background: rgba(255, 255, 255, 0.04);
}
.oj-table tbody tr.is-active {
  background: rgba(99, 102, 241, 0.12);
}
.oj-table td {
  padding: 8px 10px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  vertical-align: top;
}
.oj-task {
  color: var(--color-text-primary, #e0e0e0);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 60px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.oj-meta {
  font-size: 0.72rem;
  color: var(--color-text-muted, #777);
  margin-top: 3px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.oj-source { color: #818cf8; }

.oj-status {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 0.72rem;
  background: rgba(255, 255, 255, 0.08);
  color: var(--color-text-secondary, #ccc);
}
.oj-status--running { color: #818cf8; background: rgba(129, 140, 248, 0.16); }
.oj-status--done    { color: #34d399; background: rgba(52, 211, 153, 0.16); }
.oj-status--failed  { color: #f87171; background: rgba(248, 113, 113, 0.16); }
.oj-status--pending { color: #fbbf24; background: rgba(251, 191, 36, 0.14); }

.oj-empty {
  padding: 28px;
  text-align: center;
  color: var(--color-text-muted, #888);
}

.oj-detail {
  border: 1px solid var(--color-border-subtle, #2a2a3a);
  border-radius: 8px;
  background: var(--color-bg-elevated, #14141e);
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow: auto;
}
.oj-detail__head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.oj-job-id {
  font-size: 0.74rem;
  color: var(--color-text-muted, #888);
  flex: 1;
}
.oj-detail__brief {
  margin: 0;
  white-space: pre-wrap;
  font-size: 0.86rem;
  color: var(--color-text-primary, #eaeaea);
}

.oj-subhead {
  margin: 6px 0 4px 0;
  font-size: 0.82rem;
  color: var(--color-text-secondary, #c8c8c8);
  border-bottom: 1px solid var(--color-border-subtle, #2a2a3a);
  padding-bottom: 4px;
}

.oj-sub-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; }
.oj-sub {
  border: 1px solid var(--color-border-subtle, #2a2a3a);
  border-radius: 6px;
  padding: 7px 10px;
  background: rgba(255, 255, 255, 0.02);
}
.oj-sub--fail { border-color: rgba(239, 68, 68, 0.4); background: rgba(239, 68, 68, 0.05); }
.oj-sub--ok   { border-color: rgba(52, 211, 153, 0.3); background: rgba(52, 211, 153, 0.04); }
.oj-sub__head { display: flex; gap: 8px; align-items: center; }
.oj-sub__icon { width: 16px; }
.oj-sub--fail .oj-sub__icon { color: #f87171; }
.oj-sub--ok   .oj-sub__icon { color: #34d399; }
.oj-sub__name { color: var(--color-text-primary, #eaeaea); font-size: 0.82rem; }
.oj-sub__err  { color: #fca5a5; font-size: 0.78rem; }
.oj-sub__result {
  margin: 6px 0 0 0;
  max-height: 220px;
  overflow: auto;
  font-size: 0.7rem;
  background: rgba(0, 0, 0, 0.25);
  padding: 6px;
  border-radius: 4px;
}

.oj-handoff { padding-left: 18px; margin: 0; display: flex; flex-direction: column; gap: 4px; font-size: 0.82rem; }
.oj-depth { font-size: 0.72rem; color: var(--color-text-muted, #888); margin-right: 4px; }
.oj-h-brief { color: var(--color-text-secondary, #aaa); margin-left: 6px; }

.oj-denied {
  padding: 2rem;
  text-align: center;
  color: var(--color-text-secondary, #aaa);
}
.btn {
  display: inline-block;
  margin-top: 1rem;
  padding: 0.5rem 1rem;
  border-radius: 8px;
  text-decoration: none;
}
.btn-primary {
  background: #fff;
  color: #0a0a0a;
}

html[data-workbench-theme='light'] .oj-stat{background:rgba(0,0,0,0.04)}
html[data-workbench-theme='light'] .oj-stat--running{background:rgba(99,102,241,0.08);color:#4f46e5}
html[data-workbench-theme='light'] .oj-stat--done{background:rgba(5,150,105,0.08);color:#059669}
html[data-workbench-theme='light'] .oj-stat--failed{background:rgba(220,38,38,0.08);color:#dc2626}
html[data-workbench-theme='light'] .oj-btn{background:#fff;color:#1a1a1a;border-color:#d1d5db}
html[data-workbench-theme='light'] .oj-btn--active{background:rgba(5,150,105,0.08);color:#059669;border-color:#059669}
html[data-workbench-theme='light'] .oj-flash--err{background:rgba(220,38,38,0.06);color:#dc2626;border-color:rgba(220,38,38,0.2)}
html[data-workbench-theme='light'] .oj-list{background:#fff;border-color:#e2e8f0}
html[data-workbench-theme='light'] .oj-table thead th{background:#f8f9fa;color:#64748b;border-color:#e2e8f0}
html[data-workbench-theme='light'] .oj-table tbody tr:hover{background:rgba(0,0,0,0.03)}
html[data-workbench-theme='light'] .oj-table tbody tr.is-active{background:rgba(99,102,241,0.06)}
html[data-workbench-theme='light'] .oj-table td{border-color:rgba(0,0,0,0.06)}
html[data-workbench-theme='light'] .oj-status{background:rgba(0,0,0,0.05);color:#64748b}
html[data-workbench-theme='light'] .oj-detail{background:#fff;border-color:#e2e8f0}
html[data-workbench-theme='light'] .oj-sub{background:rgba(0,0,0,0.02);border-color:#e2e8f0}
html[data-workbench-theme='light'] .oj-sub__result{background:rgba(0,0,0,0.03)}
html[data-workbench-theme='light'] .btn-primary{background:#1a1a1a;color:#fff}
</style>
