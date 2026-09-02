import { computed, ref } from 'vue'
import { api } from '@/api'

/** 员工大会进度片段（服务器 ``planning_record.progress``，字段可能缺省）。 */
interface AllHandsProgressPayload {
  stage?: string
  total?: number
  completed?: number
  ok?: number
  error?: number
  percent?: number
  current_employee_id?: string
  current_employee_name?: string
  current_employee_status?: string
  updated_at?: string
}

/** 本地维护的完整进度状态。 */
type AllHandsProgress = Required<AllHandsProgressPayload>

interface AllHandsReportSummary {
  total?: number
  ok?: number
  error?: number
  bench_provider?: unknown
  bench_model?: unknown
}

/** 员工汇报行：模板消费 ``employee_id`` / ``status`` / ``report_markdown``，其余字段保持开放。 */
interface AllHandsEmployeeRow {
  [key: string]: unknown
  employee_id?: string
  status?: string
  name?: unknown
  report_markdown?: string
}

/** 员工大会报告（模板消费 summary / employees / synthesized_answer）。 */
interface AllHandsReport {
  [key: string]: unknown
  summary?: AllHandsReportSummary | null
  employees?: AllHandsEmployeeRow[]
  synthesized_answer?: { markdown?: string; question?: unknown } | null
}

interface AllHandsMeetingMinutes {
  [key: string]: unknown
  text?: string
}

/** 轮询会话接口响应（实际消费 planning_record.progress / status / error / artifact）。 */
interface AllHandsSessionResponse {
  status?: unknown
  error?: unknown
  planning_record?: { progress?: AllHandsProgressPayload | null } | null
  artifact?: {
    all_hands_report?: AllHandsReport | null
    meeting_minutes?: AllHandsMeetingMinutes | null
    meeting_minutes_email?: AllHandsMeetingMinutes | null
  } | null
}

interface AllHandsStartResponse {
  session_id?: unknown
}

type AllHandsArtifact = NonNullable<AllHandsSessionResponse['artifact']>

