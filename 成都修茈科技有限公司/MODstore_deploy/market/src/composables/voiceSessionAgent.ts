import { ref, type Ref } from 'vue'
import { api } from '../api'
import {
  routeVoiceUtterance,
  type VoiceRouteContext,
  VOICE_PUSHBACK_RE,
  inferUserGoalFromVoiceMessages,
  hasEmployeePlanContext,
  looksLikeEmployeeTaskDescription,
  isLikelyShortProceedFragment,
} from './voiceUtteranceRouter'
import { normalizeVoiceAsrText } from './normalizeVoiceAsrText'

export type VoiceSessionStage =
  | 'exploring'
  | 'clarifying'
  | 'ready_to_plan'
  | 'planning'
  | 'executing'

export type VoiceUserTone = 'neutral' | 'complaint' | 'confirm' | 'cancel'

export type VoiceAgentAction =
  | 'chat'
  | 'clarify'
  | 'open_plan'
  | 'update_plan'
  | 'dismiss_plan'
  | 'confirm_plan'
  | 'pause_checklist'
  | 'cancel_work'
  | 'status'

export interface VoiceSessionState {
  mode: 'employee' | 'mod' | 'skill'
  stage: VoiceSessionStage
  userGoal: string
  openQuestions: string[]
  constraints: string[]
  lastUserTone: VoiceUserTone
  readyToPlan: boolean
  planDismissedAt?: number
}

export interface VoiceTurnClassification {
  action: VoiceAgentAction
  replyHint: string
  statePatch: Partial<VoiceSessionState>
  confidence: number
}

export interface ClassifyVoiceTurnContext {
  text: string
  state: VoiceSessionState
  recentMessages: Array<{ role: string; content: string }>
  routeCtx: Omit<VoiceRouteContext, 'text'>
  composerIntent: string
  provider: string
  model: string
}

const VALID_ACTIONS = new Set<VoiceAgentAction>([
  'chat',
  'clarify',
  'open_plan',
  'update_plan',
  'dismiss_plan',
  'confirm_plan',
  'pause_checklist',
  'cancel_work',
  'status',
])

export function createDefaultVoiceSessionState(
  mode: VoiceSessionState['mode'] = 'employee',
): VoiceSessionState {
  return {
    mode,
    stage: 'exploring',
    userGoal: '',
    openQuestions: [],
    constraints: [],
    lastUserTone: 'neutral',
    readyToPlan: false,
  }
}

export function applyVoiceSessionPatch(
  state: VoiceSessionState,
  patch: Partial<VoiceSessionState> | undefined,
): VoiceSessionState {
  if (!patch || !Object.keys(patch).length) return state
  if (patch.userGoal !== undefined) state.userGoal = String(patch.userGoal || '').trim()
  if (patch.openQuestions !== undefined) {
    state.openQuestions = Array.isArray(patch.openQuestions)
      ? patch.openQuestions.map((q) => String(q).trim()).filter(Boolean).slice(0, 6)
      : []
  }
  if (patch.constraints !== undefined) {
    state.constraints = Array.isArray(patch.constraints)
      ? patch.constraints.map((c) => String(c).trim()).filter(Boolean).slice(0, 8)
      : []
  }
  if (patch.stage !== undefined) state.stage = patch.stage
  if (patch.lastUserTone !== undefined) state.lastUserTone = patch.lastUserTone
  if (patch.readyToPlan !== undefined) state.readyToPlan = !!patch.readyToPlan
  if (patch.planDismissedAt !== undefined) state.planDismissedAt = patch.planDismissedAt
  if (patch.mode !== undefined) state.mode = patch.mode
  return state
}

export function resetVoiceSessionState(
  stateRef: Ref<VoiceSessionState>,
  mode: VoiceSessionState['mode'] = 'employee',
) {
  stateRef.value = createDefaultVoiceSessionState(mode)
}

export function buildAgentAwarePrompt(state: VoiceSessionState, extraHint?: string): string {
  const parts = [
    '【会话理解状态】',
    `阶段：${state.stage}`,
    state.userGoal ? `用户目标（已理解）：${state.userGoal}` : '用户目标：尚未明确',
  ]
  if (state.openQuestions.length) {
    parts.push(`待澄清：${state.openQuestions.join('；')}`)
  }
  if (state.constraints.length) {
    parts.push(`已知约束：${state.constraints.join('；')}`)
  }
  if (state.readyToPlan) {
    parts.push('系统判断：目标已基本清晰；用户若确认推进，应执行对应阶段动作，勿只回复「正在规划」却不执行。')
  } else {
    parts.push('系统判断：仍在探索/澄清，禁止输出「已开始规划」或催促确认摘要。')
  }
  parts.push(
    '闲聊或 ASR 噪声时：简短确认听清与否，不要画 Mermaid/流程图，除非用户明确要求「画个图」。',
  )
  if (extraHint?.trim()) parts.push(extraHint.trim())
  return parts.join('\n')
}

