<template>
  <div class="attendance-dashboard page-view">
    <header class="dashboard-hero">
      <div>
        <p class="dashboard-eyebrow">SUNBIRD · 通用考勤</p>
        <h2>考勤看板</h2>
        <p class="dashboard-subtitle">集中查看人员覆盖、考勤数据与异常情况。</p>
      </div>
      <div class="dashboard-actions">
        <router-link class="dashboard-action dashboard-action--primary" :to="{ name: 'attendance-industry-home' }">
          上传考勤表
        </router-link>
        <router-link class="dashboard-action" :to="{ name: 'attendance-industry-settings' }">考勤设置</router-link>
        <button type="button" class="dashboard-action" :disabled="loading" @click="loadDashboard">
          {{ loading ? '刷新中…' : '刷新数据' }}
        </button>
      </div>
    </header>

    <div v-if="loading && !dashboard" class="dashboard-state" aria-live="polite">正在读取考勤数据…</div>
    <div v-else-if="error" class="dashboard-state dashboard-state--error" role="alert">
      <strong>看板暂时无法加载</strong>
      <span>{{ error }}</span>
      <button type="button" class="dashboard-action" @click="loadDashboard">重新加载</button>
    </div>

    <template v-else-if="dashboard">
      <section class="metric-grid" aria-label="考勤关键指标">
        <article class="metric-card">
          <span class="metric-label">当前人员</span>
          <strong>{{ formatNumber(dashboard.employees_total) }}</strong>
          <small>已进入考勤人员库</small>
        </article>
        <article class="metric-card">
          <span class="metric-label">部门数量</span>
          <strong>{{ formatNumber(dashboard.departments_total) }}</strong>
          <small>当前组织覆盖</small>
        </article>
        <article class="metric-card">
          <span class="metric-label">考勤明细</span>
          <strong>{{ formatNumber(dashboard.daily_records_total) }}</strong>
          <small>{{ dashboard.months_total ? `覆盖 ${dashboard.months_total} 个月` : '尚未形成月度数据' }}</small>
        </article>
        <article class="metric-card" :class="{ 'metric-card--warning': dashboard.anomaly_records_total > 0 }">
          <span class="metric-label">异常记录</span>
          <strong>{{ formatNumber(dashboard.anomaly_records_total) }}</strong>
          <small>迟到、早退、缺卡、请假或缺勤</small>
        </article>
      </section>

      <section class="readiness-card" :class="`readiness-card--${dashboard.readiness}`">
        <div class="readiness-icon" aria-hidden="true">{{ readinessIcon }}</div>
        <div>
          <strong>{{ readinessTitle }}</strong>
          <p>{{ readinessDescription }}</p>
        </div>
        <router-link v-if="dashboard.readiness !== 'ready'" class="dashboard-action dashboard-action--primary" :to="{ name: 'attendance-industry-home' }">
          去上传转换
        </router-link>
      </section>

      <div class="dashboard-grid">
        <section class="dashboard-panel" aria-labelledby="department-title">
          <div class="panel-heading">
            <div>
              <p class="panel-kicker">组织覆盖</p>
              <h3 id="department-title">部门人员分布</h3>
            </div>
            <span>{{ dashboard.employees_total }} 人</span>
          </div>
          <div v-if="dashboard.department_breakdown.length" class="department-list">
            <div v-for="item in dashboard.department_breakdown" :key="item.department" class="department-row">
              <div class="department-row__meta">
                <span>{{ item.department }}</span>
                <strong>{{ item.employees }} 人</strong>
              </div>
              <div class="department-bar" aria-hidden="true">
                <span :style="{ width: departmentWidth(item.employees) }" />
              </div>
            </div>
          </div>
          <p v-else class="panel-empty">尚未导入人员与部门数据。</p>
        </section>

        <section class="dashboard-panel" aria-labelledby="import-title">
          <div class="panel-heading">
            <div>
              <p class="panel-kicker">数据状态</p>
              <h3 id="import-title">最近导入</h3>
            </div>
            <span v-if="dashboard.latest_month">{{ dashboard.latest_month }}</span>
          </div>

          <dl v-if="dashboard.latest_import" class="import-details">
            <div>
              <dt>文件</dt>
              <dd :title="dashboard.latest_import.source_file">{{ latestImportName }}</dd>
            </div>
            <div>
              <dt>写入结果</dt>
              <dd>{{ dashboard.latest_import.rows_written }} / {{ dashboard.latest_import.rows_in }} 行</dd>
            </div>
            <div>
              <dt>导入时间</dt>
              <dd>{{ formatDateTime(dashboard.latest_import.imported_at) }}</dd>
            </div>
            <div>
              <dt>数据日期</dt>
              <dd>{{ dateRangeText }}</dd>
            </div>
          </dl>
          <div v-else class="panel-empty panel-empty--action">
            <span>尚无考勤导入记录。</span>
            <router-link :to="{ name: 'attendance-industry-home' }">上传第一份考勤表</router-link>
          </div>
        </section>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { apiFetch } from '@/utils/apiBase'

