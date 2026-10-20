<template>
  <div class="autonomy-tab">
    <div class="page-header">
      <div>
        <h2>自治总览</h2>
        <p>运营指标 · 部署事件 · 审计 · 跨端门禁 · GitHub 待处理</p>
      </div>
      <div class="header-actions">
        <button class="btn btn-secondary" type="button" :disabled="loading" @click="loadAll">
          {{ loading ? '刷新中…' : '刷新' }}
        </button>
        <button class="btn btn-primary" type="button" :disabled="forcing" @click="forceLoop">
          强制运行一次自维护 loop
        </button>
      </div>
    </div>
    <p v-if="error" class="banner-error">{{ error }}</p>
    <p v-if="forceMsg" class="banner-ok">{{ forceMsg }}</p>

    <div class="kpi-grid">
      <div v-for="[label, value] in kpis" :key="label" class="kpi">
        <div class="kpi-label">{{ label }}</div><div class="kpi-value">{{ value }}</div>
      </div>
    </div>

    <section class="card">
      <h3>30 天 veto rate 趋势</h3>
      <svg v-if="trendPoints.length > 1" class="chart" viewBox="0 0 320 120" role="img" aria-label="veto rate trend">
        <polyline
          fill="none"
          stroke="#1890ff"
          stroke-width="2"
          :points="trendPoints.map((p) => `${p.x},${p.y}`).join(' ')"
        />
      </svg>
      <div v-else class="empty">暂无足够的快照数据（将随 daily metrics 累积）</div>
    </section>

    <div class="split">
      <section v-for="section in recentSections" :key="section.title" class="card">
        <h3>{{ section.title }}</h3>
        <table v-if="section.rows.length" class="data-table">
          <thead><tr><th v-for="column in section.columns" :key="column">{{ column }}</th></tr></thead>
          <tbody><tr v-for="(row, idx) in section.rows" :key="idx">
            <td v-for="(value, col) in row" :key="col">{{ value || '—' }}</td>
          </tr></tbody>
        </table>
        <div v-else class="empty">{{ section.empty }}</div>
      </section>
    </div>

    <div class="split">
      <section class="card">
        <h3>跨端门禁</h3>
        <ul class="gate-list">
          <li v-for="rule in gateRules" :key="rule.tier + rule.action_type">
            <span class="badge" :class="rule.allow ? 'ok' : 'err'">{{ rule.allow ? '通过' : '阻断' }}</span>
            <div>
              <strong>{{ rule.label }}</strong>
              <div class="muted">{{ (rule.reasons || []).join('；') || '—' }}</div>
            </div>
          </li>
        </ul>
      </section>

      <section class="card">
        <div class="card-head-row">
          <h3>待人工处理的 PR / Issue</h3>
          <a class="link" href="https://github.com/42433422/XCMAX/pulls?q=is%3Aopen+label%3Aneeds-human" target="_blank" rel="noopener">GitHub</a>
        </div>
        <ul v-if="githubItems.length" class="gh-list">
          <li v-for="item in githubItems" :key="`${item.kind}-${item.number}`">
            <a :href="item.url" target="_blank" rel="noopener">
              [{{ item.kind }} #{{ item.number }}] {{ item.title }}
            </a>
          </li>
        </ul>
        <div v-else class="empty">{{ githubError || '暂无 needs-human / ai-self-heal 条目' }}</div>
      </section>
    </div>

    <section class="card">
      <div class="card-head-row">
        <h3>跨端审计</h3>
        <div class="tabs">
          <button
            v-for="t in ['desktop', 'server', 'ci']"
            :key="t"
            type="button"
            :class="{ active: auditTier === t }"
            @click="switchTier(t)"
          >
            {{ tierLabels[t] }}
          </button>
        </div>
      </div>
      <p role="status">{{ auditLoading ? '正在加载审计记录…' : auditMessage }}</p>
      <p class="muted">{{ crossAudit.length }} 条记录 · 最新事件 {{ auditLatest || '未知' }} · 超过 24 小时提示过期，不代表服务故障</p>
      <button type="button" class="btn" :disabled="auditLoading" @click="switchTier(auditTier)">重新读取</button>
      <table v-if="crossAudit.length" class="data-table">
        <thead><tr><th>动作</th><th>说明</th><th>时间</th><th>详情</th></tr></thead>
        <tbody><tr v-for="(row, idx) in crossAudit" :key="idx">
          <td>{{ auditAction(row).type || auditAction(row).action || row.event || row.type || '未标注动作' }}</td>
          <td>{{ auditAction(row).params?.reason || row.reason || row.decision || '查看原始记录' }}</td>
          <td>{{ row.timestamp || row.ts || '未知' }}</td>
          <td><details><summary>原始记录</summary><pre>{{ JSON.stringify(row, null, 2) }}</pre></details></td>
        </tr></tbody>
      </table>
      <details><summary>数据来源</summary><p class="mono">{{ auditPath || '尚未取得来源' }}</p><p>读取服务端可见的该端审计文件，不代表已实时连接其他设备。</p></details>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  xcmaxAdminApi,
  type AutonomyDeployEvent,
  type AutonomyGithubItem,
} from '@/api/xcmaxAdmin'
import { appConfirm } from '@/utils/appDialog'

