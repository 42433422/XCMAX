<template>
  <div class="employee-autonomy-view" id="view-employee-autonomy">
    <div class="page-header">
      <div>
        <h2>员工自治</h2>
        <p>运行自洽 · 履职覆盖 · 建议看板 · 问答 · 成绩单</p>
      </div>
      <div class="header-actions">
        <button class="btn btn-secondary" type="button" :disabled="loading" @click="refresh">
          {{ loading ? '刷新中…' : '刷新' }}
        </button>
        <button class="btn btn-primary" type="button" :disabled="!selectedIds.length || acting" @click="batchApprove">
          批量通过 ({{ selectedIds.length }})
        </button>
      </div>
    </div>
    <p v-if="error" class="banner-error">{{ error }}</p>

    <nav class="tabs">
      <button type="button" :class="{ active: tab === 'consistency' }" @click="tab = 'consistency'">自洽总览</button>
      <button type="button" :class="{ active: tab === 'suggestions' }" @click="tab = 'suggestions'">建议看板</button>
      <button type="button" :class="{ active: tab === 'questions' }" @click="tab = 'questions'">问答</button>
      <button type="button" :class="{ active: tab === 'scorecard' }" @click="tab = 'scorecard'">成绩单</button>
    </nav>

    <section v-show="tab === 'consistency'" class="consistency-panel">
      <div class="summary-grid">
        <article class="metric-card" :class="systemHealthy ? 'healthy' : 'degraded'">
          <span>系统运行态</span>
          <strong>{{ systemHealthy ? '健康' : '降级' }}</strong>
          <small>
            失败 {{ numberValue(runtimeSummary.actionable_failing) }} · 停摆 {{ numberValue(runtimeSummary.actionable_stale) }}
          </small>
        </article>
        <article class="metric-card" :class="numberValue(runtimeSummary.actionable_never_run) ? 'degraded' : 'healthy'">
          <span>定时履职</span>
          <strong>{{ numberValue(employeeDuty.observed_cron_count) }} / {{ numberValue(employeeDuty.registered_cron_count) }}</strong>
          <small>未运行 {{ numberValue(runtimeSummary.actionable_never_run) }} · 审批保留 {{ numberValue(employeeDuty.approval_required_count) }}</small>
        </article>
        <article class="metric-card" :class="coverage.workforce_ready ? 'healthy' : 'degraded'">
          <span>能力证明</span>
          <strong>{{ numberValue(coverage.proven_count) }} / {{ numberValue(coverage.planned_count) }}</strong>
          <small>门槛 {{ numberValue(coverage.proof_required_count) }} · {{ formatPercent(coverage.proof_ratio) }}</small>
        </article>
        <article class="metric-card" :class="coverage.production_workforce_ready ? 'healthy' : 'degraded'">
          <span>生产履职</span>
          <strong>{{ numberValue(coverage.production_proven_count) }} / {{ numberValue(coverage.planned_count) }}</strong>
          <small>{{ formatPercent(coverage.production_proof_ratio) }} · {{ platformLlmLabel }}</small>
        </article>
      </div>

      <div class="consistency-grid">
        <article class="card consistency-card">
          <h3>需处理运行项</h3>
          <div v-if="issueJobs.length" class="issue-list">
            <div v-for="job in issueJobs" :key="String(job.job_id)" class="issue-row">
              <span class="state-tag" :class="String(job.state || '')">{{ job.state || 'unknown' }}</span>
              <span>{{ job.job_id || '—' }}</span>
              <code>{{ job.last_error_code || '无安全错误码' }}</code>
            </div>
          </div>
          <div v-else class="empty compact">没有失败或停摆任务</div>
        </article>

        <article class="card consistency-card">
          <h3>未履职定时岗位</h3>
          <div v-if="neverRunEmployeeIds.length" class="employee-tags">
            <span v-for="employeeId in neverRunEmployeeIds" :key="employeeId">{{ employeeId }}</span>
          </div>
          <div v-else class="empty compact">所有已注册定时岗位均有运行回执</div>
        </article>

        <article class="card consistency-card">
          <h3>未完成能力证明</h3>
          <div v-if="unprovenEmployeeIds.length" class="employee-tags">
            <span v-for="employeeId in unprovenEmployeeIds" :key="employeeId">{{ employeeId }}</span>
          </div>
          <div v-else class="empty compact">全部员工均有有效能力回执</div>
        </article>

        <article class="card consistency-card">
          <h3>需人工审批岗位</h3>
          <div v-if="approvalRequiredEmployeeIds.length" class="employee-tags policy">
            <span v-for="employeeId in approvalRequiredEmployeeIds" :key="employeeId">{{ employeeId }}</span>
          </div>
          <div v-else class="empty compact">没有待审批的高风险岗位</div>
        </article>
      </div>
    </section>

    <section v-show="tab === 'suggestions'" class="card table-card">
      <table v-if="suggestions.length" class="data-table">
        <thead>
          <tr>
            <th></th>
            <th>员工</th>
            <th>建议</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in suggestions" :key="String(row.id)">
            <td>
              <input v-model="selectedIds" type="checkbox" :value="row.id" />
            </td>
            <td>{{ row.employee_id || row.employee || '—' }}</td>
            <td>{{ row.title || row.summary || row.suggestion || '—' }}</td>
            <td>{{ row.status || 'pending' }}</td>
            <td class="ops">
              <button type="button" class="link" @click="approveOne(row.id)">通过</button>
              <button type="button" class="link danger" @click="rejectOne(row.id)">拒绝</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">暂无建议</div>
    </section>

    <section v-show="tab === 'questions'" class="card">
      <div v-if="retortStats.open" class="retort-banner" :class="retortStats.critical ? 'critical' : ''">
        Retort 待澄清 {{ retortStats.open }} 条
        <template v-if="retortStats.critical"> · 其中 {{ retortStats.critical }} 条即将超时</template>
      </div>
      <div v-for="q in questions" :key="String(q.id)" class="qa-item" :class="urgencyClass(q)">
        <div class="qa-q">
          <span v-if="isRetortQuestion(q)" class="retort-tag">Retort 澄清</span>
          <span v-if="urgencyLabel(q)" class="urgency-tag" :class="urgencyClass(q)">{{ urgencyLabel(q) }}</span>
          {{ q.question || q.content || q.title }}
        </div>
        <div class="qa-meta">
          {{ q.employee_id || '—' }} · {{ q.asked_at || q.created_at || '' }}
          <template v-if="countdownText(q)"> · {{ countdownText(q) }}</template>
          <template v-else-if="q.expires_at"> · 截止 {{ q.expires_at }}</template>
        </div>
        <div v-if="structuredQuestions(q).length" class="qa-multi">
          <div v-for="sub in structuredQuestions(q)" :key="String(sub.id)" class="qa-sub">
            <label>{{ sub.question || sub.id }}</label>
            <input
              v-model="structuredAnswers[answerKey(q.id, sub.id)]"
              type="text"
              :placeholder="sub.blocking === false ? '可选补充' : '必答：确认意图/风险边界'"
            />
          </div>
          <div class="qa-answer">
            <input v-model="answers[String(q.id)]" type="text" placeholder="或统一答复（覆盖全部必答题）" />
            <button type="button" class="btn btn-primary" @click="answerOne(q)">提交</button>
          </div>
        </div>
        <div v-else class="qa-answer">
          <input v-model="answers[String(q.id)]" type="text" placeholder="输入答复（确认意图/风险边界）" />
          <button type="button" class="btn btn-primary" @click="answerOne(q)">提交</button>
        </div>
      </div>
      <div v-if="!questions.length" class="empty">暂无待答问题</div>
    </section>

    <section v-show="tab === 'scorecard'" class="card table-card">
      <table v-if="scorecard.length" class="data-table">
        <thead>
          <tr>
            <th>员工</th>
            <th>任务数</th>
            <th>成功率</th>
            <th>最近活跃</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, idx) in scorecard" :key="String(row.employee_id || idx)">
            <td>{{ row.employee_id || row.name || '—' }}</td>
            <td>{{ row.total_tasks ?? row.task_count ?? '—' }}</td>
            <td>{{ formatRate(row.success_rate) }}</td>
            <td>{{ row.last_run_at || row.last_active_at || row.updated_at || '—' }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">暂无成绩单数据</div>
    </section>
  </div>
</template>

<script lang="ts">
export default { name: 'EmployeeAutonomyView' }
</script>
<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { xcmaxEmployeeAutonomyApi } from '@/api/xcmaxEmployeeAutonomy'
import { appAlert, appPrompt } from '@/utils/appDialog'
const route = useRoute()
type Row = Record<string, any>
const tab = ref<'consistency' | 'suggestions' | 'questions' | 'scorecard'>('consistency')
const loading = ref(false)
const acting = ref(false)
const error = ref('')
const suggestions = ref<Row[]>([])
const questions = ref<Row[]>([])
const scorecard = ref<Row[]>([])
const runtime = ref<Row>({})
const coverage = ref<Row>({})
const selectedIds = ref<Array<string | number>>([])
const answers = reactive<Record<string, string>>({})
const structuredAnswers = reactive<Record<string, string>>({})
const nowMs = ref(Date.now())
const retortMeta = ref({ open: 0, critical: 0 })
let tickTimer: ReturnType<typeof setInterval> | undefined

const retortStats = computed(() => ({
  open: Number(retortMeta.value.open || 0),
  critical: Number(retortMeta.value.critical || 0),
}))
const runtimeSummary = computed<Row>(() => asRecord(runtime.value.summary))
const employeeDuty = computed<Row>(() => asRecord(runtime.value.employee_duty))
const employeeDutyDetails = computed<Row>(() => asRecord(runtime.value.employee_duty_details))
const systemHealthy = computed(() => runtime.value.ok === true && String(runtime.value.status || '') !== 'degraded')
const neverRunEmployeeIds = computed<string[]>(() => stringList(employeeDutyDetails.value.never_run_employee_ids))
const approvalRequiredEmployeeIds = computed<string[]>(() => stringList(employeeDutyDetails.value.approval_required_employee_ids))
const issueJobs = computed<Row[]>(() => {
  const policyHeld = new Set(approvalRequiredEmployeeIds.value.map((id) => `employee_cron:${id}`))
  return asList(runtime.value.jobs, ['items', 'rows']).filter(
    (row) => ['failing', 'stale'].includes(String(row.state || '')) && !policyHeld.has(String(row.job_id || '')),
  )
})
const unprovenEmployeeIds = computed<string[]>(() => stringList(coverage.value.unproven_employee_ids))
const platformLlmLabel = computed(() => {
  const llm = asRecord(coverage.value.platform_llm)
  const provider = String(llm.provider || '').trim()
  const model = String(llm.model || '').trim()
  return provider && model ? `${provider}/${model}` : '模型未配置'
})

function numberValue(value: unknown) {
  const number = Number(value)
  return Number.isFinite(number) ? number : 0
}

function formatPercent(value: unknown) {
  const number = Number(value)
  return Number.isFinite(number) ? `${(number * 100).toFixed(1)}%` : '0.0%'
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item || '').trim()).filter(Boolean) : []
}
function formatRate(value: unknown) {
  if (value == null || value === '') return '—'
  const n = Number(value)
  if (Number.isNaN(n)) return String(value)
  return n <= 1 ? `${(n * 100).toFixed(1)}%` : `${n.toFixed(1)}%`
}

