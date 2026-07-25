<template>
  <div class="employee-autonomy-view" id="view-employee-autonomy">
    <div class="page-header">
      <div>
        <h2>员工自治</h2>
        <p>建议看板 · 问答 · 成绩单 · 批量审批</p>
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
      <button type="button" :class="{ active: tab === 'suggestions' }" @click="tab = 'suggestions'">建议看板</button>
      <button type="button" :class="{ active: tab === 'questions' }" @click="tab = 'questions'">问答</button>
      <button type="button" :class="{ active: tab === 'scorecard' }" @click="tab = 'scorecard'">成绩单</button>
    </nav>

    <section v-show="tab === 'suggestions'" class="card">
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

    <section v-show="tab === 'scorecard'" class="card">
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
            <td>{{ row.last_active_at || row.updated_at || '—' }}</td>
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

const tab = ref<'suggestions' | 'questions' | 'scorecard'>('suggestions')
const loading = ref(false)
const acting = ref(false)
const error = ref('')
const suggestions = ref<Row[]>([])
const questions = ref<Row[]>([])
const scorecard = ref<Row[]>([])
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

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const [sug, qs, sc] = await Promise.all([
      xcmaxEmployeeAutonomyApi.listSuggestions({ limit: 50 }),
      xcmaxEmployeeAutonomyApi.listQuestions({ include_history: false }),
      xcmaxEmployeeAutonomyApi.scorecard({ days: 7, top_n: 50 }),
    ])
    suggestions.value = asList(sug)
    questions.value = asList(qs)
    scorecard.value = asList(sc)
    const meta = (qs && typeof qs === 'object' ? qs : {}) as Record<string, unknown>
    retortMeta.value = {
      open: Number(meta.retort_open_count || 0),
      critical: Number(meta.retort_critical_count || 0),
    }
    nowMs.value = Date.now()
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
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
    await xcmaxEmployeeAutonomyApi.batchReview({ approve_ids: [...selectedIds.value] })
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
  if (requested === 'questions' || requested === 'scorecard' || requested === 'suggestions') {
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

<style scoped>
.employee-autonomy-view {
  padding: 24px 28px 40px;
  max-width: 1400px;
  margin: 0 auto;
  background: linear-gradient(135deg, #edf5fb 0%, #e7eef6 100%);
  min-height: 100%;
}
.page-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.page-header h2 { margin: 0 0 4px; font-size: 22px; color: #172033; }
.page-header p { margin: 0; color: #64748b; font-size: 13px; }
.header-actions, .ops { display: flex; gap: 8px; align-items: center; }
.btn {
  border: 1px solid #d0d7e2;
  background: #fff;
  border-radius: 8px;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 13px;
}
.btn-primary { background: #1890ff; border-color: #1890ff; color: #fff; }
.btn:disabled { opacity: 0.6; cursor: not-allowed; }
.banner-error {
  background: #fff1f0; color: #cf1322; border: 1px solid #ffa39e;
  border-radius: 8px; padding: 10px 12px; margin-bottom: 12px;
}
.tabs { display: flex; gap: 8px; margin-bottom: 12px; }
.tabs button {
  border: 1px solid #d0d7e2; background: #fff; border-radius: 999px;
  padding: 6px 14px; cursor: pointer;
}
.tabs button.active { background: #1890ff; border-color: #1890ff; color: #fff; }
.card {
  background: rgba(255,255,255,0.92);
  border: 1px solid rgba(15,76,129,0.1);
  border-radius: 16px;
  padding: 14px;
  box-shadow: 0 4px 18px rgba(15,76,129,0.07);
}
.data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.data-table th, .data-table td {
  text-align: left; padding: 8px 10px; border-bottom: 1px solid #eef2f7;
}
.empty { padding: 28px; text-align: center; color: #94a3b8; }
.link { border: none; background: none; color: #1890ff; cursor: pointer; }
.link.danger { color: #cf1322; }
.retort-banner {
  margin-bottom: 12px;
  padding: 10px 12px;
  border-radius: 10px;
  background: #fff7e6;
  border: 1px solid #ffd591;
  color: #ad6800;
  font-size: 13px;
  font-weight: 600;
}
.retort-banner.critical {
  background: #fff1f0;
  border-color: #ffa39e;
  color: #cf1322;
}
.qa-item { border: 1px solid #eef2f7; border-radius: 10px; padding: 12px; margin-bottom: 10px; }
.qa-item.urgency-critical { border-color: #ffa39e; background: #fffafa; }
.qa-item.urgency-soon { border-color: #ffd591; background: #fffdf8; }
.qa-item.urgency-expired { border-color: #d9d9d9; opacity: 0.85; }
.qa-q { font-weight: 600; color: #172033; }
.retort-tag,
.urgency-tag {
  display: inline-block;
  margin-right: 8px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
}
.retort-tag {
  background: #fff7e6;
  color: #d46b08;
  border: 1px solid #ffd591;
}
.urgency-tag.urgency-critical { background: #fff1f0; color: #cf1322; border: 1px solid #ffa39e; }
.urgency-tag.urgency-soon { background: #fff7e6; color: #d46b08; border: 1px solid #ffd591; }
.urgency-tag.urgency-expired { background: #f5f5f5; color: #8c8c8c; border: 1px solid #d9d9d9; }
.urgency-tag.urgency-normal { background: #e6f4ff; color: #0958d9; border: 1px solid #91caff; }
.qa-meta { color: #94a3b8; font-size: 12px; margin: 4px 0 8px; }
.qa-multi { display: grid; gap: 8px; }
.qa-sub { display: grid; gap: 4px; }
.qa-sub label { font-size: 12px; color: #475569; font-weight: 600; }
.qa-sub input,
.qa-answer input {
  width: 100%;
  border: 1px solid #d0d7e2;
  border-radius: 8px;
  padding: 8px 10px;
  box-sizing: border-box;
}
.qa-answer { display: flex; gap: 8px; margin-top: 4px; }
.qa-answer input { flex: 1; }
</style>
