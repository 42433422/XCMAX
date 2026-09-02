/**
 * 员工大会（All-Hands）：会期编排、轮询、汇报与会议纪要。
 *
 * 由 AdminDutyEmployeeGraph.vue 原文机械迁出。
 */
import { api } from '../../../api'
import { publishButlerTask } from '../../../utils/agent/butlerTaskBus'
import { isDeployedDutyRosterRow, isVirtualEmployee } from './adminDutyConstants'
import type { AdminDutyState } from './useAdminDutyState'
import type { AdminDutyPanels } from './useAdminDutyPanels'
import type {
  AllHandsEmployeeRow, AllHandsReport, AllHandsProgress, MeetingMinutesBlock,
  MeetingMinutesEmailMeta, AllHandsSessionSnapshot,
} from './adminDutyTypes'

export function useAdminDutyAllHands(s: AdminDutyState, panels: AdminDutyPanels, ctx: { focusEmployee: (id: string) => void }) {
  const { focusEmployee } = ctx
  const { togglePanel } = panels
  const {
    employees, error, showAllHandsPanel, allHandsBusy, allHandsError, allHandsReport,
    allHandsWithResearch, allHandsExpanded, allHandsPlainOpen, allHandsPlainText,
    allHandsPlainLoading, allHandsPlainReqGen, allHandsMeetingMinutes,
    allHandsMeetingMinutesEmail, allHandsSessionId, allHandsQuestion, allHandsProgress,
  } = s
  let allHandsPollTimer = 0

function stripEmbeddedReasoningTrace(s: string): string {
  const tagPairs: Array<{ o: string; c: string }> = [
    { o: 'think', c: 'think' },
    { o: 'thinking', c: 'thinking' },
    { o: 'redacted' + '_' + 'thinking', c: 'redacted' + '_' + 'thinking' },
  ]
  let out = s
  for (let p = 0; p < 12; p++) {
    let next = out
    for (const { o, c } of tagPairs) {
      const re = new RegExp('<' + o + '\\b[^>]*>[\\s\\S]*?</' + c + '>', 'gi')
      next = next.replace(re, '')
    }
    next = next.replace(/\n{3,}/g, '\n\n').trim()
    if (next === out) break
    out = next
  }
  return out
}

async function _openAllHandsPanel() {
  togglePanel('allhands')
  if (!showAllHandsPanel.value) return
  if (allHandsReport.value || allHandsBusy.value) return
  await runAllHands()
}


function applyAllHandsReport(report: AllHandsReport) {
  allHandsReport.value = report
  if (!report.ok) {
    allHandsError.value = report.error || '全员汇报失败'
    return
  }
  const next: Record<string, boolean> = {}
  for (const row of report.employees) next[row.employee_id] = true
  allHandsExpanded.value = next
}


function parseAllHandsReportFromArtifact(artifact: Record<string, unknown> | null | undefined): AllHandsReport | null {
  if (!artifact || typeof artifact !== 'object') return null
  const raw = (artifact as Record<string, unknown>).all_hands_report
  if (!raw || typeof raw !== 'object') return null
  const report = raw as Partial<AllHandsReport>
  if (!Array.isArray(report.employees)) return null
  return report as AllHandsReport
}


function resetAllHandsProgress(total = 0) {
  const t = Math.max(0, Number(total) || 0)
  allHandsProgress.value = {
    stage: 'prepare',
    total: t,
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


function applyAllHandsProgress(raw: Partial<AllHandsProgress> | null | undefined) {
  if (!raw || typeof raw !== 'object') return
  const prev = allHandsProgress.value
  const total = Math.max(0, Number(raw.total ?? prev.total) || 0)
  const completedRaw = Math.max(0, Number(raw.completed ?? prev.completed) || 0)
  const completed = total > 0 ? Math.min(completedRaw, total) : completedRaw
  const ok = Math.max(0, Number(raw.ok ?? prev.ok) || 0)
  const error = Math.max(0, Number(raw.error ?? prev.error) || 0)
  const percentRaw = Number(raw.percent)
  const percent = Number.isFinite(percentRaw)
    ? Math.max(0, Math.min(100, Math.round(percentRaw)))
    : (total > 0 ? Math.round((completed / total) * 100) : 0)
  allHandsProgress.value = {
    stage: String(raw.stage ?? prev.stage ?? 'collect'),
    total,
    completed,
    ok,
    error,
    percent,
    current_employee_id: String(raw.current_employee_id ?? prev.current_employee_id ?? ''),
    current_employee_name: String(raw.current_employee_name ?? prev.current_employee_name ?? ''),
    current_employee_status: String(raw.current_employee_status ?? prev.current_employee_status ?? ''),
    updated_at: String(raw.updated_at ?? prev.updated_at ?? ''),
  }
}


async function copyAllHandsMeetingMinutes() {
  const t = (allHandsMeetingMinutes.value?.text || '').trim()
  if (!t) return
  try {
    await navigator.clipboard.writeText(t)
  } catch {
    /* ignore */
  }
}


function downloadAllHandsMeetingMinutes() {
  const t = (allHandsMeetingMinutes.value?.text || '').trim()
  if (!t) return
  const blob = new Blob([t], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `员工大会会议摘要-${new Date().toISOString().slice(0, 10)}.txt`
  a.click()
  URL.revokeObjectURL(url)
}


function stopAllHandsPolling() {
  if (allHandsPollTimer) {
    clearTimeout(allHandsPollTimer)
    allHandsPollTimer = 0
  }
}


async function pollAllHandsSession(sessionId: string) {
  stopAllHandsPolling()
  try {
    const sess = (await api.workbenchGetSession(sessionId)) as AllHandsSessionSnapshot
    applyAllHandsProgress(sess?.planning_record?.progress ?? null)
    if (sess.status === 'done') {
      allHandsBusy.value = false
      const report = parseAllHandsReportFromArtifact(sess.artifact ?? null)
      if (!report) {
        allHandsError.value = '全员汇报完成，但未返回有效报告内容'
        allHandsMeetingMinutes.value = null
        allHandsMeetingMinutesEmail.value = null
        return
      }
      applyAllHandsProgress({
        stage: 'completed',
        total: Number(report.summary?.total ?? report.employees?.length ?? 0) || 0,
        completed: Number(report.summary?.total ?? report.employees?.length ?? 0) || 0,
        ok: Number(report.summary?.ok ?? 0) || 0,
        error: Number(report.summary?.error ?? 0) || 0,
        percent: 100,
      })
      applyAllHandsReport(report)
      const art = sess.artifact
      if (art && typeof art === 'object') {
        const mmRaw = (art as Record<string, unknown>).meeting_minutes
        allHandsMeetingMinutes.value =
          mmRaw && typeof mmRaw === 'object' ? (mmRaw as MeetingMinutesBlock) : null
        const emRaw = (art as Record<string, unknown>).meeting_minutes_email
        allHandsMeetingMinutesEmail.value =
          emRaw && typeof emRaw === 'object' ? (emRaw as MeetingMinutesEmailMeta) : null
      } else {
        allHandsMeetingMinutes.value = null
        allHandsMeetingMinutesEmail.value = null
      }
      return
    }
    if (sess.status === 'error') {
      allHandsBusy.value = false
      allHandsError.value = String(sess.error || '全员汇报失败')
      return
    }
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    if (/会话不存在|404/.test(msg)) {
      allHandsBusy.value = false
      allHandsError.value = `全员汇报会话已失效：${msg}`
      return
    }
  }
  if (!allHandsBusy.value || allHandsSessionId.value !== sessionId) return
  allHandsPollTimer = window.setTimeout(() => {
    void pollAllHandsSession(sessionId)
  }, 2000)
}


async function runAllHands(opts: { withQuestion?: boolean } = {}) {
  if (allHandsBusy.value) return
  stopAllHandsPolling()
  allHandsBusy.value = true
  allHandsError.value = ''
  allHandsSessionId.value = ''
  allHandsReport.value = null
  allHandsPlainOpen.value = {}
  allHandsPlainText.value = {}
  allHandsPlainLoading.value = {}
  allHandsPlainReqGen.value = {}
  allHandsMeetingMinutes.value = null
  allHandsMeetingMinutesEmail.value = null
  try {
    const realIds = employees.value.filter(isDeployedDutyRosterRow).map((e) => e.id)
    const cap = Math.max(1, realIds.length || 8)
    resetAllHandsProgress(cap)
    const useQuestion = opts.withQuestion === true && allHandsQuestion.value.trim().length > 0
    const payload: Record<string, unknown> = {
      employee_ids: realIds,
      with_research: useQuestion ? false : allHandsWithResearch.value,
      max_employees: cap,
      concurrency: 2,
    }
    if (useQuestion) {
      payload.user_question = allHandsQuestion.value.trim()
      payload.synthesize = true
    }
    const started = (await api.butlerAllHandsReportStartSession(payload as never)) as { session_id?: string; status?: string }
    const sid = String(started?.session_id || '').trim()
    if (!sid) throw new Error('启动全员汇报失败：后端未返回 session_id')
    allHandsSessionId.value = sid
    void pollAllHandsSession(sid)
  } catch (e: unknown) {
    allHandsBusy.value = false
    allHandsError.value = e instanceof Error ? e.message : String(e)
  }
}


async function askAllHandsQuestion() {
  if (!allHandsQuestion.value.trim()) {
    allHandsError.value = '请先输入要向员工大会提的问题'
    return
  }
  await runAllHands({ withQuestion: true })
}


function toggleAllHandsRow(id: string) {
  allHandsExpanded.value = {
    ...allHandsExpanded.value,
    [id]: !allHandsExpanded.value[id],
  }
}


async function requestPlainLang(row: AllHandsEmployeeRow) {
  const id = row.employee_id
  // toggle off if already open and loaded
  if (allHandsPlainOpen.value[id]) {
    allHandsPlainOpen.value = { ...allHandsPlainOpen.value, [id]: false }
    allHandsPlainReqGen.value = { ...allHandsPlainReqGen.value, [id]: (allHandsPlainReqGen.value[id] ?? 0) + 1 }
    return
  }
  allHandsPlainOpen.value = { ...allHandsPlainOpen.value, [id]: true }
  const cachedRaw = allHandsPlainText.value[id]
  const cached = stripEmbeddedReasoningTrace(typeof cachedRaw === 'string' ? cachedRaw : '')
  if (cached.length > 0) {
    if (cached !== cachedRaw) {
      allHandsPlainText.value = { ...allHandsPlainText.value, [id]: cached }
    }
    return
  }
  const gen = (allHandsPlainReqGen.value[id] ?? 0) + 1
  allHandsPlainReqGen.value = { ...allHandsPlainReqGen.value, [id]: gen }
  allHandsPlainLoading.value = { ...allHandsPlainLoading.value, [id]: true }
  try {
    const defaultLlm = (await api.llmResolveChatDefault()) as { provider: string; model: string } | null
    const provider = defaultLlm?.provider ?? 'openai'
    const model = defaultLlm?.model ?? 'gpt-4o-mini'

    const reportSnippet = row.report_markdown ? row.report_markdown.slice(0, 500) : '（无）'
    const userContent = [
      `员工名称：${row.name}（${row.employee_id}）`,
      `汇报状态：${row.status}`,
      `认知错误：${row.cognition_error || '无'}`,
      `警告条数：${row.warnings.length}，内容：${row.warnings.join('；') || '无'}`,
      `近期失败条数：${row.recent_failures.length}`,
      `调研来源条数：${row.research_sources.length}`,
      `汇报摘要（前500字）：${reportSnippet}`,
    ].join('\n')

    const messages = [
      {
        role: 'system',
        content:
          '你是一个说大白话的助手，帮老板（称呼对方为"爸爸"）看懂 AI 员工全员汇报的状态。' +
          '用口语化中文解释：这个员工的汇报有什么问题、缺哪些素材、为什么写不出来，或者一切正常是什么意思。' +
          '不要用技术术语，不要绕弯，直接说人话；禁止输出思维链、推理步骤、<think> 等标记或括号内的内心独白。' +
          '开头和结尾都要叫"爸爸"。回复控制在200字以内。',
      },
      { role: 'user', content: userContent },
    ]

    const res = (await api.llmChat(provider, model, messages, 1024)) as {
      content?: string
      choices?: { message?: { content?: string } }[]
    }
    if (allHandsPlainReqGen.value[id] !== gen) return
    const raw =
      String(res?.content ?? res?.choices?.[0]?.message?.content ?? '').trim() ||
      '爸爸，AI 没返回内容，可能是模型暂时不可用，稍后再试一下。'
    let text = stripEmbeddedReasoningTrace(raw)
    if (!text) {
      text =
        '爸爸，模型只返回了推理过程没有正文，可以把默认模型换成非推理款或稍后再试。'
    }
    allHandsPlainText.value = { ...allHandsPlainText.value, [id]: text }
  } catch (e) {
    if (allHandsPlainReqGen.value[id] !== gen) return
    allHandsPlainText.value = {
      ...allHandsPlainText.value,
      [id]: `爸爸，调用 AI 翻译时出错了：${e instanceof Error ? e.message : String(e)}`,
    }
  } finally {
    if (allHandsPlainReqGen.value[id] === gen) {
      allHandsPlainLoading.value = { ...allHandsPlainLoading.value, [id]: false }
    }
  }
}


function focusAllHandsEmployee(id: string) {
  focusEmployee(id)
}


function publishFollowUpToButler(row: AllHandsEmployeeRow) {
  // 把单个员工的汇报作为 brief 推到数字管家事件总线，让管家做后续动作
  publishButlerTask({
    source: 'admin-duty-graph:all-hands',
    employeeId: row.employee_id,
    employeeName: row.name,
    brief:
      `请基于以下「员工大会」汇报，识别需要立即跟进的事项并给出执行计划：\n\n` +
      (row.report_markdown || '（无 Markdown 报告）'),
    inputData: {
      manifest_signals: row.manifest_signals,
      recent_failures: row.recent_failures,
      research_sources: row.research_sources,
    },
    includeDependencies: true,
    allowHighRisk: false,
    maxConcurrency: 2,
  })
}


  return {
    _openAllHandsPanel, applyAllHandsReport, parseAllHandsReportFromArtifact,
    resetAllHandsProgress, applyAllHandsProgress, copyAllHandsMeetingMinutes,
    downloadAllHandsMeetingMinutes, stopAllHandsPolling, pollAllHandsSession,
    runAllHands, askAllHandsQuestion, toggleAllHandsRow, requestPlainLang,
    focusAllHandsEmployee, publishFollowUpToButler,
  }
}

export type AdminDutyAllHands = ReturnType<typeof useAdminDutyAllHands>