function isRetortQuestion(q: Row) {
  const employee = String(q.employee_id || '')
  const kind = String((q.context && q.context.kind) || q.source || '')
  return employee === 'retort-clarification' || kind.includes('retort_clarification') || String(q.id || '').startsWith('retort:')
}

function structuredQuestions(q: Row): Row[] {
  return Array.isArray(q.questions) ? q.questions.filter((item) => item && typeof item === 'object') : []
}

function answerKey(questionId: string | number, subId: unknown) {
  return `${String(questionId)}::${String(subId || '')}`
}
function secondsRemaining(q: Row): number | null {
  if (typeof q.seconds_remaining === 'number') {
    const asked = q.asked_at || q.created_at
    if (!asked || !q.expires_at) return Math.max(0, q.seconds_remaining)
  }
  const expires = String(q.expires_at || '').trim()
  if (!expires) return typeof q.seconds_remaining === 'number' ? Math.max(0, q.seconds_remaining) : null
  const end = new Date(expires).getTime()
  if (Number.isNaN(end)) return typeof q.seconds_remaining === 'number' ? Math.max(0, q.seconds_remaining) : null
  return Math.max(0, Math.floor((end - nowMs.value) / 1000))
}

function urgencyOf(q: Row): string {
  const explicit = String(q.urgency || '')
  if (explicit && explicit !== 'none') return explicit
  const secs = secondsRemaining(q)
  if (secs == null) return ''
  if (secs <= 0) return 'expired'
  if (secs <= 300) return 'critical'
  if (secs <= 900) return 'soon'
  return 'normal'
}

