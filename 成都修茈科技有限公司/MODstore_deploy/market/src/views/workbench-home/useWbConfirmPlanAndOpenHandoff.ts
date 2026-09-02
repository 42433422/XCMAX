import { nextTick } from 'vue'
import { api } from '../../api'
import { streamLLMChat } from '../../utils/llmStream'
import type { VoiceTurnMessage } from '../../composables/voiceUserTurnCoalesce'
import { classifyVoiceTurn, pickBestEmployeeBriefFromVoice, formatFilteredPlanMessagesForBrief, buildDefaultEmployeePlanAssistantReply, isSummaryNeedsClarification } from '../../composables/voiceSessionAgent'
import type { useWbSendDirectChat } from './useWbSendDirectChat'
import type { OpenPlanSessionInput, PlanChoice } from './types'

// 拆分自 WorkbenchHomeView.vue（原行 3586–3599, 6461–6475, 6609–6644 …）；逐字迁移，行为不变。
export function useWbConfirmPlanAndOpenHandoff(ctx: ReturnType<typeof useWbSendDirectChat>) {
  const {
    suggestModIdFromText, draft, workbenchErrorMessage, inputRef, pendingHandoff, finalizeError,
    __wbState, planSession, planReplyDraft, planOptionSelections, PLAN_OPTION_OTHER_ID, planOptionOtherText,
    clearPlanOptionOtherText, planPanelRef, planSurfaceKey, knowledgeUploading, knowledgeError, knowledgeFileInputRef,
    knowledgeDragActive, CANVAS_SKILL_INTENT, isCanvasSkillIntent, composerIntent, modFrontendEnabled, directAttachedFiles,
    streamingTts, voiceMessages, voiceSessionState, ingestComposerFiles, buildVoiceRouteContext, requireLoginForWorkbenchUse,
    INTENT_META, ORCH_ESTIMATE_SYSTEM, parseOrchestrationEtaFromLlmText, hasWorkflow, planQuickOptions, compactPlanVisibleText,
    buildPlanSummarySystemPrompt, parsePlanSummary, canSendPlanQuickPicks, dismissPlanSession, scrollMakeFlowToEnd, buildPlanSystemPrompt,
    friendlyPlanPanelApiError, resolveChatProviderModel,
  } = ctx

/** 只有明确的员工制作指令才从语音闲聊进入规划面板。 */
async function tryOpenEmployeePlanFromExplicitCommand(
  text: string,
  _options: { userAlreadyInThread?: boolean } = {},
): Promise<boolean> {
  const normalized = String(text || '').trim()
  const explicit =
    /(?:创建|制作|生成|规划|新建|开始做).{0,12}(?:AI\s*)?员工|员工包/.test(
      normalized,
    )
  if (!explicit || !hasWorkflow.value || planSession.value) return false
  composerIntent.value = 'employee'
  await openPlanSession({ fullBrief: normalized, displayBrief: normalized, files: [] })
  return true
}
async function resolveEmployeeClassification(content: string) {
  streamingTts.warmUp()
  const routeCtx = buildVoiceRouteContext()
  const { provider, model } = await resolveChatProviderModel()
  const classification = await classifyVoiceTurn({
    text: content,
    state: voiceSessionState.value,
    recentMessages: voiceMessages.value.slice(-6),
    routeCtx,
    composerIntent: composerIntent.value,
    provider,
    model,
  })
  return classification
}
async function resummarizeVoiceEmployeePlan(forceConcrete: boolean) {
  const ps = planSession.value
  if (!ps || ps.intentKey !== 'employee') return
  const briefBase = ps.fullBrief || ps.displayBrief || ps.initialBrief || ''
  const briefForSummary =
    briefBase +
    (forceConcrete
      ? '\n\n【系统指令】以上语音对话已充分描述员工目标与产出。请直接输出具体 TITLE 与 SUMMARY，禁止 TITLE:待澄清；尚未拍板的细节写在 SUMMARY 末尾「待确认：…」。'
      : '')
  const { provider, model } = await resolveChatProviderModel()
  ps.loading = true
  ps.streamingText = ''
  try {
    const handle = streamLLMChat({
      provider,
      model,
      messages: [
        { role: 'system', content: buildPlanSummarySystemPrompt(ps.intentTitle, 'employee-voice') },
        { role: 'user', content: briefForSummary },
      ],
      maxTokens: 700,
      onToken: (_delta, soFar) => {
        if (planSession.value) planSession.value.streamingText = soFar
      },
    })
    const { content } = await handle.done
    if (planSession.value) planSession.value.streamingText = ''
    const parsed = parsePlanSummary(content, ps.displayBrief || ps.fullBrief)
    ps.summaryTitle = parsed.title
    ps.summaryText = parsed.summary
    ps.summaryNeedsClarification = isSummaryNeedsClarification(parsed.title, parsed.summary)
    ps.initialBrief = `${parsed.title}\n${parsed.summary}`
  } finally {
    ps.loading = false
  }
}
async function estimateOrchestrationSeconds(ctx: {
  intent: string
  checklistLen: number
  generateFrontend?: boolean
  employeeTarget?: string
  scriptFileCount?: number
  brief: string
}): Promise<{ seconds: number | null; reason: string }> {
  try {
    const { provider, model } = await resolveChatProviderModel()
    const lines = [
      `intent=${ctx.intent}`,
      `execution_checklist 条数=${ctx.checklistLen}`,
      ctx.intent === 'mod' ? `generate_frontend=${ctx.generateFrontend}` : '',
      ctx.intent === 'employee' ? `employee_target=${ctx.employeeTarget || ''}` : '',
      typeof ctx.scriptFileCount === 'number' && ctx.scriptFileCount > 0
        ? `script_workflow 附件数=${ctx.scriptFileCount}`
        : '',
      '--- 需求摘要（截断） ---',
      ctx.brief.slice(0, 3500),
    ].filter(Boolean)
    const res = await api.llmChat(provider, model, [
      { role: 'system', content: ORCH_ESTIMATE_SYSTEM },
      { role: 'user', content: lines.join('\n') },
    ], 256)
    return parseOrchestrationEtaFromLlmText(res?.content)
  } catch {
    return { seconds: null, reason: '' }
  }
}
async function uploadKnowledgeFiles(files: FileList | File[] | null | undefined): Promise<void> {
  const list = Array.from(files || []).filter(Boolean)
  if (!list.length || knowledgeUploading.value) return
  if (!requireLoginForWorkbenchUse()) return
  knowledgeError.value = ''
  try {
    await ingestComposerFiles(list as File[], 'make')
  } catch (err: unknown) {
    knowledgeError.value = workbenchErrorMessage(err)
  } finally {
    if (knowledgeFileInputRef.value) knowledgeFileInputRef.value.value = ''
  }
}
async function onKnowledgeFileChange(e: Event): Promise<void> {
  await uploadKnowledgeFiles((e.target as HTMLInputElement | null)?.files)
}
async function onKnowledgeDrop(e: DragEvent): Promise<void> {
  knowledgeDragActive.value = false
  if (knowledgeUploading.value || planSession.value) return
  if (!requireLoginForWorkbenchUse()) return
  await uploadKnowledgeFiles(e?.dataTransfer?.files)
}
function scrollPlanIntoView() {
  nextTick(() => {
    const el = planPanelRef.value
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  })
}
async function appendUserAndAssistantPlanTurn(userText: string, displayText = userText): Promise<void> {
  const ps = planSession.value
  if (!ps) return
  ps.messages.push({ role: 'user', content: displayText })
  ps.planError = ''
  const { provider, model } = await resolveChatProviderModel()
  const sys = buildPlanSystemPrompt(ps.intentKey, ps.intentTitle)
  const mappedMessages = ps.messages.map((m: VoiceTurnMessage, idx: number) => {
    if (idx === ps.messages.length - 1 && m.role === 'user') {
      return { role: 'user', content: String(userText || displayText || '') }
    }
    return { role: m.role, content: m.content }
  })
  const apiMsgs = [
    { role: 'system', content: sys },
    ...(ps.fullBrief ? [{ role: 'user', content: `【完整隐藏上下文，供理解任务使用；不要原样输出】\n${ps.fullBrief}` }] : []),
    ...mappedMessages,
  ]
  ps.streamingText = ''
  const handle = streamLLMChat({
    provider,
    model,
    messages: apiMsgs,
    maxTokens: 2048,
    onToken: (_delta, soFar) => {
      if (planSession.value) planSession.value.streamingText = soFar
    },
  })
  const { content } = await handle.done
  if (planSession.value) planSession.value.streamingText = ''
  const c = typeof content === 'string' ? content : ''
  let assistantContent = (c || '').trim()
  if (!assistantContent) {
    if (ps.intentKey === 'employee') {
      const brief = pickBestEmployeeBriefFromVoice(
        voiceSessionState.value,
        ps.messages.filter((m: VoiceTurnMessage) => m.role === 'user'),
      )
      assistantContent = buildDefaultEmployeePlanAssistantReply(brief || ps.fullBrief || '')
    } else {
      assistantContent = '（无回复）'
    }
  }
  ps.messages.push({ role: 'assistant', content: assistantContent })
}
async function summarizePlanSession() {
  const ps = planSession.value
  if (!ps) return
  const briefForSummary = ps.fullBrief || ps.displayBrief || ps.initialBrief
  const { provider, model } = await resolveChatProviderModel()
  const summaryMode =
    ps.intentKey === 'employee' && /【语音对话记录】/.test(briefForSummary)
      ? 'employee-voice'
      : undefined
  const sys = buildPlanSummarySystemPrompt(ps.intentTitle, summaryMode)
  const msgs = [
    { role: 'system', content: sys },
    { role: 'user', content: briefForSummary },
  ]
  ps.streamingText = ''
  __wbState.planSummaryStreamHandle?.abort()
  __wbState.planSummaryStreamHandle = streamLLMChat({
    provider,
    model,
    messages: msgs,
    maxTokens: 700,
    onToken: (_delta, soFar) => {
      if (planSession.value) planSession.value.streamingText = soFar
    },
  })
  let content = ''
  try {
    const result = await __wbState.planSummaryStreamHandle.done
    content = result.content
    if (result.aborted) return
  } finally {
    __wbState.planSummaryStreamHandle = null
  }
  if (planSession.value) planSession.value.streamingText = ''
  const parsed = parsePlanSummary(content, ps.displayBrief || ps.fullBrief)
  ps.summaryTitle = parsed.title
  ps.summaryText = parsed.summary
  ps.summaryNeedsClarification = isSummaryNeedsClarification(parsed.title, parsed.summary)
  ps.initialBrief = `${parsed.title}\n${parsed.summary}`
}
async function openPlanSession(input: string | OpenPlanSessionInput): Promise<void> {
  planSurfaceKey.value += 1
  const effectiveIntent = composerIntent.value || CANVAS_SKILL_INTENT
  const meta = INTENT_META[effectiveIntent] || INTENT_META.workflow
  const inputRecord = typeof input === 'object' && input ? input : null
  const fullBrief = inputRecord ? String(inputRecord.fullBrief || '') : String(input || '')
  const displayBrief = inputRecord
    ? String(inputRecord.displayBrief || '')
    : compactPlanVisibleText(fullBrief)
  planSession.value = {
    intentKey: effectiveIntent,
    intentTitle: meta.title,
    phase: 'summary',
    initialBrief: displayBrief,
    fullBrief,
    displayBrief,
    generateFrontend: effectiveIntent === 'mod' ? inputRecord?.generateFrontend !== false : false,
    summaryTitle: '',
    summaryText: '',
    summaryNeedsClarification: false,
    files: Array.isArray(inputRecord?.files) ? inputRecord.files : [],
    messages: [],
    checklistText: '',
    checklistLines: [],
    planError: '',
    loading: true,
    streamingText: '',
  }
  draft.value = ''
  planReplyDraft.value = ''
  planOptionSelections.value = {}
  clearPlanOptionOtherText()
  finalizeError.value = ''
  await nextTick()
  scrollPlanIntoView()
  try {
    await summarizePlanSession()
  } catch (e) {
    const aborted =
      (e as Error)?.name === 'AbortError' ||
      String((e as Error)?.message || e).toLowerCase().includes('abort')
    if (aborted) return
    if (planSession.value) {
      const fallback = parsePlanSummary('', displayBrief || fullBrief)
      planSession.value.summaryTitle = fallback.title
      planSession.value.summaryText = fallback.summary
      planSession.value.summaryNeedsClarification = isSummaryNeedsClarification(fallback.title, fallback.summary)
      planSession.value.initialBrief = `${fallback.title}\n${fallback.summary}`
      planSession.value.planError = `摘要生成失败，已使用输入内容兜底：${friendlyPlanPanelApiError(e)}`
    }
  } finally {
    if (planSession.value) planSession.value.loading = false
  }
}
function backSummaryToComposer() {
  const ps = planSession.value
  if (ps?.displayBrief) draft.value = ps.displayBrief
  dismissPlanSession()
  nextTick(() => {
    const el = inputRef.value
    if (el && typeof el.focus === 'function') el.focus()
  })
}
async function confirmSummaryAndStartPlanning() {
  const ps = planSession.value
  if (!ps || ps.phase !== 'summary' || ps.loading) return
  ps.phase = 'chat'
  ps.messages = []
  ps.planError = ''
  ps.loading = true
  directAttachedFiles.value = []
  planOptionSelections.value = {}
  clearPlanOptionOtherText()
  const visible = `已确认任务：${ps.summaryTitle || '任务摘要'}\n${ps.summaryText || ps.displayBrief || ''}`
  try {
    await appendUserAndAssistantPlanTurn(ps.fullBrief || ps.displayBrief || ps.summaryText, visible)
  } catch (e) {
    ps.planError = friendlyPlanPanelApiError(e)
    ps.messages = []
  } finally {
    ps.loading = false
    scrollPlanIntoView()
  }
}
/** 自主生成：无 LLM 澄清回合时注入默认理解，避免卡在「澄清回合不足」 */
function ensureAutoPilotReadyChatTurns(useDefault = false) {
  const ps = planSession.value
  if (!ps || ps.phase !== 'chat') return
  if ((ps.messages?.length || 0) >= 2) return
  if (!useDefault) return
  const isEmployee = ps.intentKey === 'employee'
  let brief = ''
  if (isEmployee) {
    brief = pickBestEmployeeBriefFromVoice(voiceSessionState.value, voiceMessages.value)
    if (!brief) {
      brief = String(ps.fullBrief || ps.summaryText || ps.displayBrief || '').trim().slice(0, 2000)
    }
  } else {
    brief = String(ps.fullBrief || ps.summaryText || ps.displayBrief || '').trim().slice(0, 2000)
  }
  if (!ps.messages.length) {
    ps.messages.push({ role: 'user', content: brief || '按前述语音需求继续' })
  }
  ps.messages.push({
    role: 'assistant',
    content: isEmployee
      ? buildDefaultEmployeePlanAssistantReply(brief)
      : [
          `已确认任务：${ps.summaryTitle || '员工包'}`,
          ps.summaryText || brief,
          '',
          '未决细节按默认方案：图片单独存储；格式保留标题层级与表格结构；适用通用 Word 文档场景。',
        ]
          .filter(Boolean)
          .join('\n'),
  })
}
function fastEnterChatForAutoPilot() {
  const ps = planSession.value
  if (!ps || ps.phase !== 'summary') return
  ps.phase = 'chat'
  ps.messages = []
  ps.planError = ''
  ps.loading = false
  directAttachedFiles.value = []
  planOptionSelections.value = {}
  clearPlanOptionOtherText()
  ensureAutoPilotReadyChatTurns(true)
  scrollPlanIntoView()
}
function pickPlanOption(qid: string, cid: string): void {
  planOptionSelections.value = { ...planOptionSelections.value, [qid]: cid }
}
/** 每道快捷题选中第一个选项（非「其他」），便于快速填表后再微调 */
function autoPickPlanQuickOptions() {
  const ps = planSession.value
  if (!ps || ps.loading || ps.phase !== 'chat') return
  const opts = planQuickOptions.value
  if (!opts.length) return
  clearPlanOptionOtherText()
  const sel = { ...planOptionSelections.value }
  for (const q of opts) {
    const first = q.choices?.[0]
    if (first?.id) sel[q.id] = first.id
  }
  planOptionSelections.value = sel
}
async function submitPlanUserMessage(userText: string): Promise<void> {
  const ps = planSession.value
  const t = String(userText || '').trim()
  if (!t || !ps || ps.loading || ps.phase !== 'chat') return
  planOptionSelections.value = {}
  clearPlanOptionOtherText()
  ps.loading = true
  ps.planError = ''
  try {
    await appendUserAndAssistantPlanTurn(t)
  } catch (e) {
    ps.planError = friendlyPlanPanelApiError(e)
    if (ps.messages.length && ps.messages[ps.messages.length - 1].role === 'user') {
      ps.messages.pop()
    }
  } finally {
    ps.loading = false
    scrollPlanIntoView()
  }
}
async function sendPlanReply() {
  const t = planReplyDraft.value.trim()
  if (!t) return
  planReplyDraft.value = ''
  await submitPlanUserMessage(t)
}
async function sendPlanReplyFromQuickPicks() {
  const opts = planQuickOptions.value
  if (!opts.length || !canSendPlanQuickPicks.value) return
  const sel = planOptionSelections.value
  const lines: string[] = []
  for (const q of opts) {
    const cid = sel[q.id]
    if (cid === PLAN_OPTION_OTHER_ID) {
      lines.push(`【${q.title}】${String(planOptionOtherText[q.id] || '').trim()}`)
    } else {
      const c = (q.choices || []).find((choice: PlanChoice) => choice.id === cid)
      lines.push(`【${q.title}】${c ? c.label : cid}`)
    }
  }
  await submitPlanUserMessage(lines.join('\n'))
}
function backPlanToChat() {
  const ps = planSession.value
  if (!ps) return
  ps.phase = 'chat'
  ps.checklistText = ''
  ps.checklistLines = []
  ps.planError = ''
}
function confirmPlanAndOpenHandoff() {
  const ps = planSession.value
  if (!ps || ps.phase !== 'checklist') return
  const isEmployee = ps.intentKey === 'employee'
  const topicHint = [
    ps.initialBrief,
    ps.fullBrief,
    ...ps.messages.map((m: VoiceTurnMessage) => m.content),
  ].join(' ')
  const qaText = formatFilteredPlanMessagesForBrief(ps.messages, topicHint)
  let initialChunk = ps.initialBrief
  let employeeBrief = ''
  if (isEmployee) {
    employeeBrief = pickBestEmployeeBriefFromVoice(
      voiceSessionState.value,
      voiceMessages.value.length ? voiceMessages.value : ps.messages,
    )
    if (employeeBrief) {
      initialChunk = [(ps.summaryTitle || '').trim(), employeeBrief].filter(Boolean).join('\n')
    }
  }
  const descChunks = [`【初始想法】\n${initialChunk}`]
  if (qaText) descChunks.push(`【澄清对话】\n${qaText}`)
  descChunks.push(`【执行清单】\n${ps.checklistText}`)
  const description = descChunks.join('\n\n---\n\n')
  const ik = ps.intentKey
  const defaultName =
    (ps.summaryTitle || '').trim() ||
    suggestModIdFromText(`${ps.initialBrief}\n${ps.checklistText}`)
  pendingHandoff.value = {
    description,
    employeeRoutingBrief: isEmployee ? (employeeBrief || ps.initialBrief || '').slice(0, 200) : undefined,
    planningContext: description,
    intentTitle: ps.intentTitle,
    intentKey: ik,
    workflowName: isCanvasSkillIntent(ik) ? defaultName : '',
    planNotes: isCanvasSkillIntent(ik) ? ps.checklistText : '',
    suggestedModId: ik === 'mod' ? suggestModIdFromText(`${ps.initialBrief}\n${ps.checklistText}`) : '',
    files: Array.isArray(ps.files) ? ps.files : [],
    generateFrontend: ik === 'mod' ? modFrontendEnabled.value : false,
    planningMessages: Array.isArray(ps.messages) ? ps.messages.map((m) => ({ role: m.role, content: m.content })) : [],
    executionChecklist: Array.isArray(ps.checklistLines) ? [...ps.checklistLines] : [],
    sourceDocuments: Array.isArray(ps.files)
      ? ps.files.map((f) => ({ name: String(f?.name || ''), size: Number(f?.size || 0), type: String(f?.type || '') }))
      : [],
    employeeTarget: ik === 'employee' ? 'pack_only' : 'pack_only',
    employeeWorkflowName: ik === 'employee' ? defaultName : '',
    fhdBaseUrl: '',
  }
  ps.phase = 'done'
  ps.planError = ''
  nextTick(() => {
    void scrollMakeFlowToEnd()
  })
}

  return {
    ...ctx, tryOpenEmployeePlanFromExplicitCommand, resolveEmployeeClassification, resummarizeVoiceEmployeePlan, estimateOrchestrationSeconds,
    uploadKnowledgeFiles, onKnowledgeFileChange, onKnowledgeDrop, scrollPlanIntoView, appendUserAndAssistantPlanTurn,
    summarizePlanSession, openPlanSession, backSummaryToComposer, confirmSummaryAndStartPlanning, ensureAutoPilotReadyChatTurns,
    fastEnterChatForAutoPilot, pickPlanOption, autoPickPlanQuickOptions, submitPlanUserMessage, sendPlanReply,
    sendPlanReplyFromQuickPicks, backPlanToChat, confirmPlanAndOpenHandoff,
  }
}

export type useWbConfirmPlanAndOpenHandoffBinds = ReturnType<typeof useWbConfirmPlanAndOpenHandoff>