interface DepartmentBreakdown {
  department: string
  employees: number
}

interface LatestImport {
  source_file: string
  month_label: string
  rows_in: number
  rows_written: number
  imported_at: string
}

interface AttendanceDashboard {
  employees_total: number
  departments_total: number
  daily_records_total: number
  anomaly_records_total: number
  months_total: number
  latest_month: string
  date_from: string
  date_to: string
  latest_import: LatestImport | null
  department_breakdown: DepartmentBreakdown[]
  readiness: 'empty' | 'needs_records' | 'ready'
}

const loading = ref(false)
const error = ref('')
const dashboard = ref<AttendanceDashboard | null>(null)

const maxDepartmentEmployees = computed(() =>
  Math.max(0, ...(dashboard.value?.department_breakdown || []).map((item) => Number(item.employees) || 0)),
)

const readinessIcon = computed(() => {
  if (dashboard.value?.readiness === 'ready') return '✓'
  if (dashboard.value?.readiness === 'needs_records') return '→'
  return '+'
})

const readinessTitle = computed(() => {
  if (dashboard.value?.readiness === 'ready') return '考勤数据已就绪'
  if (dashboard.value?.readiness === 'needs_records') return '人员已就绪，等待考勤明细'
  return '先导入人员和考勤数据'
})

const readinessDescription = computed(() => {
  if (dashboard.value?.readiness === 'ready') {
    return dashboard.value.latest_month ? `当前最新统计月份为 ${dashboard.value.latest_month}。` : '已可以查看考勤统计与异常。'
  }
  if (dashboard.value?.readiness === 'needs_records') return '人员与部门已经存在，上传钉钉考勤表后即可形成月度统计。'
  return '当前考勤库为空，完成首次上传后看板会自动汇总。'
})

const latestImportName = computed(() => {
  const source = String(dashboard.value?.latest_import?.source_file || '').replace(/\\/g, '/')
  return source.split('/').pop() || source || '未命名文件'
})

const dateRangeText = computed(() => {
  const from = dashboard.value?.date_from || ''
  const to = dashboard.value?.date_to || ''
  if (from && to) return from === to ? from : `${from} 至 ${to}`
  return '暂无明细日期'
})

function formatNumber(value: number): string {
  return new Intl.NumberFormat('zh-CN').format(Number(value) || 0)
}

function formatDateTime(value: string): string {
  const text = String(value || '').trim()
  if (!text) return '—'
  return text.replace('T', ' ').slice(0, 16)
}

function departmentWidth(value: number): string {
  const max = maxDepartmentEmployees.value
  if (!max) return '0%'
  return `${Math.max(5, Math.round(((Number(value) || 0) / max) * 100))}%`
}

async function loadDashboard() {
  loading.value = true
  error.value = ''
  try {
    const response = await apiFetch('/api/mod/attendance-industry/attendance/dashboard')
    const payload = await response.json().catch(() => ({}))
    if (!response.ok || !payload.success || !payload.data) {
      throw new Error(payload.message || payload.error || `HTTP ${response.status}`)
    }
    dashboard.value = payload.data as AttendanceDashboard
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void loadDashboard()
})
</script>

<style scoped>
.attendance-dashboard {
  --dashboard-ink: #172038;
  --dashboard-muted: #667085;
  --dashboard-border: #e7eaf0;
  min-height: 100%;
  padding: 28px;
  color: var(--dashboard-ink);
  background:
    radial-gradient(circle at 92% 0%, rgba(255, 183, 77, 0.12), transparent 28%),
    #f7f8fb;
}

.dashboard-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 24px;
}

.dashboard-eyebrow,
.panel-kicker {
  margin: 0 0 6px;
  color: #b36b17;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.dashboard-hero h2 {
  margin: 0;
  font-size: 30px;
  letter-spacing: -0.03em;
}