/** 服务器员工大会域逻辑（自 ServerFunctionsView.vue 拆出，行为零变更）。 */
export function useAllHands(formatJson: (value: unknown) => string) {
  const allHandsQuestion = ref('')
  const allHandsMaxEmployees = ref(20)
  const allHandsConcurrency = ref(2)
  const allHandsWithResearch = ref(true)
  const allHandsBusy = ref(false)
  const allHandsError = ref('')
  const allHandsSessionId = ref('')
  const allHandsReport = ref<AllHandsReport | null>(null)
  const allHandsMeetingMinutes = ref<AllHandsMeetingMinutes | null>(null)
  const allHandsMeetingMinutesEmail = ref<AllHandsMeetingMinutes | null>(null)
  const allHandsProgress = ref<AllHandsProgress>({
    stage: 'prepare',
    total: 0,
    completed: 0,
    ok: 0,
    error: 0,
    percent: 0,
    current_employee_id: '',
    current_employee_name: '',
    current_employee_status: '',
    updated_at: '',
  })

  let allHandsPollTimer = 0
  const allHandsStallHint = ref('')
  let allHandsStallSince = 0
  let allHandsStallSnapshot = ''

  const ALL_HANDS_STAGE_LABELS: Record<string, string> = {
    prepare: '准备员工清单',
    collect: '收集员工汇报',
    employee_done: '收集员工汇报',
    completed: '汇报汇总',
    synthesize: '数字管家综合答复',
    minutes: '生成会议摘要',
  }

  const allHandsStageLabel = computed(() => {
    const stage = String(allHandsProgress.value.stage || 'collect').toLowerCase()
    return ALL_HANDS_STAGE_LABELS[stage] || '员工大会进行中'
  })

  function resetAllHandsProgress(total: number) {
    allHandsProgress.value = {
      stage: 'prepare',
      total,
      completed: 0,
      ok: 0,
      error: 0,
      percent: 0,
      current_employee_id: '',
      current_employee_name: '',
      current_employee_status: '',
      updated_at: '',
    }
  }

  function touchAllHandsStallWatch() {
    const snap = [
      allHandsProgress.value.stage,
      allHandsProgress.value.completed,
      allHandsProgress.value.total,
      allHandsProgress.value.current_employee_id,
    ].join('|')
    if (snap !== allHandsStallSnapshot) {
      allHandsStallSnapshot = snap
      allHandsStallSince = Date.now()
      allHandsStallHint.value = ''
      return
    }
    if (!allHandsBusy.value) return
    const stalledMs = Date.now() - allHandsStallSince
    if (stalledMs < 120_000) return
    const stage = String(allHandsProgress.value.stage || '').toLowerCase()
    if (stage === 'minutes' || stage === 'synthesize') {
      allHandsStallHint.value = '会议摘要/综合答复生成较慢，请继续等待…'
      return
    }
    const name = allHandsProgress.value.current_employee_name || allHandsProgress.value.current_employee_id
    allHandsStallHint.value = name
      ? `「${name}」汇报超过 2 分钟无进展，可能 LLM 较慢；单员工默认 300s 超时后会自动跳过`
      : '进度超过 2 分钟无变化，请检查 MODstore :8788 日志或稍后重试'
  }

  function applyAllHandsProgress(raw: AllHandsProgressPayload | null | undefined) {
    if (!raw || typeof raw !== 'object') return
    const prev = allHandsProgress.value
    const total = Math.max(0, Number(raw.total ?? prev.total) || 0)
    const completed = Math.max(0, Math.min(Number(raw.completed ?? prev.completed) || 0, total || Number.MAX_SAFE_INTEGER))
    const percentRaw = Number(raw.percent)
    allHandsProgress.value = {
      stage: String(raw.stage ?? prev.stage ?? 'collect'),
      total,
      completed,
      ok: Math.max(0, Number(raw.ok ?? prev.ok) || 0),
      error: Math.max(0, Number(raw.error ?? prev.error) || 0),
      percent: Number.isFinite(percentRaw)
        ? Math.max(0, Math.min(100, Math.round(percentRaw)))
        : total > 0 ? Math.round((completed / total) * 100) : 0,
      current_employee_id: String(raw.current_employee_id ?? prev.current_employee_id ?? ''),
      current_employee_name: String(raw.current_employee_name ?? prev.current_employee_name ?? ''),
      current_employee_status: String(raw.current_employee_status ?? prev.current_employee_status ?? ''),
      updated_at: String(raw.updated_at ?? prev.updated_at ?? ''),
    }
    touchAllHandsStallWatch()
  }

  function stopAllHandsPolling() {
    if (allHandsPollTimer) {
      window.clearTimeout(allHandsPollTimer)
      allHandsPollTimer = 0
    }
  }

  async function pollAllHandsSession(sessionId: string) {
    stopAllHandsPolling()
    try {
      const sess = await api.get<AllHandsSessionResponse>(`/api/xcmax/admin/all-hands-report/sessions/${sessionId}`)
      applyAllHandsProgress(sess?.planning_record?.progress)
      if (sess?.status === 'done') {
        allHandsBusy.value = false
        const artifact: AllHandsArtifact = sess.artifact && typeof sess.artifact === 'object' ? sess.artifact : {}
        const report = artifact.all_hands_report
        if (!report || typeof report !== 'object') {
          allHandsError.value = '员工大会完成，但服务器没有返回有效报告内容'
          return
        }
        allHandsReport.value = report
        allHandsMeetingMinutes.value = artifact.meeting_minutes && typeof artifact.meeting_minutes === 'object'
          ? artifact.meeting_minutes
          : null
        allHandsMeetingMinutesEmail.value = artifact.meeting_minutes_email && typeof artifact.meeting_minutes_email === 'object'
          ? artifact.meeting_minutes_email
          : null
        applyAllHandsProgress({
          stage: 'completed',
          total: Number(report.summary?.total ?? report.employees?.length ?? 0) || 0,
          completed: Number(report.summary?.total ?? report.employees?.length ?? 0) || 0,
          ok: Number(report.summary?.ok ?? 0) || 0,
          error: Number(report.summary?.error ?? 0) || 0,
          percent: 100,
        })
        return
      }
      if (sess?.status === 'error') {
        allHandsBusy.value = false
        allHandsError.value = String(sess.error || '员工大会失败')
        return
      }
    } catch (e) {
      allHandsBusy.value = false
      allHandsError.value = e instanceof Error ? e.message : String(e)
      return
    }
    if (!allHandsBusy.value || allHandsSessionId.value !== sessionId) return
    allHandsPollTimer = window.setTimeout(() => {
      void pollAllHandsSession(sessionId)
    }, 2000)
  }

  async function startAllHands(withQuestion: boolean) {
    if (allHandsBusy.value) return
    stopAllHandsPolling()
    allHandsBusy.value = true
    allHandsError.value = ''
    allHandsSessionId.value = ''
    allHandsReport.value = null
    allHandsMeetingMinutes.value = null
    allHandsMeetingMinutesEmail.value = null
    allHandsStallHint.value = ''
    allHandsStallSince = Date.now()
    allHandsStallSnapshot = ''
    const maxEmployees = Math.max(1, Math.min(Number(allHandsMaxEmployees.value) || 20, 20))
    resetAllHandsProgress(maxEmployees)
    try {
      const question = allHandsQuestion.value.trim()
      const payload: Record<string, unknown> = {
        max_employees: maxEmployees,
        concurrency: Math.max(1, Math.min(Number(allHandsConcurrency.value) || 2, 4)),
        with_research: withQuestion && question ? false : allHandsWithResearch.value,
      }
      if (withQuestion && question) {
        payload.user_question = question
        payload.synthesize = true
      }
      const started = await api.post<AllHandsStartResponse>('/api/xcmax/admin/all-hands-report/sessions', payload)
      const sid = String(started?.session_id || '').trim()
      if (!sid) throw new Error('服务器没有返回员工大会 session_id')
      allHandsSessionId.value = sid
      void pollAllHandsSession(sid)
    } catch (e) {
      allHandsBusy.value = false
      allHandsError.value = e instanceof Error ? e.message : String(e)
    }
  }

  function downloadAllHandsJson() {
    const data = {
      report: allHandsReport.value,
      meeting_minutes: allHandsMeetingMinutes.value,
      meeting_minutes_email: allHandsMeetingMinutesEmail.value,
    }
    const blob = new Blob([formatJson(data)], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `server-all-hands-${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  return {
    allHandsQuestion,
    allHandsMaxEmployees,
    allHandsConcurrency,
    allHandsWithResearch,
    allHandsBusy,
    allHandsError,
    allHandsSessionId,
    allHandsReport,
    allHandsMeetingMinutes,
    allHandsMeetingMinutesEmail,
    allHandsProgress,
    allHandsStallHint,
    allHandsStageLabel,
    startAllHands,
    downloadAllHandsJson,
    stopAllHandsPolling,
  }
}