function extractJsonObject(raw: string): Record<string, unknown> | null {
  const text = String(raw || '').trim()
  if (!text) return null
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/i)
  const candidate = fenced?.[1]?.trim() || text
  const start = candidate.indexOf('{')
  const end = candidate.lastIndexOf('}')
  if (start < 0 || end <= start) return null
  try {
    return JSON.parse(candidate.slice(start, end + 1)) as Record<string, unknown>
  } catch {
    return null
  }
}

function normalizeAction(raw: unknown): VoiceAgentAction {
  const a = String(raw || '').trim() as VoiceAgentAction
  return VALID_ACTIONS.has(a) ? a : 'chat'
}

function normalizeTone(raw: unknown): VoiceUserTone {
  const t = String(raw || '').trim()
  if (t === 'complaint' || t === 'confirm' || t === 'cancel') return t
  return 'neutral'
}

function normalizeStage(raw: unknown): VoiceSessionStage | undefined {
  const s = String(raw || '').trim()
  if (
    s === 'exploring' ||
    s === 'clarifying' ||
    s === 'ready_to_plan' ||
    s === 'planning' ||
    s === 'executing'
  ) {
    return s
  }
  return undefined
}

export function parseClassificationResponse(raw: string): VoiceTurnClassification | null {
  const obj = extractJsonObject(raw)
  if (!obj) return null
  const patchRaw = (obj.statePatch || obj.state_patch) as Record<string, unknown> | undefined
  const patch: Partial<VoiceSessionState> = {}
  if (patchRaw && typeof patchRaw === 'object') {
    if (patchRaw.userGoal !== undefined || patchRaw.user_goal !== undefined) {
      patch.userGoal = String(patchRaw.userGoal ?? patchRaw.user_goal ?? '').trim()
    }
    if (Array.isArray(patchRaw.openQuestions || patchRaw.open_questions)) {
      patch.openQuestions = (patchRaw.openQuestions || patchRaw.open_questions) as string[]
    }
    if (Array.isArray(patchRaw.constraints)) {
      patch.constraints = patchRaw.constraints as string[]
    }
    const stage = normalizeStage(patchRaw.stage)
    if (stage) patch.stage = stage
    patch.lastUserTone = normalizeTone(patchRaw.lastUserTone ?? patchRaw.last_user_tone)
    if (patchRaw.readyToPlan !== undefined || patchRaw.ready_to_plan !== undefined) {
      patch.readyToPlan = Boolean(patchRaw.readyToPlan ?? patchRaw.ready_to_plan)
    }
  }
  const confidence = Math.max(0, Math.min(1, Number(obj.confidence) || 0.5))
  return {
    action: normalizeAction(obj.action),
    replyHint: String(obj.replyHint ?? obj.reply_hint ?? '').trim(),
    statePatch: patch,
    confidence,
  }
}

function buildClassifierSystemPrompt(composerIntent: string): string {
  return [
    '你是语音工作台话语分类器。根据用户最新一句话、对话历史、规划阶段与系统状态，输出唯一 JSON（不要 markdown）。',
    `工作台模式：${composerIntent || 'employee'}。`,
    '字段：action, replyHint, statePatch, confidence(0~1)。',
    'action 取值：chat|clarify|open_plan|update_plan|dismiss_plan|confirm_plan|pause_checklist|cancel_work|status',
    '',
    '通用：',
    '- ASR 噪声、无关闲聊 → chat',
    '- 用户抱怨过早开工 → dismiss_plan，lastUserTone=complaint',
    '- 取消/停下制作 → cancel_work；问进度 → status',
    '',
    '无规划会话（planSessionPhase=null）：',
    '- 用户在描述员工/Mod 任务 → clarify，更新 userGoal；若已写清职责与产出 → open_plan，readyToPlan=true',
    '',
    'planSessionPhase=summary：',
    '- 用户确认摘要、同意开始规划 → confirm_plan',
    '- 用户补充/修改需求 → update_plan',
    '- 禁止 classify 为 chat 后只让对话模型说「正在规划」',
    '',
    'planSessionPhase=chat：',
    '- 用户回答澄清问题 → update_plan',
    '- 用户明确同意生成清单/开始制作/可以了 → confirm_plan',
    '',
    'planSessionPhase=checklist（执行清单已展示）：',
    '- 用户同意推进（嗯、好、开始、可以、就这样等任意口语）→ confirm_plan',
    '- 用户要改清单 → update_plan',
    '- 用户说等一下/先别/暂停自动制作 → pause_checklist',
    '- 不要输出「整理摘要」类 replyHint',
    '',
    'orchestrating=true 或 finalizeLoading=true：',
    '- 问进度 → status；补充需求 → chat（系统将作插话）',
    '',
    '禁止编造用户未提及的文件或数据。',
  ].join('\n')
}

