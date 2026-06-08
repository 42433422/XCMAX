/** 语音话语路由：安全快路径（取消/进度/插话）；业务意图由 LLM 分类器 + 阶段状态机处理 */

export type VoiceRouteAction =
  | { type: 'chat' }
  | { type: 'new_task' }
  | { type: 'plan_reply' }
  | { type: 'confirm_generate' }
  | { type: 'cancel_work' }
  | { type: 'status_query' }
  | { type: 'inject' }

export interface VoiceRouteContext {
  text: string
  orchPhase: string
  hasPlanSession: boolean
  hasPendingHandoff: boolean
  canRunOrch: boolean
  planSessionPhase?: string
  planIntentKey?: string
  orchestrating: boolean
  composerIntent?: string
  /** 供分类器 payload，非路由判定 */
  pendingHandoff?: boolean
  finalizeLoading?: boolean
  voiceTitle?: string
  checklistLineCount?: number
  lastAssistantSnippet?: string
}

const STATUS_RE = /进度|做到哪|还要多久|怎么样了|完成没|好了吗/
const CANCEL_RE = /取消|停止生成|别做了|不要了|停下/

/** 用户质疑过早执行 → dismiss_plan（分类器 coerce 使用） */
export const VOICE_PUSHBACK_RE =
  /怎么就开始|为何开始|为什么开始|还没确认|不要开始|先别做|别急着|不要乱做|没让你做|谁让你做|太急了|太快了|就开始做|就开始规划|就开始生成/

const VOICE_NON_TASK_RE =
  /^(你好|嗨|在吗|听得到|听得见|试试|测试)|怎么.*(做|规划|生成)|为什么.*(做|规划|生成)|什么.*(做|规划)|你就.*(做|规划|生成)/

const WORK_INTENT_RE =
  /做\s*(个|一个|款|下|点)?|生成|制作|规划|开始任务|帮我做|帮我生成|创建|开发|定制|mod|skill|工作流|组件|插件/i

const EMPLOYEE_EXPLICIT_TASK_RE =
  /帮我(做|创建|生成|规划|设计|定义)|开始(做|生成|规划|制作)|做一个|生成一个|创建.{0,16}员工|设计.{0,16}员工|规划.{0,8}员工|员工职责|员工包|提示词|工具配置|employee_pack|执行清单|生成执行清单|确认任务|开始任务/i

/** 语音里描述员工任务（brief 拼接与 ensureVoiceEmployeeIntent，非口令表） */
export function looksLikeEmployeeTaskDescription(text: string): boolean {
  const t = text.trim()
  if (!t || t.length < 6) return false
  if (EMPLOYEE_EXPLICIT_TASK_RE.test(t)) return true
  return (
    /员工|employee/i.test(t) &&
    /做|创建|生成|提取|负责|需要|word|docx|文档|json|全量/i.test(t)
  )
}

export function isVoiceEmployeeWorkContext(ctx: VoiceRouteContext): boolean {
  return ctx.composerIntent === 'employee' || ctx.planIntentKey === 'employee'
}

/** 过短且无任务语义的 ASR 碎片，不作为规划 brief */
export function isLikelyShortProceedFragment(text: string): boolean {
  const t = text.trim()
  return t.length > 0 && t.length <= 10 && !looksLikeEmployeeTaskDescription(t)
}

export function inferUserGoalFromVoiceMessages(
  messages: Array<{ role: string; content: string }>,
  excludeUtterance?: string,
): string {
  const ex = String(excludeUtterance || '').trim()
  const chunks = messages
    .filter((m) => m.role === 'user')
    .map((m) =>
      String(m.content || '')
        .trim()
        .replace(/^undefined(?=\S)/, '')
        .trim(),
    )
    .filter((t) => t && t !== ex && !isLikelyShortProceedFragment(t) && t.length > 2)
  return chunks.slice(-4).join('；')
}

export function hasEmployeePlanContext(
  state: { userGoal?: string },
  messages: Array<{ role: string; content: string }>,
  excludeUtterance?: string,
): boolean {
  if (String(state.userGoal || '').trim()) return true
  return inferUserGoalFromVoiceMessages(messages, excludeUtterance).length >= 8
}

export function hasVoiceWorkIntent(
  text: string,
  opts?: { composerIntent?: string },
): boolean {
  const t = text.trim()
  if (!t) return false
  if (VOICE_PUSHBACK_RE.test(t) || VOICE_NON_TASK_RE.test(t)) return false
  const intent = String(opts?.composerIntent || '').trim()
  if (intent === 'employee') {
    return EMPLOYEE_EXPLICIT_TASK_RE.test(t) || looksLikeEmployeeTaskDescription(t)
  }
  return WORK_INTENT_RE.test(t)
}

/** 安全快路径：取消、进度、制作中插话、已有 handoff 的确认生成 */
const CHECKLIST_PAUSE_RE = /等一下|先别|暂停|等等/

export function routeVoiceUtterance(ctx: VoiceRouteContext): VoiceRouteAction {
  const t = ctx.text.trim()
  if (!t) return { type: 'chat' }

  if (ctx.planSessionPhase === 'checklist' && CHECKLIST_PAUSE_RE.test(t)) {
    return { type: 'plan_reply' }
  }

  if (VOICE_PUSHBACK_RE.test(t) || VOICE_NON_TASK_RE.test(t)) {
    return { type: 'chat' }
  }

  if (CANCEL_RE.test(t)) return { type: 'cancel_work' }
  if (STATUS_RE.test(t) && (ctx.orchestrating || ctx.hasPendingHandoff || ctx.hasPlanSession)) {
    return { type: 'status_query' }
  }
  if (ctx.hasPendingHandoff && ctx.canRunOrch && /确认生成|开始生成|开始制作/.test(t)) {
    return { type: 'confirm_generate' }
  }
  if (ctx.orchestrating || ctx.orchPhase === 'running' || ctx.orchPhase === 'estimating') {
    return { type: 'inject' }
  }
  if (ctx.hasPlanSession && ctx.planSessionPhase && ctx.planSessionPhase !== 'summary') {
    return { type: 'plan_reply' }
  }
  if (ctx.hasPlanSession && ctx.planSessionPhase === 'summary') {
    return { type: 'plan_reply' }
  }
  if (!ctx.hasPlanSession && !ctx.hasPendingHandoff) {
    return hasVoiceWorkIntent(t, { composerIntent: ctx.composerIntent })
      ? { type: 'new_task' }
      : { type: 'chat' }
  }
  return { type: 'chat' }
}

export function appendVoiceInject(existing: string, text: string): string {
  const base = String(existing || '').trim()
  const line = `【中途补充】${text.trim()}`
  return base ? `${base}\n${line}` : line
}

export function buildOrchestrationStatusSummary(
  steps: Array<{ label?: string; status?: string; message?: string }> | undefined,
): string {
  if (!Array.isArray(steps) || !steps.length) return '当前还没有制作步骤。'
  const running = steps.find((s) => s.status === 'running')
  if (running) {
    return `正在执行：${running.label || running.message || '当前步骤'}。`
  }
  const done = steps.filter((s) => s.status === 'done').length
  const total = steps.length
  if (done >= total) return '所有步骤已完成。'
  const next = steps.find((s) => s.status === 'pending')
  return `已完成 ${done}/${total} 步。${next ? `下一步：${next.label || '待执行'}。` : ''}`
}
