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

<!-- 拆分后本文件为组装入口（façade）：样式外移至 ./AdminOrchestrateJobsView.css，模板与逻辑保持原样。 -->
<style scoped src="./AdminOrchestrateJobsView.css"></style>