function urgencyClass(q: Row) {
  const u = urgencyOf(q)
  return u ? `urgency-${u}` : ''
}

function urgencyLabel(q: Row) {
  const map: Record<string, string> = {
    critical: '即将超时',
    soon: '临近截止',
    expired: '已过期',
    normal: '待答',
  }
  return map[urgencyOf(q)] || ''
}

function countdownText(q: Row) {
  const secs = secondsRemaining(q)
  if (secs == null) return ''
  if (secs <= 0) return '已到期'
  const h = Math.floor(secs / 3600)
  const m = Math.floor((secs % 3600) / 60)
  const s = secs % 60
  if (h > 0) return `剩余 ${h}h ${m}m`
  if (m > 0) return `剩余 ${m}m ${s}s`
  return `剩余 ${s}s`
}

function asList(payload: unknown, keys: string[] = ['items', 'suggestions', 'questions', 'rows', 'data']): Row[] {
  if (Array.isArray(payload)) return payload
  if (!payload || typeof payload !== 'object') return []
  const obj = payload as Record<string, unknown>
  for (const key of keys) {
    const val = obj[key]
    if (Array.isArray(val)) return val as Row[]
    if (val && typeof val === 'object') {
      const nested = asList(val, ['items', 'rows'])
      if (nested.length) return nested
    }
  }
  return []
}