function buildClassifierUserPayload(ctx: ClassifyVoiceTurnContext): string {
  const history = ctx.recentMessages
    .slice(-6)
    .map((m) => `${m.role}: ${String(m.content || '').slice(0, 400)}`)
    .join('\n')
  const lastAssistant = [...ctx.recentMessages].reverse().find((m) => m.role === 'assistant')
  return JSON.stringify(
    {
      utterance: ctx.text.trim(),
      sessionState: ctx.state,
      hasPlanSession: ctx.routeCtx.hasPlanSession,
      planSessionPhase: ctx.routeCtx.planSessionPhase ?? null,
      pendingHandoff: !!ctx.routeCtx.pendingHandoff,
      finalizeLoading: !!ctx.routeCtx.finalizeLoading,
      orchestrating: !!ctx.routeCtx.orchestrating,
      voiceTitle: ctx.routeCtx.voiceTitle ?? null,
      checklistLineCount: ctx.routeCtx.checklistLineCount ?? 0,
      lastAssistantSnippet: String(lastAssistant?.content || '').slice(0, 280),
      recentMessages: history,
    },
    null,
    0,
  )
}

export function fallbackClassifyVoiceTurn(ctx: ClassifyVoiceTurnContext): VoiceTurnClassification {
  const route = routeVoiceUtterance({
    text: ctx.text,
    ...ctx.routeCtx,
    composerIntent: ctx.composerIntent,
  })
  let action: VoiceAgentAction = 'chat'
  let replyHint = ''
  const statePatch: Partial<VoiceSessionState> = {}
  const phase = ctx.routeCtx.planSessionPhase

  switch (route.type) {
    case 'cancel_work':
      action = 'cancel_work'
      break
    case 'status_query':
      action = 'status'
      break
    case 'confirm_generate':
      action = 'confirm_plan'
      replyHint = '草稿已就绪，开始制作。'
      break
    case 'inject':
      action = 'chat'
      replyHint = '用户正在制作中补充需求，简短确认已记录。'
      break
    case 'plan_reply':
      if (phase === 'checklist' && /等一下|先别|暂停|等等|先别做/.test(ctx.text.trim())) {
        action = 'pause_checklist'
        replyHint = '用户要求暂停自动制作。'
      } else if (phase === 'checklist') {
        action = 'confirm_plan'
        replyHint = '清单已就绪，用户同意开始制作。'
      } else {
        action = 'update_plan'
      }
      break
    case 'new_task':
      action = looksLikeEmployeeTaskDescription(ctx.text) ? 'open_plan' : 'clarify'
      if (action === 'open_plan') {
        statePatch.readyToPlan = hasEmployeePlanContext(ctx.state, ctx.recentMessages, ctx.text)
        statePatch.stage = 'planning'
        statePatch.userGoal = ctx.state.userGoal || ctx.text.trim()
      } else {
        statePatch.userGoal = ctx.state.userGoal || ctx.text.trim()
        statePatch.stage = 'clarifying'
      }
      break
    default:
      action = 'chat'
  }

  return { action, replyHint, statePatch, confidence: 0.5 }
}

export function coerceClassificationForEmployee(
  classification: VoiceTurnClassification,
  state: VoiceSessionState,
  ctx?: {
    text?: string
    recentMessages?: Array<{ role: string; content: string }>
    planSessionPhase?: string
  },
): VoiceTurnClassification {
  const text = String(ctx?.text || '').trim()

  if (text && VOICE_PUSHBACK_RE.test(text)) {
    return {
      ...classification,
      action: 'dismiss_plan',
      replyHint: classification.replyHint || '用户质疑过早执行，说明当前阶段并询问是否继续。',
      statePatch: { ...classification.statePatch, lastUserTone: 'complaint' },
      confidence: Math.max(classification.confidence, 0.85),
    }
  }

  let { action, confidence } = classification

  if (
    ctx?.planSessionPhase === 'checklist' &&
    action === 'chat' &&
    confidence < 0.55 &&
    text.length <= 16
  ) {
    action = 'clarify'
    classification.replyHint =
      classification.replyHint || '清单已展示，请用户明确是否开始制作，或说修改哪一条。'
  }

  if (action === 'open_plan') {
    const patchReady =
      classification.statePatch.readyToPlan ?? state.readyToPlan ?? looksLikeEmployeeTaskDescription(text)
    if (!patchReady && confidence < 0.65) {
      action = 'clarify'
      classification.replyHint =
        classification.replyHint ||
        '先复述你对用户需求的理解，并追问 1-2 个关键点；不要开规划面板。'
    }
  }

  return { ...classification, action, confidence }
}