.dashboard-subtitle {
  margin: 8px 0 0;
  color: var(--dashboard-muted);
}

.dashboard-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.dashboard-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 36px;
  padding: 0 14px;
  border: 1px solid #d7dce5;
  border-radius: 9px;
  background: #fff;
  color: #344054;
  font: inherit;
  font-size: 13px;
  font-weight: 650;
  text-decoration: none;
  cursor: pointer;
}

.dashboard-action:hover {
  border-color: #b6bfcc;
  background: #fafbfc;
}

.dashboard-action:disabled {
  opacity: 0.55;
  cursor: default;
}

.dashboard-action--primary {
  border-color: #d97706;
  background: #d97706;
  color: #fff;
}

.dashboard-action--primary:hover {
  border-color: #b45309;
  background: #b45309;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.metric-card,
.dashboard-panel,
.readiness-card,
.dashboard-state {
  border: 1px solid var(--dashboard-border);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 8px 24px rgba(23, 32, 56, 0.045);
}

.metric-card {
  display: flex;
  min-height: 126px;
  flex-direction: column;
  padding: 18px 20px;
}

.metric-card strong {
  margin: 8px 0 4px;
  font-size: 30px;
  line-height: 1;
}

.metric-card small,
.metric-label {
  color: var(--dashboard-muted);
}

.metric-label {
  font-size: 13px;
  font-weight: 650;
}

.metric-card--warning strong {
  color: #c2410c;
}

.readiness-card {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 14px;
  margin-top: 14px;
  padding: 16px 18px;
}

.readiness-icon {
  display: grid;
  width: 38px;
  height: 38px;
  place-items: center;
  border-radius: 50%;
  background: #fff7ed;
  color: #c2410c;
  font-size: 20px;
  font-weight: 800;
}

.readiness-card--ready .readiness-icon {
  background: #ecfdf3;
  color: #15803d;
}

.readiness-card strong {
  font-size: 14px;
}

.readiness-card p {
  margin: 4px 0 0;
  color: var(--dashboard-muted);
  font-size: 13px;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(320px, 0.75fr);
  gap: 14px;
  margin-top: 14px;
}

.dashboard-panel {
  min-height: 300px;
  padding: 20px;
}

.panel-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}

.panel-heading h3 {
  margin: 0;
  font-size: 18px;
}

.panel-heading > span {
  border-radius: 999px;
  background: #f2f4f7;
  padding: 5px 9px;
  color: #475467;
  font-size: 12px;
  font-weight: 650;
}

.department-list {
  display: grid;
  gap: 14px;
}

.department-row__meta {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 6px;
  font-size: 13px;
}

.department-row__meta strong {
  white-space: nowrap;
}

.department-bar {
  height: 7px;
  overflow: hidden;
  border-radius: 999px;
  background: #f0f2f5;
}

.department-bar span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #f59e0b, #d97706);
}

.import-details {
  display: grid;
  gap: 0;
  margin: 0;
}

.import-details > div {
  display: grid;
  grid-template-columns: 80px minmax(0, 1fr);
  gap: 12px;
  padding: 14px 0;
  border-bottom: 1px solid #eef0f3;
}

.import-details > div:last-child {
  border-bottom: 0;
}

.import-details dt {
  color: var(--dashboard-muted);
  font-size: 13px;
}

.import-details dd {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  color: #344054;
  font-size: 13px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.panel-empty,
.dashboard-state {
  color: var(--dashboard-muted);
}

.panel-empty--action {
  display: grid;
  min-height: 180px;
  place-content: center;
  gap: 10px;
  text-align: center;
}

.panel-empty--action a {
  color: #b45309;
  font-weight: 650;
}

.dashboard-state {
  display: grid;
  min-height: 220px;
  place-content: center;
  gap: 10px;
  padding: 28px;
  text-align: center;
}

.dashboard-state--error strong {
  color: #b42318;
}

@media (max-width: 1000px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .dashboard-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .attendance-dashboard {
    padding: 18px;
  }

  .dashboard-hero {
    flex-direction: column;
  }

  .dashboard-actions {
    justify-content: flex-start;
  }

  .metric-grid {
    grid-template-columns: 1fr;
  }

  .readiness-card {
    grid-template-columns: auto minmax(0, 1fr);
  }

  .readiness-card .dashboard-action {
    grid-column: 1 / -1;
  }
}
</style>