const loading = ref(false)
const forcing = ref(false)
const error = ref('')
const forceMsg = ref('')
const overview = ref<Record<string, any>>({})
const deployEvents = ref<AutonomyDeployEvent[]>([])
const auditItems = ref<Record<string, any>[]>([])
const githubItems = ref<AutonomyGithubItem[]>([])
const githubError = ref('')
const gateRules = ref<Array<Record<string, any>>>([])
const auditTier = ref('server')
const crossAudit = ref<Record<string, any>[]>([])
const auditPath = ref('')
const auditLoading = ref(false)
const auditStatus = ref('')
const auditLatest = ref('')
let auditRequest = 0
const tierLabels: Record<string, string> = { desktop: '桌面端', server: '服务器', ci: '持续集成' }
const auditMessages: Record<string, string> = {
  ready: '已加载审计记录。', stale: '数据已过期：请检查该端审计采集与同步，再重新读取。',
  not_connected: '数据源未接入：未找到该端审计文件，请检查采集路径和同步配置。',
  empty: '数据源已接入，但尚无审计记录。',
  error: '加载失败：请检查网络、登录状态及审计文件权限或格式，再重新读取。',
  unknown_freshness: '已加载记录，但无法核实数据时效，请检查记录时间。',
}
const auditMessage = computed(() => auditMessages[auditStatus.value] || '尚未读取审计数据。')
function auditAction(row: Record<string, any>): Record<string, any> {
  return row.action && typeof row.action === 'object' ? row.action : { type: row.action }
}

const window30 = computed(() => overview.value?.operating_metrics?.windows?.['30'] || {})
const kpis = computed(() => [
  ['待办', String(overview.value?.pending?.count || 0)], ['30 天动作', String(window30.value.action_count ?? '—')],
  ['30 天否决', String(window30.value.blocked_count ?? '—')], ['30 天 veto rate', formatRate(window30.value.veto_rate)],
])
const recentSections = computed(() => [
  { title: '最近部署事件', empty: '暂无部署事件', columns: ['deploy_id', '时间', '状态', '分支', 'workflow'],
    rows: deployEvents.value.map(r => [r.deploy_id, r.deployed_at, r.status, r.head_branch, r.source_workflow]) },
  { title: '最近审计日志', empty: '暂无审计日志', columns: ['action', 'risk', 'decision', 'actor', 'time'],
    rows: auditItems.value.map(r => [r.action, r.risk_level, r.decision, r.actor || r.approver || r.source, r.timestamp || r.created_at]) },
])

const trendPoints = computed(() => {
  const rows = overview.value?.operating_metrics?.veto_rate_trend_30d || []
  if (!Array.isArray(rows) || rows.length < 2) return []
  const rates = rows.map((r: any) => Number(r.veto_rate || 0))
  const max = Math.max(...rates, 1)
  const min = Math.min(...rates, 0)
  const span = Math.max(max - min, 0.01)
  return rates.map((rate, idx) => ({
    x: (idx / (rates.length - 1)) * 300 + 10,
    y: 100 - ((rate - min) / span) * 80,
  }))
})

function formatRate(value: unknown) {
  if (value == null || value === '') return '—'
  const n = Number(value)
  if (Number.isNaN(n)) return String(value)
  return `${n.toFixed(2)}%`
}

async function loadAll() {
  loading.value = true
  error.value = ''
  try {
    const [ov, gh, gate] = await Promise.all([
      xcmaxAdminApi.fetchAutonomyOverview(),
      xcmaxAdminApi.fetchAutonomyGithubItems(30),
      xcmaxAdminApi.fetchAutonomyCrossTierGate(),
    ])
    overview.value = ov || {}
    deployEvents.value = Array.isArray(ov?.deploy_events?.items) ? ov.deploy_events.items : []
    auditItems.value = Array.isArray(ov?.audit?.items) ? ov.audit.items : []
    githubItems.value = Array.isArray(gh?.items) ? gh.items : []
    githubError.value = Array.isArray(gh?.errors) && gh.errors.length ? String(gh.errors[0]) : ''
    gateRules.value = Array.isArray((gate as any)?.rules) ? (gate as any).rules : []
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    await switchTier(auditTier.value)
    loading.value = false
  }
}