function asRecord(payload: unknown): Row {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return {}
  const row = payload as Row
  if (row.data && typeof row.data === 'object' && !Array.isArray(row.data)) {
    return row.data as Row
  }
  return row
}
async function refresh() {
  loading.value = true
  error.value = ''
  const failures: string[] = []
  try {
    const [runtimeResult, coverageResult, suggestionsResult, questionsResult, scorecardResult] = await Promise.allSettled([
      xcmaxEmployeeAutonomyApi.runtime(),
      xcmaxEmployeeAutonomyApi.executionCoverage({ window_hours: 24, production_window_hours: 720 }),
      xcmaxEmployeeAutonomyApi.listSuggestions({ limit: 50 }),
      xcmaxEmployeeAutonomyApi.listQuestions({ include_history: false }),
      xcmaxEmployeeAutonomyApi.scorecard({ days: 7, top_n: 50 }),
    ])

    if (runtimeResult.status === 'fulfilled') runtime.value = asRecord(runtimeResult.value)
    else failures.push(`运行态：${errorText(runtimeResult.reason)}`)

    if (coverageResult.status === 'fulfilled') coverage.value = asRecord(coverageResult.value)
    else failures.push(`履职覆盖：${errorText(coverageResult.reason)}`)

    if (suggestionsResult.status === 'fulfilled') suggestions.value = asList(suggestionsResult.value)
    else failures.push(`建议：${errorText(suggestionsResult.reason)}`)

    if (questionsResult.status === 'fulfilled') {
      const questionsPayload = asRecord(questionsResult.value)
      questions.value = asList(questionsPayload)
      retortMeta.value = {
        open: Number(questionsPayload.retort_open_count || 0),
        critical: Number(questionsPayload.retort_critical_count || 0),
      }
    } else {
      failures.push(`问答：${errorText(questionsResult.reason)}`)
    }

    if (scorecardResult.status === 'fulfilled') scorecard.value = asList(scorecardResult.value)
    else failures.push(`成绩单：${errorText(scorecardResult.reason)}`)

    error.value = failures.length ? `部分数据刷新失败：${failures.join('；')}` : ''
    nowMs.value = Date.now()
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}
async function approveOne(id: string | number) {
  acting.value = true
  try {
    await xcmaxEmployeeAutonomyApi.approveSuggestion(id)
    await refresh()
  } catch (e: unknown) {
    await appAlert(e instanceof Error ? e.message : String(e))
  } finally {
    acting.value = false
  }
}

async function rejectOne(id: string | number) {
  const reason = await appPrompt('拒绝原因（可选）', '')
  if (reason === null) return
  acting.value = true
  try {
    await xcmaxEmployeeAutonomyApi.rejectSuggestion(id, reason || undefined)
    await refresh()
  } catch (e: unknown) {
    await appAlert(e instanceof Error ? e.message : String(e))
  } finally {
    acting.value = false
  }
}

async function batchApprove() {
  if (!selectedIds.value.length) return
  acting.value = true
  try {
    await xcmaxEmployeeAutonomyApi.batchReview({
      ids: [...selectedIds.value],
      action: 'approve',
      dispatch_now: true,
    })
    selectedIds.value = []
    await refresh()
  } catch (e: unknown) {
    await appAlert(e instanceof Error ? e.message : String(e))
  } finally {
    acting.value = false
  }
}

async function answerOne(qOrId: Row | string | number) {
  const q = typeof qOrId === 'object' && qOrId ? qOrId : { id: qOrId }
  const id = q.id as string | number
  const freeform = String(answers[String(id)] || '').trim()
  const subs = structuredQuestions(q)
  const perQuestion: Record<string, string> = {}
  for (const sub of subs) {
    const sid = String(sub.id || '')
    if (!sid) continue
    const text = String(structuredAnswers[answerKey(id, sid)] || '').trim()
    if (text) perQuestion[sid] = text
  }
  const blockingIds = subs
    .filter((sub) => sub.blocking !== false)
    .map((sub) => String(sub.id || ''))
    .filter(Boolean)
  const missing = blockingIds.filter((sid) => !perQuestion[sid])
  if (!freeform && missing.length) {
    await appAlert(`请先回答全部必答题（还差 ${missing.length} 题），或填写统一答复`)
    return
  }
  if (!freeform && !Object.keys(perQuestion).length) {
    await appAlert('请输入答复')
    return
  }
  acting.value = true
  try {
    await xcmaxEmployeeAutonomyApi.answerQuestion(
      id,
      freeform,
      Object.keys(perQuestion).length ? perQuestion : undefined,
    )
    answers[String(id)] = ''
    for (const key of Object.keys(structuredAnswers)) {
      if (key.startsWith(`${String(id)}::`)) structuredAnswers[key] = ''
    }
    await refresh()
  } catch (e: unknown) {
    await appAlert(e instanceof Error ? e.message : String(e))
  } finally {
    acting.value = false
  }
}

function applyTabFromRoute() {
  const requested = String(route.query.tab || '')
  if (requested === 'consistency' || requested === 'questions' || requested === 'scorecard' || requested === 'suggestions') {
    tab.value = requested
  }
}

watch(
  () => route.query.tab,
  () => applyTabFromRoute(),
)

onMounted(() => {
  applyTabFromRoute()
  void refresh()
  tickTimer = setInterval(() => {
    nowMs.value = Date.now()
  }, 1000)
})

onUnmounted(() => {
  if (tickTimer) clearInterval(tickTimer)
})
</script>
<style scoped src="../styles/EmployeeAutonomyView.css"></style>
