import { computed } from 'vue'
import type { OrchStepLike, StructuredStepMessage } from '../../utils/orchestrationSteps'
import { requestMicInUserGesture } from '../../composables/asr/micPreflight'
import { unlockVoiceAudioPlayback } from '../../composables/voiceDevice'
import { stripInternalMarkers } from '../../utils/lightMarkdown'
import { showAppToast } from '../../composables/useAppToast'
import type { useWbLoadWorkbenchRepoPicks } from './useWbLoadWorkbenchRepoPicks'
import type { CachedWorkbenchFile, PendingHandoff, PlanMessage, PlanQuestion, PlanSession, WorkbenchStateRecord } from './types'

// 拆分自 WorkbenchHomeView.vue（原行 7600–7624, 8097–8103, 8106–8106 …）；逐字迁移，行为不变。
export function useWbRestoreMakeProgressCache(ctx: ReturnType<typeof useWbLoadWorkbenchRepoPicks>) {
  const {
    wbSidebar, wbNav, draft, pendingHandoff, finalizeLoading, finalizeError,
    orchestrationSession, orchestrationSessionId, orchPhase, orchestrationEtaSeconds, orchestrationEtaReason, __wbState,
    orchTimingStartMs, orchElapsedTick, workflowLinkOffer, planSession, planReplyDraft, planOptionSelections,
    planOptionOtherText, clearPlanOptionOtherText, MAKE_PROGRESS_CACHE_KEY, MAKE_PROGRESS_CACHE_TTL_MS, CANVAS_SKILL_INTENT, composerIntent,
    modFrontendEnabled, activeGear, directDraft, directError, directVoiceListening, directVoiceAudioLevel,
    makeVoiceListening, directVoiceRecognizing, makeVoiceRecognizing, directVoicePermissionHint, makeVoicePermissionHint, personalSettingsOpen,
    voiceMessages, voiceChatPhase, voiceWorkPhase, voiceInjectQueue, inlineAsr, setActiveConversation,
    syncVoiceWorkPhase, INTENT_META, formatWallClockSec, makeComposerInput,
  } = ctx

/** 制作草稿执行中：紧邻按钮的可读状态，避免只看到「执行中…」误以为卡住 */
const _handoffRunStatusLine = computed(() => {
  if (!finalizeLoading.value) return ''
  const s = orchestrationSession.value
  const steps = Array.isArray(s?.steps) ? s.steps : []
  const running = steps.find((x) => x.status === 'running')
  if (running) {
    const lab = String(running.label || '编排').trim() || '编排'
    const msg = typeof running.message === 'string' && running.message.trim() ? ` — ${running.message.trim()}` : ''
    const sec = orchStepRunningSec(running)
    const elapsed = sec !== null && sec >= 5 ? `（已运行 ${formatWallClockSec(sec)}）` : ''
    return `进行中：${lab}${msg}${elapsed}`
  }
  if (steps.length) {
    const done = steps.filter((x) => x.status === 'done').length
    const next = steps.find((x) => x.status === 'pending')
    if (next && done < steps.length) {
      const nl = String(next.label || '下一步').trim() || '下一步'
      return `排队中：${nl}（已完成 ${done}/${steps.length}）`
    }
    return `编排进度：${done}/${steps.length} 步`
  }
  const st = typeof s?.status === 'string' ? s.status.trim() : ''
  if (st && st !== 'done' && st !== 'error') return `编排状态：${st}`
  return '已提交，正在连接编排服务并拉取步骤…'
})
/** 返回某步骤已运行的秒数（仅 running 状态 + 有 started_at 时），null 表示不展示。
 *  orchElapsedTick 作为响应式依赖使其每 0.5 秒刷新一次。*/
function orchStepRunningSec(st: OrchStepLike): number | null {
  orchElapsedTick.value // 依赖订阅，使每次 tick 重新计算
  if (st.status !== 'running' || !st.started_at) return null
  const t0 = new Date(st.started_at).getTime()
  if (!Number.isFinite(t0)) return null
  return Math.max(0, Math.floor((Date.now() - t0) / 1000))
}
/** 跟踪各步骤最近一次 message 变化时间，用于「响应较慢」提示（B3）。*/
const _stepLastMsgChange: Record<string, { msg: string; ts: number }> = {}
function orchStepSlowHint(st: OrchStepLike): boolean {
  orchElapsedTick.value // 响应式订阅
  if (st.status !== 'running') return false
  const sec = orchStepRunningSec(st)
  if (sec === null || sec < 60) return false
  const tracked = _stepLastMsgChange[String(st.id || st.label || 'unknown')]
  if (!tracked) return true // 从未记录过，说明消息一直没来
  return (Date.now() - tracked.ts) >= 30000
}
/** 每次轮询后调用，更新 message 变化时间戳。 */
function _trackStepMessages(steps: OrchStepLike[]) {
  for (const st of steps || []) {
    const message = st.message as Record<string, unknown> | string | null | undefined
    const cur = typeof message === 'object' && message
      ? String(message.summary || JSON.stringify(message))
      : String(st.message || '')
    const stepId = String(st.id || st.label || 'unknown')
    const prev = _stepLastMsgChange[stepId]
    if (!prev || prev.msg !== cur) {
      _stepLastMsgChange[stepId] = { msg: cur, ts: Date.now() }
    }
  }
}
// ---------------------------------------------------------------- AgentLoop v2 message helpers
/** Returns the display summary string from a step's message (str or dict). */
function structuredStepMessage(st: OrchStepLike): StructuredStepMessage | null {
  const msg = st?.message
  if (!msg || typeof msg !== 'object') return null
  return msg as StructuredStepMessage
}
function stepMsgSummary(st: OrchStepLike): string {
  const msg = st?.message
  if (!msg) return ''
  if (typeof msg === 'string') return msg
  const structured = structuredStepMessage(st)
  if (structured) return String(structured.summary || '')
  return ''
}
/** Returns the current tool name from a structured message, or empty string. */
function stepMsgCurrentTool(st: OrchStepLike): string {
  return String(structuredStepMessage(st)?.current_tool || '')
}
/** Returns the todo list from a structured message, or empty array. */
function stepMsgTodos(st: OrchStepLike): Array<{ id: string; content: string; status: string }> {
  const todos = structuredStepMessage(st)?.todos
  if (!Array.isArray(todos)) return []
  return todos.filter((todo) => Boolean(todo && typeof todo === 'object'))
}
/** Returns true if the structured message indicates a slow-model hint. */
function stepMsgSlowHint(st: OrchStepLike): boolean {
  return Boolean(structuredStepMessage(st)?.slow_hint)
}
function cachedFileMetadata(file: File): CachedWorkbenchFile {
  return {
    name: file.name,
    size: file.size,
    type: file.type,
    cachedOnly: true,
  }
}
function normalizePlanMessages(value: unknown): PlanMessage[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item): PlanMessage[] => {
    if (!item || typeof item !== 'object') return []
    const row = item as Record<string, unknown>
    if (row.role !== 'user' && row.role !== 'assistant') return []
    return [{ role: row.role, content: String(row.content || '') }]
  })
}
function serializablePlanSession(ps: PlanSession | null): Record<string, unknown> | null {
  if (!ps) return null
  return {
    ...ps,
    files: ps.files.map(cachedFileMetadata),
  }
}
function restorePlanSession(value: unknown): PlanSession | null {
  if (!value || typeof value !== 'object') return null
  const ps = value as Record<string, unknown>
  const out: PlanSession = {
    intentKey: String(ps.intentKey || CANVAS_SKILL_INTENT),
    intentTitle: String(ps.intentTitle || '需求规划'),
    phase: String(ps.phase || 'summary'),
    initialBrief: String(ps.initialBrief || ''),
    fullBrief: String(ps.fullBrief || ''),
    displayBrief: String(ps.displayBrief || ''),
    generateFrontend: Boolean(ps.generateFrontend),
    summaryTitle: String(ps.summaryTitle || ''),
    summaryText: String(ps.summaryText || ''),
    summaryNeedsClarification: Boolean(ps.summaryNeedsClarification),
    // File 对象不能跨 sessionStorage 恢复；避免把元数据对象误传到上传接口。
    files: [],
    messages: normalizePlanMessages(ps.messages),
    checklistText: String(ps.checklistText || ''),
    checklistLines: Array.isArray(ps.checklistLines) ? ps.checklistLines.map((line) => String(line)) : [],
    planError: String(ps.planError || ''),
    loading: Boolean(ps.loading),
    streamingText: '',
  }
  if (out.loading) {
    out.loading = false
    out.planError =
      out.planError ||
      '页面切换前的规划请求已中断；已恢复当前进度，你可以继续补充或重新触发本步骤。'
  }
  return out
}
function serializablePendingHandoff(h: PendingHandoff | null): Record<string, unknown> | null {
  if (!h) return null
  return {
    ...h,
    files: (h.files || []).map(cachedFileMetadata),
    planningMessages: h.planningMessages.map((m) => ({ role: m.role, content: m.content })),
    executionChecklist: [...(h.executionChecklist || [])],
    sourceDocuments: [...(h.sourceDocuments || [])],
  }
}
function restorePendingHandoff(value: unknown): PendingHandoff | null {
  if (!value || typeof value !== 'object') return null
  const h = value as Record<string, unknown>
  return {
    description: String(h.description || ''),
    employeeRoutingBrief: typeof h.employeeRoutingBrief === 'string' ? h.employeeRoutingBrief : undefined,
    planningContext: typeof h.planningContext === 'string' ? h.planningContext : undefined,
    intentTitle: String(h.intentTitle || '制作草稿'),
    intentKey: String(h.intentKey || CANVAS_SKILL_INTENT),
    workflowName: String(h.workflowName || ''),
    planNotes: String(h.planNotes || ''),
    suggestedModId: String(h.suggestedModId || ''),
    generateFrontend: Boolean(h.generateFrontend),
    employeeTarget: String(h.employeeTarget || 'pack_only'),
    employeeWorkflowName: String(h.employeeWorkflowName || ''),
    fhdBaseUrl: String(h.fhdBaseUrl || ''),
    planningMessages: normalizePlanMessages(h.planningMessages),
    executionChecklist: Array.isArray(h.executionChecklist)
      ? h.executionChecklist.map((line) => String(line))
      : [],
    sourceDocuments: Array.isArray(h.sourceDocuments)
      ? h.sourceDocuments.filter((doc): doc is WorkbenchStateRecord => Boolean(doc && typeof doc === 'object'))
      : [],
    // 浏览器 File 无法从 JSON 恢复，必须由用户重新选择。
    files: [],
  }
}
function makeHasCachedProgress() {
  return Boolean(
    planSession.value ||
      pendingHandoff.value ||
      workflowLinkOffer.value ||
      finalizeLoading.value ||
      finalizeError.value ||
      orchestrationSession.value?.steps?.length ||
      orchestrationSessionId.value ||
      voiceMessages.value.length,
  )
}
function cacheMakeProgress() {
  try {
    if (!makeHasCachedProgress()) {
      sessionStorage.removeItem(MAKE_PROGRESS_CACHE_KEY)
      return
    }
    sessionStorage.setItem(
      MAKE_PROGRESS_CACHE_KEY,
      JSON.stringify({
        savedAt: Date.now(),
        activeGear: activeGear.value,
        draft: draft.value,
        composerIntent: composerIntent.value,
        modFrontendEnabled: modFrontendEnabled.value,
        planSession: serializablePlanSession(planSession.value),
        planReplyDraft: planReplyDraft.value,
        planOptionSelections: planOptionSelections.value,
        planOptionOtherText: { ...planOptionOtherText },
        pendingHandoff: serializablePendingHandoff(pendingHandoff.value),
        finalizeLoading: finalizeLoading.value,
        finalizeError: finalizeError.value,
        orchestrationSession: orchestrationSession.value,
        orchestrationSessionId: orchestrationSessionId.value,
        orchPhase: orchPhase.value,
        orchestrationEtaSeconds: orchestrationEtaSeconds.value,
        orchestrationEtaReason: orchestrationEtaReason.value,
        orchTimingStartMs: orchTimingStartMs.value,
        workflowLinkOffer: workflowLinkOffer.value,
        voiceMessages: voiceMessages.value,
        voiceChatPhase: voiceChatPhase.value,
        voiceWorkPhase: voiceWorkPhase.value,
        voiceInjectQueue: voiceInjectQueue.value,
      }),
    )
  } catch {
    /* ignore */
  }
}
function clearMakeProgressCache() {
  try {
    sessionStorage.removeItem(MAKE_PROGRESS_CACHE_KEY)
  } catch {
    /* ignore */
  }
}
function restoreMakeProgressCache() {
  try {
    const raw = sessionStorage.getItem(MAKE_PROGRESS_CACHE_KEY)
    if (!raw) return
    const cached = JSON.parse(raw)
    if (!cached || Date.now() - Number(cached.savedAt || 0) > MAKE_PROGRESS_CACHE_TTL_MS) {
      clearMakeProgressCache()
      return
    }
    if (cached.activeGear && ['direct', 'make', 'voice'].includes(cached.activeGear)) {
      activeGear.value = cached.activeGear
    }
    if (typeof cached.draft === 'string' && !draft.value.trim()) draft.value = cached.draft
    if (cached.composerIntent === 'workflow') {
      composerIntent.value = CANVAS_SKILL_INTENT
    } else if (INTENT_META[cached.composerIntent]) {
      composerIntent.value = cached.composerIntent
    }
    if (typeof cached.modFrontendEnabled === 'boolean') {
      modFrontendEnabled.value = cached.modFrontendEnabled
    }
    planSession.value = restorePlanSession(cached.planSession)
    planReplyDraft.value = typeof cached.planReplyDraft === 'string' ? cached.planReplyDraft : ''
    planOptionSelections.value =
      cached.planOptionSelections && typeof cached.planOptionSelections === 'object'
        ? cached.planOptionSelections
        : {}
    clearPlanOptionOtherText()
    if (cached.planOptionOtherText && typeof cached.planOptionOtherText === 'object') {
      for (const [k, v] of Object.entries(cached.planOptionOtherText)) {
        planOptionOtherText[k] = String(v || '')
      }
    }
    pendingHandoff.value = restorePendingHandoff(cached.pendingHandoff)
    finalizeLoading.value = Boolean(cached.finalizeLoading)
    finalizeError.value = typeof cached.finalizeError === 'string' ? cached.finalizeError : ''
    orchestrationSession.value = cached.orchestrationSession || null
    orchestrationSessionId.value = String(cached.orchestrationSessionId || '').trim()
    orchPhase.value = cached.orchPhase || (finalizeLoading.value ? 'running' : 'idle')
    orchestrationEtaSeconds.value =
      cached.orchestrationEtaSeconds == null ? null : Number(cached.orchestrationEtaSeconds)
    orchestrationEtaReason.value =
      typeof cached.orchestrationEtaReason === 'string' ? cached.orchestrationEtaReason : ''
    orchTimingStartMs.value =
      cached.orchTimingStartMs == null ? null : Number(cached.orchTimingStartMs)
    workflowLinkOffer.value = cached.workflowLinkOffer || null
    if (Array.isArray(cached.voiceMessages)) voiceMessages.value = cached.voiceMessages
    if (cached.voiceChatPhase) voiceChatPhase.value = cached.voiceChatPhase
    if (cached.voiceInjectQueue) voiceInjectQueue.value = cached.voiceInjectQueue
    syncVoiceWorkPhase()
  } catch {
    clearMakeProgressCache()
  }
}
function applyInlineVoiceText(suffix: string) {
  if (!__wbState.inlineVoiceTarget) return
  const value = __wbState.inlineVoicePrefix + suffix
  if (__wbState.inlineVoiceTarget === 'direct') directDraft.value = value
  else makeComposerInput.value = value
}
function stopInlineVoiceCapture() {
  __wbState.inlineVoiceTarget = null
  __wbState.inlineVoicePrefix = ''
}
function clearInlineVoicePermissionHint(target: 'direct' | 'make') {
  if (target === 'direct') directVoicePermissionHint.value = ''
  else makeVoicePermissionHint.value = ''
}
function setInlineVoicePermissionHint(target: 'direct' | 'make', msg: string) {
  const text = String(msg || '').trim()
  if (!text) return
  if (target === 'direct') {
    directVoicePermissionHint.value = text
    directError.value = text
  } else {
    makeVoicePermissionHint.value = text
  }
  showAppToast(text, { variant: 'error' })
}
function cancelInlineVoice(target: 'direct' | 'make', opts?: { silent?: boolean }) {
  const wasRecording = target === 'direct' ? directVoiceListening.value : makeVoiceListening.value
  const wasRecognizing = target === 'direct' ? directVoiceRecognizing.value : makeVoiceRecognizing.value
  if (!wasRecording && !wasRecognizing && __wbState.inlineVoiceTarget !== target) return

  inlineAsr.abort()
  __wbState.inlineHoldActive = false
  __wbState.inlineHoldPointerId = -1
  __wbState.inlineHoldCancelIntent = false
  __wbState.inlineHoldStartY = 0

  if (target === 'direct') {
    directVoiceListening.value = false
    directVoiceRecognizing.value = false
    directVoiceAudioLevel.value = 0
    if (__wbState.inlineVoiceTarget === 'direct') directDraft.value = __wbState.inlineVoicePrefix
  } else {
    makeVoiceListening.value = false
    makeVoiceRecognizing.value = false
    if (__wbState.inlineVoiceTarget === 'make') makeComposerInput.value = __wbState.inlineVoicePrefix
  }
  stopInlineVoiceCapture()
  if (!opts?.silent && (wasRecording || wasRecognizing)) {
    showAppToast('已取消语音输入', { variant: 'info' })
  }
}
async function stopInlineVoice(target: 'direct' | 'make'): Promise<string> {
  if (target === 'direct') {
    directVoiceListening.value = false
    directVoiceRecognizing.value = true
  } else {
    makeVoiceListening.value = false
    makeVoiceRecognizing.value = true
  }
  directVoiceAudioLevel.value = 0
  let finalText = ''
  try {
    const text = await inlineAsr.stopListening()
    finalText = text.trim()
    if (finalText && __wbState.inlineVoiceTarget === target) {
      applyInlineVoiceText(finalText)
    } else if (!finalText) {
      finalText = (target === 'direct' ? directDraft.value : makeComposerInput.value).trim()
    }
  } finally {
    if (target === 'direct') directVoiceRecognizing.value = false
    else makeVoiceRecognizing.value = false
  }
  stopInlineVoiceCapture()
  return finalText
}
function onInlineHoldMove(e: PointerEvent) {
  if (!__wbState.inlineHoldActive) return
  if (__wbState.inlineHoldPointerId >= 0 && e.pointerId !== __wbState.inlineHoldPointerId) return
  __wbState.inlineHoldCancelIntent = __wbState.inlineHoldStartY - e.clientY > 56
}
function onDirectVoicePointerMove(e: PointerEvent) {
  if (wbNav.isMobile) onInlineHoldMove(e)
}
function stopDirectVoice() {
  void stopInlineVoice('direct')
}
function voiceBtnLongPressStart() {
  __wbState.voiceBtnLongPressFired = false
  __wbState.voiceBtnLongPressTimer = setTimeout(() => {
    __wbState.voiceBtnLongPressFired = true
    requestMicInUserGesture()
    void unlockVoiceAudioPlayback()
    wbSidebar.activeMode = 'voice'
  }, 600)
}
function voiceBtnLongPressCancel() {
  if (__wbState.voiceBtnLongPressTimer) {
    clearTimeout(__wbState.voiceBtnLongPressTimer)
    __wbState.voiceBtnLongPressTimer = null
  }
}
function stopMakeVoice() {
  void stopInlineVoice('make')
}
function onWbOpenSettings() {
  personalSettingsOpen.value = true
}
function onWbPickConversation(e: Event) {
  const detail = (e as CustomEvent<{ id?: string }>).detail
  const id = typeof detail?.id === 'string' ? detail.id.trim() : ''
  if (id) setActiveConversation(id)
}
function clearWorkbenchHandoffSession() {
  try {
    sessionStorage.removeItem('workbench_home_draft')
    sessionStorage.removeItem('workbench_home_intent')
    sessionStorage.removeItem('workbench_home_llm')
    sessionStorage.removeItem('workbench_home_llm_mode')
  } catch {
    /* ignore */
  }
  clearMakeProgressCache()
}
function isModHostStackSurveyQuestion(q: PlanQuestion): boolean {
  const t = String(q?.title || '').trim()
  if (!t) return false
  if (/员工包.*语言|后端.*语言|^语言$/i.test(t)) return true
  if (/API\s*(设计|风格)|RESTful|RPC\s*风格|统一前缀/i.test(t)) return true
  if (/前端\s*UI|UI\s*框架|Element\s*Plus|Ant\s*Design|Vant/i.test(t)) return true
  return false
}
function normalizePlanOptions(raw: unknown): PlanQuestion[] {
  const out: PlanQuestion[] = []
  if (!Array.isArray(raw)) return out
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue
    const qid = String(item.id || '').trim().slice(0, 48)
    const title = String(item.title || item.question || '').trim().slice(0, 120)
    const choicesIn = item.choices
    if (!qid || !title || !Array.isArray(choicesIn)) continue
    const choices = []
    for (const c of choicesIn) {
      if (!c || typeof c !== 'object') continue
      const cid = String(c.id || '').trim().slice(0, 48)
      const label = String(c.label || c.text || '').trim().slice(0, 160)
      if (!cid || !label) continue
      choices.push({ id: cid, label })
    }
    if (choices.length < 2) continue
    if (choices.length > 5) choices.length = 5
    out.push({ id: qid, title, choices })
  }
  return out.slice(0, 6)
}
/** 解析规划助手回复：Mermaid + <<<PLAN_DETAILS>>> + <<<PLAN_OPTIONS>>> JSON（与 buildPlanSystemPrompt 约定一致） */
function parsePlanAssistantContent(raw: unknown): {
  diagram: string
  details: string
  hasDiagram: boolean
  options: PlanQuestion[]
} {
  const s = String(raw || '')
  const mer = s.match(/```mermaid\s*([\s\S]*?)```/i)
  const diagram = mer ? mer[1].trim() : ''
  const det = s.match(/<<<PLAN_DETAILS>>>([\s\S]*?)<<<END_PLAN_DETAILS>>>/i)
  const opt = s.match(/<<<PLAN_OPTIONS>>>([\s\S]*?)<<<END_PLAN_OPTIONS>>>/i)
  let options: PlanQuestion[] = []
  if (opt) {
    const rawJson = opt[1].trim()
    try {
      options = normalizePlanOptions(JSON.parse(rawJson))
    } catch {
      options = []
    }
  }
  let details = det ? det[1].trim() : ''
  if (!details) {
    let rest = stripInternalMarkers(s)
    if (mer) rest = rest.replace(mer[0], '')
    if (det) rest = rest.replace(det[0], '')
    if (opt) rest = rest.replace(opt[0], '')
    rest = rest.replace(/<<<PLAN_DETAILS>>>[\s\S]*/gi, '')
    rest = rest.replace(/<<<PLAN_OPTIONS>>>[\s\S]*/gi, '')
    rest = rest.replace(/```mermaid[\s\S]*?```/gi, '')
    details = rest.replace(/^\s*\n+|\n+\s*$/g, '').trim()
  }
  if (!details && diagram) details = '（仅流程图，无补充说明）'
  const hasDiagram = diagram.length > 0
  return { diagram, details, hasDiagram, options }
}
const planQuickOptions = computed(() => {
  const ps = planSession.value
  if (!ps?.messages?.length) return []
  for (let i = ps.messages.length - 1; i >= 0; i--) {
    if (ps.messages[i].role === 'assistant') {
      let o = parsePlanAssistantContent(ps.messages[i].content).options
      if (!Array.isArray(o)) return []
      if (ps.intentKey === 'mod') {
        o = o.filter((q) => !isModHostStackSurveyQuestion(q))
      }
      return o
    }
  }
  return []
})
const planPanelTitle = computed(() => {
  const ps = planSession.value
  if (!ps) return '需求规划'
  if (ps.phase === 'summary') return ps.summaryTitle || '确认任务摘要'
  return ps.summaryTitle || '需求规划'
})
function mermaidChecklistLabel(text: unknown, max = 30): string {
  const s = String(text || '')
    .replace(/^\s*\d+[.)、]\s*/, '')
    .replace(/[<>]/g, '')
    .replace(/["[\]{}]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
  if (!s) return '步骤'
  return s.length > max ? `${s.slice(0, max)}…` : s
}

  return {
    ...ctx, _handoffRunStatusLine, orchStepRunningSec, _stepLastMsgChange, orchStepSlowHint,
    _trackStepMessages, structuredStepMessage, stepMsgSummary, stepMsgCurrentTool, stepMsgTodos,
    stepMsgSlowHint, cachedFileMetadata, normalizePlanMessages, serializablePlanSession, restorePlanSession,
    serializablePendingHandoff, restorePendingHandoff, makeHasCachedProgress, cacheMakeProgress, clearMakeProgressCache,
    restoreMakeProgressCache, applyInlineVoiceText, stopInlineVoiceCapture, clearInlineVoicePermissionHint, setInlineVoicePermissionHint,
    cancelInlineVoice, stopInlineVoice, onInlineHoldMove, onDirectVoicePointerMove, stopDirectVoice,
    voiceBtnLongPressStart, voiceBtnLongPressCancel, stopMakeVoice, onWbOpenSettings, onWbPickConversation,
    clearWorkbenchHandoffSession, isModHostStackSurveyQuestion, normalizePlanOptions, parsePlanAssistantContent, planQuickOptions,
    planPanelTitle, mermaidChecklistLabel,
  }
}

export type useWbRestoreMakeProgressCacheBinds = ReturnType<typeof useWbRestoreMakeProgressCache>
