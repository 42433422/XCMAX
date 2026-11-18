<template>
  <div class="autonomy-tab">
    <div class="at-head">
      <div class="at-head__title">
        <h2>自治总览</h2>
        <span class="at-head__meta">
          运营总览 {{ overviewReady ? '已读取' : loading ? '读取中' : '待核实' }} ·
          跨端门禁 {{ gateReady ? '已读取' : loading ? '读取中' : '待核实' }} ·
          GitHub {{ githubReady ? '已读取' : loading ? '读取中' : '待核实' }} ·
          数据时间 {{ overview?.generated_at || overview?.operating_metrics?.generated_at || '未提供' }}
        </span>
      </div>
      <div class="at-head__actions">
        <button class="btn btn-secondary" type="button" :disabled="loading" @click="loadAll">
          {{ loading ? '刷新中…' : '刷新' }}
        </button>
        <button class="btn btn-primary" type="button" :disabled="forcing" @click="forceLoop">
          强制运行一次自维护 loop
        </button>
      </div>
    </div>
    <p v-if="error" class="banner-error" role="alert">{{ error }}</p>
    <p v-if="forceMsg" class="banner-ok">{{ forceMsg }}</p>

    <AdminSectionNav v-model="section" label="自治分区" :items="[{ value: 'maintenance', label: '维护执行' }, { value: 'metrics', label: '运行与门禁' }, { value: 'audit', label: '跨端审计' }]" />

    <div v-show="section === 'maintenance'" class="at-panel">
      <MaintenanceExecutionPanel />
    </div>

    <div v-show="section === 'metrics'" class="at-dashboard">
      <div class="kpi-grid">
        <div v-for="[label, value] in kpis" :key="label" class="kpi">
          <div class="kpi-label">{{ label }}</div>
          <div class="kpi-value">{{ value }}</div>
        </div>
      </div>

      <section class="card at-card at-trend">
        <h3>30 天 veto rate 趋势</h3>
        <div class="at-scroll">
          <svg v-if="trendPoints.length > 1" class="chart" viewBox="0 0 320 120" role="img" aria-label="veto rate trend">
            <polyline
              fill="none"
              stroke="#1890ff"
              stroke-width="2"
              :points="trendPoints.map((p) => `${p.x},${p.y}`).join(' ')"
            />
          </svg>
          <div v-else class="empty">暂无足够的快照数据（将随 daily metrics 累积）</div>
        </div>
      </section>

      <section class="card at-card at-gate">
        <h3>跨端门禁</h3>
        <div class="at-scroll">
          <p v-if="!gateRules.length" class="empty">{{ gateReady ? '当前未返回适用规则，动作许可仍待核实。' : '门禁规则尚未读取成功，请重新读取。' }}</p>
          <ul v-else class="gate-list">
            <li v-for="rule in gateRules" :key="rule.tier + rule.action_type">
              <span class="badge" :class="rule.allow === true ? 'ok' : rule.allow === false ? 'err' : ''">{{ rule.allow === true ? '允许' : rule.allow === false ? '阻断' : '待核实' }}</span>
              <div>
                <strong>{{ rule.label || rule.action_type || '未标明动作' }}</strong>
                <div class="muted">{{ (rule.reasons || []).join('；') || '—' }}</div>
              </div>
            </li>
          </ul>
        </div>
      </section>

      <div class="at-recent">
        <section v-for="block in recentSections" :key="block.title" class="card at-card">
          <h3>{{ block.title }}</h3>
          <div class="at-scroll">
            <table v-if="block.rows.length" class="data-table">
              <thead><tr><th v-for="column in block.columns" :key="column">{{ column }}</th></tr></thead>
              <tbody><tr v-for="(row, idx) in block.rows" :key="idx">
                <td v-for="(value, col) in row" :key="col">{{ value ?? '—' }}</td>
              </tr></tbody>
            </table>
            <div v-else class="empty">{{ block.empty }}</div>
          </div>
        </section>
      </div>

      <section class="card at-card at-github">
        <div class="card-head-row">
          <h3>待人工处理的 PR / Issue</h3>
          <a class="link" href="https://github.com/42433422/XCMAX/pulls?q=is%3Aopen+label%3Aneeds-human" target="_blank" rel="noopener">GitHub</a>
        </div>
        <div class="at-scroll">
          <ul v-if="githubItems.length" class="gh-list">
            <li v-for="item in githubItems" :key="`${item.kind}-${item.number}`">
              <a :href="item.url" target="_blank" rel="noopener">
                [{{ item.kind }} #{{ item.number }}] {{ item.title }}
              </a>
            </li>
          </ul>
          <div v-else class="empty">{{ githubError || (githubReady ? '暂无需要人工处理的条目' : 'GitHub 条目尚未核实，请重新读取。') }}</div>
        </div>
      </section>
    </div>

    <section v-show="section === 'audit'" class="card at-audit">
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
      <div class="at-audit__meta">
        <span role="status">{{ auditLoading ? '正在加载审计记录…' : auditMessage }}</span>
        <span class="muted">{{ crossAudit.length }} 条记录 · 最新事件 {{ auditLatest || '未知' }}</span>
        <button type="button" class="btn" :disabled="auditLoading" @click="switchTier(auditTier)">重新读取</button>
      </div>
      <div class="at-scroll">
        <table v-if="crossAudit.length" class="data-table">
          <thead><tr><th>动作</th><th>说明</th><th>时间</th><th>详情</th></tr></thead>
          <tbody><tr v-for="(row, idx) in crossAudit" :key="idx">
            <td>{{ auditAction(row).type || auditAction(row).action || row.event || row.type || '未标注动作' }}</td>
            <td>{{ auditSummary(row) }}</td>
            <td>{{ row.timestamp || row.ts || '未知' }}</td>
            <td><details><summary>原始记录</summary><pre>{{ JSON.stringify(row, null, 2) }}</pre></details></td>
          </tr></tbody>
        </table>
        <div v-else class="empty">暂无审计记录</div>
      </div>
      <details class="at-audit__source"><summary>数据来源</summary><p class="mono">{{ auditPath || '尚未取得来源' }}</p></details>
    </section>
  </div>
</template>

<script setup lang="ts">
import AdminSectionNav from './AdminSectionNav.vue'
const section = ref('maintenance')
import { computed, onMounted, ref } from 'vue'
import MaintenanceExecutionPanel from './MaintenanceExecutionPanel.vue'
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
const overview = ref<Record<string, any> | null>(null)
const overviewReady = ref(false), gateReady = ref(false), githubReady = ref(false)
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
function auditSummary(row: Record<string, any>): string {
  const action = auditAction(row)
  const reasons = Array.isArray(action.reasons) ? action.reasons.filter((item: unknown) => typeof item === 'string').join('；') : ''
  const detail = action.params?.reason || reasons || row.reason || row.diagnosis?.detail || row.result?.detail || row.decision || '查看原始记录'
  const result = row.result?.ok === true ? '成功' : row.result?.ok === false ? '失败' : ''
  return [result, typeof detail === 'string' ? detail : '查看原始记录'].filter(Boolean).join('：')
}
function auditAction(row: Record<string, any>): Record<string, any> {
  return row.action && typeof row.action === 'object' ? row.action : { type: row.action }
}
function recordsKnown(value: unknown): value is Array<Record<string, any>> {
  return Array.isArray(value) && value.every(row => row && typeof row === 'object' && !Array.isArray(row))
}

const window30 = computed(() => overview.value?.operating_metrics?.windows?.['30'] || {})
const kpis = computed(() => [
  ['待办', String(overview.value?.pending?.count ?? '待核实')], ['30 天动作', String(window30.value.action_count ?? '待核实')],
  ['30 天否决', String(window30.value.blocked_count ?? '—')], ['30 天 veto rate', formatRate(window30.value.veto_rate)],
])
const recentSections = computed(() => [
  { title: '最近部署事件', empty: recordsKnown(overview.value?.deploy_events?.items) ? '暂无部署事件' : '部署记录尚未核实，请重新读取总览。', columns: ['发布编号', '时间', '状态', '分支', '工作流'],
    rows: deployEvents.value.map(r => [r.deploy_id, r.deployed_at, r.status, r.head_branch, r.source_workflow]) },
  { title: '最近审计日志', empty: recordsKnown(overview.value?.audit?.items) ? '暂无审计日志' : '审计记录尚未核实，请重新读取总览。', columns: ['动作', '说明', '风险', '结果', '操作方', '时间'],
    rows: auditItems.value.map(r => [auditAction(r).type || auditAction(r).action || '未标注动作', auditSummary(r), r.risk_level, r.decision, r.actor || r.approver || r.source, r.timestamp || r.created_at]) },
])

const trendPoints = computed(() => {
  const rows = overview.value?.operating_metrics?.veto_rate_trend_30d || []
  if (!Array.isArray(rows) || rows.length < 2) return []
  const rates = rows.filter((r: any) => typeof r?.veto_rate === 'number' && Number.isFinite(r.veto_rate)).map((r: any) => r.veto_rate)
  if (rates.length < 2) return []
  const max = Math.max(...rates, 1)
  const min = Math.min(...rates, 0)
  const span = Math.max(max - min, 0.01)
  return rates.map((rate, idx) => ({
    x: (idx / (rates.length - 1)) * 300 + 10,
    y: 100 - ((rate - min) / span) * 80,
  }))
})

function formatRate(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(2)}%` : '待核实'
}

async function loadAll() {
  loading.value = true
  error.value = ''
  overview.value = null; overviewReady.value = gateReady.value = githubReady.value = false
  deployEvents.value = []; auditItems.value = []; gateRules.value = []; githubItems.value = []; githubError.value = ''
  try {
    const results = await Promise.allSettled([
      xcmaxAdminApi.fetchAutonomyOverview(),
      xcmaxAdminApi.fetchAutonomyGithubItems(30),
      xcmaxAdminApi.fetchAutonomyCrossTierGate(),
    ])
    const failures: string[] = []
    const labels = ['运营总览', 'GitHub 条目', '跨端门禁']
    results.forEach((result, index) => {
      try {
        if (result.status === 'rejected') throw result.reason
        const data = result.value as Record<string, any>
        if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('返回数据无法识别')
        if (index === 0) {
          if (!data.pending || typeof data.pending.count !== 'number' || !Number.isInteger(data.pending.count) || data.pending.count < 0) throw new Error('未返回可核实的待办状态')
          overview.value = data; overviewReady.value = true
          deployEvents.value = recordsKnown(data.deploy_events?.items) ? data.deploy_events.items : []
          auditItems.value = recordsKnown(data.audit?.items) ? data.audit.items : []
        } else if (index === 1) {
          if (!recordsKnown(data.items)) throw new Error('未返回有效条目清单')
          githubItems.value = data.items
          githubError.value = Array.isArray(data.errors) && data.errors.length ? String(data.errors[0]) : ''
          githubReady.value = !githubError.value
        } else {
          if (!recordsKnown(data.rules)) throw new Error('未返回有效门禁规则')
          gateRules.value = data.rules; gateReady.value = true
        }
      } catch (cause) { failures.push(`${labels[index]}读取失败：${cause instanceof Error ? cause.message : '暂时无法核实'}`) }
    })
    error.value = failures.join('；')
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
    if (!res || typeof res !== 'object' || res.ok === false || !Array.isArray(res.items) || res.items.some((item: unknown) => !item || typeof item !== 'object' || Array.isArray(item)) || (res.status && !Object.hasOwn(auditMessages, res.status))) throw new Error('audit_load_failed')
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
/* 仪表盘式布局：页头与指标条固定，卡片占满剩余高度并在内部滚动。 */
.autonomy-tab {
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  padding: 0;
}
.at-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex: 0 0 auto;
}
.at-head__title {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 4px 10px;
  min-width: 0;
}
.at-head__title h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #172033;
}
.at-head__meta {
  color: #64748b;
  font-size: 12px;
}
.at-head__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.btn:disabled { opacity: 0.6; cursor: not-allowed; }
.banner-error,
.banner-ok {
  border-radius: 8px;
  padding: 8px 12px;
  margin: 0;
  font-size: 13px;
  flex: 0 0 auto;
}
.banner-error { background: #fff1f0; color: #cf1322; border: 1px solid #ffa39e; }
.banner-ok { background: #ecfdf5; color: #047857; border: 1px solid #bbf7d0; }
.at-panel {
  flex: 1 1 0;
  min-height: 0;
  overflow: auto;
}
.at-dashboard {
  display: grid;
  flex: 1 1 0;
  grid-template-columns: minmax(0, 1.55fr) minmax(0, 1fr);
  grid-template-rows: auto minmax(0, 1fr) minmax(0, 1fr);
  gap: 10px;
  min-height: 0;
}
.kpi-grid {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 8px;
}
.kpi {
  min-width: 0;
  padding: 8px 14px;
  border: 1px solid rgba(15, 76, 129, 0.1);
  border-radius: 10px;
  background: #fff;
}
.kpi-label { color: #64748b; font-size: 12px; }
.kpi-value {
  margin-top: 2px;
  color: #172033;
  font-size: 20px;
  font-weight: 700;
  line-height: 1.25;
  font-variant-numeric: tabular-nums;
}
.card {
  background: #fff;
  border: 1px solid rgba(15, 76, 129, 0.1);
  border-radius: 10px;
}
.at-card {
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 10px 14px;
  overflow: hidden;
}
.at-card h3 {
  flex: 0 0 auto;
  margin: 0 0 8px;
  font-size: 14px;
  font-weight: 600;
  color: #172033;
}
.at-trend { grid-column: 1; grid-row: 2; }
.at-gate { grid-column: 2; grid-row: 2; }
.at-recent {
  display: grid;
  grid-column: 1;
  grid-row: 3;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  min-height: 0;
}
.at-github { grid-column: 2; grid-row: 3; }
.at-scroll {
  flex: 1 1 0;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
}
.chart {
  width: 100%;
  height: 100%;
  min-height: 90px;
  background: #f8fafc;
  border-radius: 8px;
}
.data-table {
  width: 100%;
  min-width: 480px;
  border-collapse: collapse;
  font-size: 12px;
}
.data-table th,
.data-table td {
  padding: 6px 8px;
  border-bottom: 1px solid #eef2f7;
  text-align: left;
  vertical-align: top;
  overflow-wrap: anywhere;
}
.data-table th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: #f7fafd;
  color: #64748b;
  font-weight: 600;
  white-space: nowrap;
}
.data-table pre {
  max-width: 480px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; word-break: break-all; }
.empty { color: #94a3b8; text-align: center; padding: 18px; }
.gate-list,
.gh-list { list-style: none; margin: 0; padding: 0; }
.gate-list li,
.gh-list li {
  display: flex;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid #eef2f7;
}
.gate-list li:last-child,
.gh-list li:last-child { border-bottom: none; }
.badge {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  flex-shrink: 0;
}
.badge.ok { background: #e6f9f0; color: #10b759; }
.badge.err { background: #fff1f0; color: #e53e3e; }
.muted { color: #94a3b8; font-size: 12px; }
.card-head-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  flex: 0 0 auto;
}
.card-head-row h3 { margin: 0; }
.tabs { display: flex; flex-wrap: wrap; gap: 6px; }
.tabs button {
  border: 1px solid #d0d7e2;
  background: #fff;
  border-radius: 999px;
  padding: 4px 10px;
  cursor: pointer;
  font-size: 12px;
}
.tabs button.active { background: #1890ff; border-color: #1890ff; color: #fff; }
.link { color: #1890ff; text-decoration: none; font-size: 12px; }
.at-audit {
  display: flex;
  flex: 1 1 0;
  flex-direction: column;
  min-height: 0;
  padding: 10px 14px;
  overflow: hidden;
}
.at-audit__meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 12px;
  flex: 0 0 auto;
  margin: 8px 0;
  color: #475569;
  font-size: 12px;
}
.at-audit__source { flex: 0 0 auto; margin-top: 6px; font-size: 12px; }
@media (max-width: 1099px) {
  .autonomy-tab {
    height: auto;
    min-height: 100%;
    overflow-y: auto;
  }
  .at-dashboard {
    display: flex;
    flex-direction: column;
    height: auto;
    min-height: 0;
  }
  .at-card,
  .at-audit { min-height: 220px; }
  .at-recent { grid-template-columns: 1fr; }
  .at-scroll { max-height: 320px; }
}
</style>