/** 有规划会话时走 LLM；仅纯噪声/极短寒暄可走 fallback */
export function shouldUseFastVoiceClassifier(ctx: ClassifyVoiceTurnContext): boolean {
  const t = ctx.text.trim()
  if (ctx.composerIntent === 'employee') {
    if (ctx.routeCtx.hasPlanSession || ctx.routeCtx.planSessionPhase) return false
    if (looksLikeEmployeeTaskDescription(t) || hasEmployeePlanContext(ctx.state, ctx.recentMessages, t)) {
      return false
    }
  }
  if (!t || t.length <= 2) return true
  const route = routeVoiceUtterance({
    text: t,
    ...ctx.routeCtx,
    composerIntent: ctx.composerIntent,
  })
  if (route.type !== 'chat') return true
  if (/做|员工|规划|生成|分析|数据|mod|skill|任务|需求|word|docx/i.test(t)) return false
  return t.length <= 12
}

export async function classifyVoiceTurn(
  ctx: ClassifyVoiceTurnContext,
): Promise<VoiceTurnClassification> {
  if (shouldUseFastVoiceClassifier(ctx)) {
    return coerceClassificationForEmployee(fallbackClassifyVoiceTurn(ctx), ctx.state, {
      text: ctx.text,
      recentMessages: ctx.recentMessages,
      planSessionPhase: ctx.routeCtx.planSessionPhase,
    })
  }
  try {
    const res = (await api.llmChat(ctx.provider, ctx.model, [
      { role: 'system', content: buildClassifierSystemPrompt(ctx.composerIntent) },
      { role: 'user', content: buildClassifierUserPayload(ctx) },
    ], 200)) as { content?: unknown }
    const parsed = parseClassificationResponse(String(res?.content ?? ''))
    if (parsed) {
      return coerceClassificationForEmployee(parsed, ctx.state, {
        text: ctx.text,
        recentMessages: ctx.recentMessages,
        planSessionPhase: ctx.routeCtx.planSessionPhase,
      })
    }
  } catch {
    /* fallback */
  }
  return coerceClassificationForEmployee(fallbackClassifyVoiceTurn(ctx), ctx.state, {
    text: ctx.text,
    recentMessages: ctx.recentMessages,
    planSessionPhase: ctx.routeCtx.planSessionPhase,
  })
}

export function isSummaryNeedsClarification(title: string, summary: string): boolean {
  const t = String(title || '').trim()
  const s = String(summary || '').trim()
  return t === '待澄清' || t.includes('待澄清') || s.startsWith('待澄清')
}

export function sanitizeVoiceUtteranceText(text: string): string {
  return normalizeVoiceAsrText(
    String(text || '')
      .trim()
      .replace(/^undefined(?=\S)/, '')
      .trim(),
  )
}

export function isLikelyAsrEchoNoise(text: string, topicHint: string): boolean {
  const t = text.trim()
  if (t.length < 8) return false
  if (/word|docx|文档|提取|json|员工|表格|全量|extract/i.test(t)) return false
  if (/word|docx|文档|全量|提取/i.test(topicHint)) {
    if (/相处|报备|行程|分享生活|珍贵|温柔|陪伴|理解你的需求|规划面板|不甘心|是不是喜欢/i.test(t)) {
      return true
    }
  }
  return false
}

const PLAN_PLACEHOLDER_RE = /（无回复）/

export function isPlaceholderPlanContent(text: string): boolean {
  const t = sanitizeVoiceUtteranceText(text)
  if (!t) return true
  const stripped = t.replace(PLAN_PLACEHOLDER_RE, '').trim()
  if (!stripped) return true
  if (stripped.length < 8 && isLikelyShortProceedFragment(t)) return true
  if (PLAN_PLACEHOLDER_RE.test(t) && stripped.length < 24) return true
  return false
}

