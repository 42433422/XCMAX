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
      <div class="kpi">
        <div class="kpi-label">待办</div>
        <div class="kpi-value">{{ pendingCount }}</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">30 天动作</div>
        <div class="kpi-value">{{ window30.action_count ?? '—' }}</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">30 天否决</div>
        <div class="kpi-value">{{ window30.blocked_count ?? '—' }}</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">30 天 veto rate</div>
        <div class="kpi-value">{{ formatRate(window30.veto_rate) }}</div>
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
      <section class="card">
        <h3>最近部署事件</h3>
        <table v-if="deployEvents.length" class="data-table">
          <thead>
            <tr>
              <th>deploy_id</th>
              <th>时间</th>
              <th>状态</th>
              <th>分支</th>
              <th>workflow</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in deployEvents" :key="String(row.deploy_id)">
              <td class="mono">{{ row.deploy_id }}</td>
              <td>{{ row.deployed_at || '—' }}</td>
              <td>{{ row.status || '—' }}</td>
              <td>{{ row.head_branch || '—' }}</td>
              <td>{{ row.source_workflow || '—' }}</td>
            </tr>
          </tbody>
        </table>
        <div v-else class="empty">暂无部署事件</div>
      </section>

      <section class="card">
        <h3>最近审计日志</h3>
        <table v-if="auditItems.length" class="data-table">
          <thead>
            <tr>
              <th>action</th>
              <th>risk</th>
              <th>decision</th>
              <th>actor</th>
              <th>time</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, idx) in auditItems" :key="String(row.id || idx)">
              <td>{{ row.action || '—' }}</td>
              <td>{{ row.risk_level || '—' }}</td>
              <td>{{ row.decision || '—' }}</td>
              <td>{{ row.actor || row.approver || row.source || '—' }}</td>
              <td>{{ row.timestamp || row.created_at || '—' }}</td>
            </tr>
          </tbody>
        </table>
        <div v-else class="empty">暂无审计日志</div>
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
            {{ t }}
          </button>
        </div>
      </div>
      <div class="muted">{{ auditPath || '—' }}</div>
      <ul class="audit-mini">
        <li v-for="(row, idx) in crossAudit" :key="idx">
          <code>{{ row.action || row.event || row.type || 'entry' }}</code>
          <span>{{ row.timestamp || row.ts || '' }}</span>
        </li>
      </ul>
      <div v-if="!crossAudit.length" class="empty">该端暂无可读 audit.jsonl</div>
    </section>
  </div>
</template>

<script lang="ts">
export default { name: 'XCmaxAdminAutonomyTab' }
</script>

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

const pendingCount = computed(() => Number(overview.value?.pending?.count || 0))
const window30 = computed(() => overview.value?.operating_metrics?.windows?.['30'] || {})
const trend = computed(() => overview.value?.operating_metrics?.veto_rate_trend_30d || [])

const trendPoints = computed(() => {
  const rows = Array.isArray(trend.value) ? trend.value : []
  if (rows.length < 2) return []
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
    await switchTier(auditTier.value)
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function switchTier(tier: string) {
  auditTier.value = tier
  try {
    const res = await xcmaxAdminApi.fetchAutonomyAuditCrossTier({ tier, limit: 30 })
    crossAudit.value = Array.isArray(res?.items) ? res.items : []
    auditPath.value = String((res as any)?.path || '')
  } catch {
    crossAudit.value = []
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
.btn {
  border: 1px solid #d0d7e2; background: #fff; border-radius: 8px;
  padding: 8px 12px; cursor: pointer; font-size: 13px;
}
.btn-primary { background: #1890ff; border-color: #1890ff; color: #fff; }
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
  background: rgba(255,255,255,0.92);
  border: 1px solid rgba(15,76,129,0.1);
  border-radius: 14px;
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
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; word-break: break-all; }
.empty { color: #94a3b8; text-align: center; padding: 18px; }
.gate-list, .gh-list, .audit-mini { list-style: none; margin: 0; padding: 0; }
.gate-list li, .gh-list li, .audit-mini li {
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