async function switchTier(tier: string) {
  const request = ++auditRequest
  auditTier.value = tier
  auditLoading.value = true
  crossAudit.value = []
  auditPath.value = auditLatest.value = ''
  try {
    const res = await xcmaxAdminApi.fetchAutonomyAuditCrossTier({ tier, limit: 30 })
    if (request !== auditRequest) return
    if (res?.ok === false) throw new Error('audit_load_failed')
    crossAudit.value = Array.isArray(res?.items) ? res.items : []
    auditPath.value = res?.path || ''
    auditLatest.value = res?.last_event_at || ''
    auditStatus.value = res?.status || (res?.exists === false ? 'not_connected' : crossAudit.value.length ? 'unknown_freshness' : 'empty')
  } catch {
    if (request === auditRequest) auditStatus.value = 'error'
  } finally {
    if (request === auditRequest) auditLoading.value = false
  }
}

async function forceLoop() {
  const ok = await appConfirm('确认强制运行一次自维护 loop？可能占用 Para/Codex 设备并持续数分钟。')
  if (!ok) return
  forcing.value = true
  forceMsg.value = ''
  try {
    const res = await xcmaxAdminApi.forceSelfMaintenanceRun('admin_console_force_run')
    const nested = (res?.result && typeof res.result === 'object') ? res.result as Record<string, unknown> : {}
    const deeper = (nested.result && typeof nested.result === 'object')
      ? nested.result as Record<string, unknown>
      : {}
    const runId = nested.run_id || deeper.run_id || '—'
    forceMsg.value = `已触发 force-run，run_id=${runId}。可到员工可视化 · loop runtime 面板轮询。`
    await loadAll()
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    forcing.value = false
  }
}

onMounted(() => {
  void loadAll()
})
</script>

<style scoped>
.autonomy-tab { display: flex; flex-direction: column; gap: 14px; }
.page-header {
  display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap;
}
.page-header h2 { margin: 0 0 4px; font-size: 20px; }
.page-header p { margin: 0; color: #64748b; font-size: 13px; }
.header-actions { display: flex; gap: 8px; }
.btn:disabled { opacity: 0.6; cursor: not-allowed; }
.banner-error, .banner-ok {
  border-radius: 8px; padding: 10px 12px; margin: 0; font-size: 13px;
}
.banner-error { background: #fff1f0; color: #cf1322; border: 1px solid #ffa39e; }
.banner-ok { background: #ecfdf5; color: #047857; border: 1px solid #bbf7d0; }
.kpi-grid {
  display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px;
}
@media (max-width: 900px) { .kpi-grid { grid-template-columns: repeat(2, 1fr); } }
.kpi, .card {
  padding: 14px;
}
.kpi-label { color: #64748b; font-size: 12px; }
.kpi-value { font-size: 24px; font-weight: 700; color: #172033; margin-top: 4px; }
.card h3 { margin: 0 0 10px; font-size: 15px; }
.chart { width: 100%; height: 120px; background: #f8fafc; border-radius: 8px; }
.split { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
@media (max-width: 960px) { .split { grid-template-columns: 1fr; } }
.data-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.data-table th, .data-table td {
  text-align: left; padding: 6px 8px; border-bottom: 1px solid #eef2f7; vertical-align: top;
}
.data-table pre { white-space: pre-wrap; overflow-wrap: anywhere; max-width: 480px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; word-break: break-all; }
.empty { color: #94a3b8; text-align: center; padding: 18px; }
.gate-list, .gh-list { list-style: none; margin: 0; padding: 0; }
.gate-list li, .gh-list li {
  display: flex; gap: 10px; padding: 8px 0; border-bottom: 1px solid #eef2f7;
}
.badge {
  display: inline-flex; align-items: center; height: 22px; padding: 0 8px;
  border-radius: 999px; font-size: 11px; font-weight: 700;
}
.badge.ok { background: #e6f9f0; color: #10b759; }
.badge.err { background: #fff1f0; color: #e53e3e; }
.muted { color: #94a3b8; font-size: 12px; }
.card-head-row { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.card-head-row h3 { margin: 0; }
.tabs { display: flex; gap: 6px; }
.tabs button {
  border: 1px solid #d0d7e2; background: #fff; border-radius: 999px;
  padding: 4px 10px; cursor: pointer; font-size: 12px;
}
.tabs button.active { background: #1890ff; border-color: #1890ff; color: #fff; }
.link { color: #1890ff; text-decoration: none; font-size: 12px; }
</style>