export function pickBestEmployeeBriefFromVoice(
  state: VoiceSessionState,
  messages: Array<{ role: string; content: string }>,
  excludeUtterance?: string,
): string {
  const ex = sanitizeVoiceUtteranceText(excludeUtterance || '')
  const topicHint = [state.userGoal, ...messages.map((m) => String(m.content || ''))].join(' ')
  const goal = sanitizeVoiceUtteranceText(state.userGoal)
  if (goal && !isPlaceholderPlanContent(goal)) return goal

  const userChunks = messages
    .filter((m) => m.role === 'user')
    .map((m) => sanitizeVoiceUtteranceText(String(m.content || '')))
    .filter(
      (t) =>
        t &&
        t !== ex &&
        !isPlaceholderPlanContent(t) &&
        !isLikelyShortProceedFragment(t) &&
        !isLikelyAsrEchoNoise(t, topicHint),
    )

  if (!userChunks.length) return goal || ''

  const scored = userChunks.map((t) => ({
    t,
    score: (looksLikeEmployeeTaskDescription(t) ? 200 : 0) + Math.min(t.length, 300),
  }))
  scored.sort((a, b) => b.score - a.score)
  return scored[0]?.t || userChunks[userChunks.length - 1] || ''
}

export function formatFilteredPlanMessagesForBrief(
  msgs: Array<{ role: string; content: string }>,
  topicHint?: string,
): string {
  if (!Array.isArray(msgs) || !msgs.length) return ''
  const hint = topicHint || msgs.map((m) => m.content).join(' ')
  return msgs
    .map((m) => {
      const c = sanitizeVoiceUtteranceText(String(m.content || ''))
      if (!c || isPlaceholderPlanContent(c)) return ''
      if (m.role === 'user' && isLikelyAsrEchoNoise(c, hint)) return ''
      if (m.role === 'assistant' && /^```\s*mermaid/i.test(c)) return ''
      return `${m.role === 'user' ? '用户' : '助手'}：${c}`
    })
    .filter(Boolean)
    .join('\n\n')
}

export function buildDefaultEmployeePlanAssistantReply(brief: string): string {
  const core = sanitizeVoiceUtteranceText(brief)
  const summary = core ? core.slice(0, 480) : 'Word 文档全量提取为 JSON'
  return [
    `已理解需求：${summary}`,
    '默认方案：图片导出到 outputs/images/；格式保留标题层级与表格结构；输出 document_full.json 与 document_full.txt。',
    '若无疑问，将按此方案生成执行清单并制作员工包。',
  ].join('\n')
}

export function buildPlanBriefFromSessionState(
  state: VoiceSessionState,
  utterance: string,
): string {
  const parts: string[] = []
  const goal = sanitizeVoiceUtteranceText(state.userGoal)
  if (goal) parts.push(`【已理解的用户目标】\n${goal}`)
  if (state.constraints.length) parts.push(`【约束】\n${state.constraints.join('\n')}`)
  const u = sanitizeVoiceUtteranceText(utterance)
  if (u) parts.push(`【用户原话】\n${u}`)
  return parts.join('\n\n') || u
}

export function buildPlanBriefFromVoiceMessages(
  state: VoiceSessionState,
  messages: Array<{ role: string; content: string }>,
  triggerUtterance?: string,
): string {
  const parts: string[] = []
  const goal = sanitizeVoiceUtteranceText(state.userGoal)
  if (goal) parts.push(`【已理解的用户目标】\n${goal}`)
  if (state.constraints.length) parts.push(`【约束】\n${state.constraints.join('\n')}`)
  const topicHint = [
    goal,
    ...messages.map((m) => String(m.content || '')),
    String(triggerUtterance || ''),
  ].join(' ')
  const transcript = messages
    .map((m) => {
      const c = sanitizeVoiceUtteranceText(String(m.content || ''))
      if (!c) return ''
      if (m.role === 'user' && isLikelyAsrEchoNoise(c, topicHint)) return ''
      return `${m.role === 'user' ? '用户' : '助手'}：${c}`
    })
    .filter(Boolean)
    .join('\n')
  if (transcript) parts.push(`【语音对话记录】\n${transcript}`)
  const trig = sanitizeVoiceUtteranceText(triggerUtterance || '')
  if (trig && !transcript.includes(trig)) parts.push(`【触发规划口令】\n${trig}`)
  return parts.join('\n\n') || trig || goal
}

export function useVoiceSessionAgent(initialMode: VoiceSessionState['mode'] = 'employee') {
  const voiceSessionState = ref<VoiceSessionState>(createDefaultVoiceSessionState(initialMode))
  return { voiceSessionState }
}
