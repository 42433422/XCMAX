import { nextTick } from 'vue'
import { api } from '../../api'
import { ttsConfigFromPersonalSettings } from '../../composables/useStreamingTts'
import { clearVoiceLatencyMarks } from '../../composables/voiceLatency'
import type { VoiceTurnMessage } from '../../composables/voiceUserTurnCoalesce'
import { buildAgentAwarePrompt, pickBestEmployeeBriefFromVoice, formatFilteredPlanMessagesForBrief } from '../../composables/voiceSessionAgent'
import { modelSupportsVisionInput } from '../../utils/visionMultimodal'
import type { useWbRetrieveKnowledgeForDirect } from './useWbRetrieveKnowledgeForDirect'
import type { PendingHandoff, WorkbenchStateRecord } from './types'

// 拆分自 WorkbenchHomeView.vue（原行 3524–3567, 6012–6034, 6901–6950 …）；逐字迁移，行为不变。
export function useWbResolveChatProviderModel(ctx: ReturnType<typeof useWbRetrieveKnowledgeForDirect>) {
  const {
    suggestModIdFromText, router, workbenchErrorMessage, inputRef, pendingHandoff, __wbState,
    CANVAS_SKILL_INTENT, isCanvasSkillIntent, composerIntent, modFrontendEnabled, platformChatMode, voiceHumanChatMode,
    ttsAutoRead, personalSettings, voiceS2s, voiceUnified, voiceUseUnified, voiceUsePhonePipeline,
    activeBot, consumptionTier, voiceMessages, voiceSessionState, voiceError, voiceState,
    voiceChatPhase, voiceWorkPhase, voiceChatBusy, appendVoiceUserTurn, phoneTurnTextDelta, buildHumanChatStylePrompt,
    directEmployeeSystemHint, syncVoiceWorkPhase, llmCatalog, selectedProvider, selectedModel, modelMode,
    INTENT_META, intentMeta, hasRepo, hasWorkflow, hasEmployee, loadLlmCatalogForWorkbench,
    dismissPlanSession,
  } = ctx

async function handlePhonePartialStable(text: string, turnId: string) {
  if (!voiceUsePhonePipeline.value || voiceChatBusy.value) return
  clearVoiceLatencyMarks()
  __wbState.s2sProvisionalTurnId = turnId
  __wbState.s2sProvisionalStarted = true
  voiceChatBusy.value = true
  voiceChatPhase.value = 'streaming'
  voiceState.value = 'processing'
  appendVoiceUserTurn(text)
  __wbState.s2sProvisionalAssistantIdx = voiceMessages.value.length
  voiceMessages.value = [...voiceMessages.value, { role: 'assistant', content: '' }]
  const sys = buildVoiceWorkbenchPrompt()
  const history = voiceMessages.value
    .slice(0, -1)
    .filter((m) => m.content?.trim())
    .map((m) => ({ role: m.role as 'user' | 'assistant', content: m.content }))
  const { provider, model } = await resolveChatProviderModel()
  const ttsCfg = ttsConfigFromPersonalSettings(personalSettings.value)
  const turnOpts = {
    text,
    turnId,
    system: sys,
    messages: history,
    provider,
    model,
    voice: ttsCfg.edgeVoice,
    rate: ttsCfg.rate,
    ttsEnabled: ttsAutoRead.value,
    maxTokens: 1024,
    onTextDelta: phoneTurnTextDelta(__wbState.s2sProvisionalAssistantIdx),
  }
  try {
    if (voiceUseUnified.value) {
      await voiceUnified.runTurnStart(turnOpts)
    } else {
      await voiceS2s.runTurnStart({ ...turnOpts, provisional: true })
    }
  } catch (e: unknown) {
    __wbState.s2sProvisionalStarted = false
    voiceChatBusy.value = false
    voiceChatPhase.value = 'idle'
    voiceError.value = e instanceof Error ? e.message : String(e)
  }
}
async function loadUsableMediaCatalog() {
  if (!llmCatalog.value && localStorage.getItem('modstore_token')) {
    await loadLlmCatalogForWorkbench()
  }
  const catalog = llmCatalog.value
  if (!catalog) return catalog
  try {
    const statusPayload = await api.llmStatus()
    const fernetOk = Boolean(statusPayload?.fernet_configured)
    const rows = Array.isArray(statusPayload?.providers) ? statusPayload.providers : []
    const usableProviders = new Set(
      rows
        .filter((r: WorkbenchStateRecord) => _providerRowHasUsableKey(r, fernetOk))
        .map((r: WorkbenchStateRecord) => String(r.provider || '').trim()),
    )
    const providers = Array.isArray(catalog.providers)
      ? catalog.providers.filter((b) => usableProviders.has(String(b.provider || '').trim()))
      : []
    return { ...catalog, providers }
  } catch {
    return catalog
  }
}
function buildVoiceWorkbenchPrompt(extraHint?: string) {
  if (voiceHumanChatMode.value) {
    const parts = [
      `当前消费档位：${consumptionTier.value}。`,
      '【常态化聊天】当前是移动端聊天页/普通聊天模式：直接回答问题即可，不要引导做 Mod、做员工、Skill 组，不要打开规划或制作流程。',
      buildHumanChatStylePrompt('voice'),
      directEmployeeSystemHint(),
    ]
    if (platformChatMode.value) {
      parts.push(
        '【平台模式 · 工作台语音入口】这是嵌在工作台里的语音入口，不是独立电话式语音 App。用户未关闭平台模式前：只闲聊、接上下文，禁止引导或主动提起制作、规划、Skill 组；用户明确要做 Mod/员工时需提示其先关闭顶部平台模式。',
      )
    }
    const persona = String(activeBot.value?.persona || '').trim()
    if (persona) parts.push(persona)
    if (extraHint) parts.push(extraHint)
    return parts.filter(Boolean).join('\n')
  }
  const intent = composerIntent.value || CANVAS_SKILL_INTENT
  const meta = INTENT_META[intent] || INTENT_META.skill
  const parts = [
    `当前消费档位：${consumptionTier.value}。`,
    `语音工作台模式：用户通过第三档「说」与你对话；左上角已选「${meta.title}」。`,
    '回复要短、口语化，适合朗读；可追问 1-2 个关键问题。',
    '禁止无实质内容的「嗯」「你说」「我在听」式空承接；先理解用户完整表述再回应。',
    buildHumanChatStylePrompt('voice'),
  ]
  if (intent === 'employee') {
    parts.push(
      '【做员工 · 对话优先】你是有自主意识的协作伙伴，不是收到一句话就立刻开工的规划器。',
      '先判断用户是在闲聊、抱怨、澄清、质疑进度，还是已明确下达「要生成/规划员工包」类任务。未明确任务前：只复述理解、追问关键点，不要说「已开始规划」或「会自动打开规划面板」。',
      '若用户质疑「怎么就开始做了」：说明当前并未在执行制作（可能是系统误判），问是否现在要进入需求规划。',
      '仅当用户已确认开始（如「开始规划」「开始写吧」）且系统话语分类将触发 open_plan 时：你可简短说正在整理摘要；禁止在未确认前承诺「会打开规划面板」。',
      buildAgentAwarePrompt(voiceSessionState.value, extraHint),
    )
  } else if (intent === 'mod') {
    parts.push(
      '【做 Mod】先理解用户在描述想法、补充细节还是下达制作任务；未明确前以澄清为主，不要催促进入规划。',
      '规划与清单格式约定（供用户稍后进入规划面板时参考）：',
      buildPlanSystemPrompt(intent, meta.title),
    )
  } else {
    parts.push(buildPlanSystemPrompt(intent, meta.title))
  }
  if (voiceWorkPhase.value === 'orchestrating') {
    parts.push('后台正在制作，用户可能在补充需求或问进度。')
  }
  if (extraHint && intent !== 'employee') parts.push(extraHint)
  return parts.join('\n')
}
function _confirmVoiceAndOpenHandoff() {
  if (!voiceMessages.value.length) return
  const text = formatPlanMessagesForBrief(voiceMessages.value)
  const intentKey = composerIntent.value
  const isEmployee = intentKey === 'employee'
  const routingBrief = isEmployee
    ? (pickBestEmployeeBriefFromVoice(voiceSessionState.value, voiceMessages.value) || text.split('\n')[0] || text).slice(0, 200)
    : ''
  pendingHandoff.value = {
    description: isEmployee
      ? `【初始想法】\n${routingBrief || text}`
      : `【语音规划记录】\n${text}`,
    employeeRoutingBrief: isEmployee ? routingBrief : undefined,
    intentTitle: intentMeta.value.title,
    intentKey,
    workflowName: suggestModIdFromText(text) || '',
    planNotes: isCanvasSkillIntent(intentKey) ? text : '',
    suggestedModId: intentKey === 'mod' ? suggestModIdFromText(text) : '',
    generateFrontend: intentKey === 'mod' ? modFrontendEnabled.value : false,
    employeeTarget: intentKey === 'employee' ? 'pack_only' : 'pack_only',
    employeeWorkflowName: '',
    fhdBaseUrl: '',
    planningMessages: voiceMessages.value.map((m) => ({ role: m.role, content: m.content })),
  }
  syncVoiceWorkPhase()
}
function _applyStarter(kind: string): void {
  if (hasWorkflow.value) {
    if (!INTENT_META[kind]) return
    dismissPlanSession()
    composerIntent.value = kind
    nextTick(() => {
      const el = inputRef.value
      if (el && typeof el.focus === 'function') el.focus()
    })
    return
  }
  const fallback = ({
    mod: hasRepo.value ? 'workbench-repository' : null,
    employee: hasEmployee.value ? 'workbench-employee' : null,
    skill: hasWorkflow.value ? 'workbench-workflow' : null,
    workflow: hasWorkflow.value ? 'workbench-workflow' : null,
  } as Record<string, string | null>)[kind]
  if (fallback && router.hasRoute(fallback)) {
    router.push({ name: fallback })
  }
}
function buildPlanSystemPrompt(intentKey: string, intentTitle: string): string {
  const typeHint =
    isCanvasSkillIntent(intentKey)
      ? '区分两类产物：（1）Skill 组合工作流＝先把需求拆成可复用 ESkill/Skill，再把这些 Skill 组合成画布工作流；（2）脚本工作流＝可运行程序、直接完成任务。规划时若用户要「程序本体」，引导其需求规划结束后去「脚本工作流」新建；此处必须先识别业务能力边界，拆出多个 Skill，说明每个 Skill 的输入、输出、质量门和触发策略，再描述 Skill 之间的顺序、条件与失败重试。流程图用 flowchart LR 或 TD；节点 id 仅用英文字母；子图写 subgraph sg1["中文标题"]，结束用单独一行 end（禁止 endsubgraph）；含冒号/括号的中文标签必须加双引号。'
      : intentKey === 'mod'
        ? [
            '用户目标可能有两档：（1）Mod 草稿骨架：仓库、manifest、行业 JSON、workflow_employees 名片；（2）可执行员工：在骨架基础上生成/登记 employee_pack，绑定 workflow_id，让工作流 employee 节点使用可执行包 id，并完成非 Mock 真实执行验证。',
            '【宿主软件 FHD / XCAGI 已定型，禁止「技术栈问卷」】宿主主程序为 Vue 3 + Vite + Element Plus（FHD/frontend）；本 Mod 前端作为专业版切换（侧栏 proModeToggle 等入口）后的「第二套前端」，挂在现有 /mods/<id>/frontend 路由体系，UI 语汇与宿主一致，不要引导用户再选「Node/Python/Go 员工包语言」「REST/RPC」「Element Plus / Ant Design / Vant」等通用栈。',
            '宿主与平台服务侧为 Python + FastAPI 等，不要提议用 Express/Gin 替换宿主 API。澄清时围绕：行业与场景、仓库与数据、员工职责与工具、工作流绑定、外部系统（微信/电话/合同等）、合规与脱敏、是否需要额外宿主路由/页面；不要把这些写成「选语言/选框架」的多选题。',
            'Mermaid 须用 flowchart 画出「建仓库 → 员工名片 → 员工包登记 → 工作流绑定 → 真实验证」的主线，节点名两到六字中文，不用括号。',
            '<<<PLAN_OPTIONS>>>：若需要点选澄清，只能出与业务/交付相关的题；若当前轮没有合适的二选一/多选一，必须输出 []。严禁出现「后端语言」「前端 UI 框架」「API 风格 REST/RPC」类标题或选项。',
          ].join(' ')
        : '关注员工角色、可用工具/能力标识、输入输出与行业场景。Mermaid 用 flowchart 表示角色、工具、输出关系即可。节点 id 仅用英文字母 A/B/C…；子图写 subgraph sg1["中文标题"]，结束用单独一行 end（禁止 endsubgraph）；含冒号/括号的中文标签必须加双引号。'
  const diagramParity =
    intentKey === 'mod'
      ? '【与做员工对齐】每条回复的流程图要求与「做员工」完全相同：不得以「暂无图」「略」或纯文字代替拓扑；必须在 fenced Mermaid 中给出 flowchart。信息不足时仍输出极简示例，例如：flowchart LR 建仓库 --> 写JSON骨架 --> 员工命名。'
      : intentKey === 'employee'
        ? '【流程图】每条回复须含 fenced Mermaid flowchart，不得以纯文字代替；信息不足时用 3～5 个短中文节点概括角色与产出。'
        : ''
  return [
    `你是 XCAGI 工作台的「需求规划」助手。用户当前制作类型：「${intentTitle}」。`,
    `${typeHint}`,
    ...(diagramParity ? [diagramParity] : []),
    '流程：先根据用户的初步想法提出 2～4 个高价值澄清问题（用数字编号列出）；用户补充后，可继续追问直到需求足够具体。',
    '不要生成最终代码、manifest JSON 或工作流节点配置；不要代替用户直接写执行清单（清单由用户点击「生成执行清单」触发）。',
    '用语简洁，中文。',
    '',
    '【输出格式必须严格遵守，便于界面展示】',
    '1) 回复开头必须先输出且仅输出一段 fenced Mermaid（主视图流程草图），例如：',
    '```mermaid',
    'flowchart LR',
    '  A[开始] --> B[步骤]',
    '  B --> C[结束]',
    '```',
    '2) 紧接着输出澄清与说明文字，且必须用以下标记包裹（界面默认折叠在「详细」中）：',
    '<<<PLAN_DETAILS>>>',
    '（此处写编号问题与补充，可多段）',
    '<<<END_PLAN_DETAILS>>>',
    '3) 再输出快捷选项：单行 JSON 数组，用以下标记包裹（供界面点选；不需要选项时输出 []）：',
    '<<<PLAN_OPTIONS>>>',
    intentKey === 'mod'
      ? '[{"id":"q_scope","title":"交付档位","choices":[{"id":"skeleton","label":"先骨架（manifest/行业 JSON/名片）"},{"id":"full","label":"骨架 + 可执行员工包 + 工作流绑定"}]}]'
      : '[{"id":"q1","title":"短标题","choices":[{"id":"c1","label":"选项甲"},{"id":"c2","label":"选项乙"}]}]',
    '<<<END_PLAN_OPTIONS>>>',
    'JSON 须为单行；每项含 id、title、choices（2～5 项，每项 id 与 label）；label 内勿用英文双引号。',
    '除上述各段外不要输出其它前言或后记。',
  ].join('\n')
}
/** 仅用于「生成执行清单」单次请求：不得沿用对话里的 Mermaid/PLAN_* 格式，否则模型会拒写 <<<CHECKLIST>>> */
function buildChecklistGenerationSystemPrompt(intentKey: string, intentTitle: string): string {
  const scope =
    isCanvasSkillIntent(intentKey)
      ? '每条任务应可执行、可验证。若用户要「程序本体」，清单中应出现脚本工作流（编写/运行/沙箱）相关条目；否则必须围绕 Skill 生成闭环：拆分 Skill 蓝图、定义每个 Skill 的输入输出契约、静态逻辑、质量门、动态触发策略、固化策略、Skill 间数据映射、组合工作流与沙盒校验。普通画布节点只作为 start/end/condition 等控制节点。'
      : intentKey === 'mod'
        ? '每条任务应可落到 Mod 仓库与真实可用闭环：仓库、manifest、行业 JSON、员工名片、employee_pack 登记、workflow_id 绑定、employee 节点 id 匹配、Mock 结构沙盒与非 Mock 真实执行验证。若用户只要草稿骨架，也必须在清单中标明后续成为可执行员工还缺哪些步骤。'
        : '每条任务应可落到员工能力、工具配置与交付物。'
  return [
    `你是 XCAGI 工作台的「执行清单」生成助手。当前制作类型：「${intentTitle}」。`,
    `${scope}`,
    '用户与助手的前文是对话历史；你的**整段回复只允许**输出下面这一块，不要写任何其它字符（不要写「好的」、不要写 mermaid、不要写 <<<PLAN_DETAILS>>>、不要写 <<<PLAN_OPTIONS>>>、不要用 ``` 代码围栏）。',
    '',
    '【必须严格按行输出】',
    '<<<CHECKLIST>>>',
    '1. …',
    '2. …',
    '<<<END>>>',
    '',
    '至少 4 条、建议 6～12 条；中文短句；行首编号必须为「数字 + 英文句点 + 空格」。',
  ].join('\n')
}
function formatPlanMessagesForBrief(msgs: VoiceTurnMessage[]): string {
  if (!Array.isArray(msgs) || !msgs.length) return ''
  const topicHint = msgs.map((m: VoiceTurnMessage) => m.content).join(' ')
  return formatFilteredPlanMessagesForBrief(msgs, topicHint)
}
/** 编排前净化员工 handoff brief，去掉 ASR 噪声与占位符 */
function enrichEmployeeHandoffBeforeOrchestration(h: PendingHandoff): void {
  if (!h || h.intentKey !== 'employee') return
  const msgs = Array.isArray(h.planningMessages) && h.planningMessages.length
    ? h.planningMessages
    : voiceMessages.value
  const best = pickBestEmployeeBriefFromVoice(voiceSessionState.value, msgs)
  const topicHint = [best, h.description, ...msgs.map((m: VoiceTurnMessage) => m.content)].join(' ')
  const qaText = formatFilteredPlanMessagesForBrief(msgs, topicHint)
  const initialFromDesc = String(h.description || '').split('【澄清对话】')[0].replace('【初始想法】', '').trim()
  const initial = best || initialFromDesc || String(h.description || '').trim()
  h.employeeRoutingBrief = initial.slice(0, 200)
  const descChunks = [`【初始想法】\n${initial}`]
  if (qaText) descChunks.push(`【澄清对话】\n${qaText}`)
  const checklistMatch = String(h.description || '').match(/【执行清单】\s*([\s\S]*)$/)
  if (checklistMatch?.[1]?.trim()) {
    descChunks.push(`【执行清单】\n${checklistMatch[1].trim()}`)
  } else if (Array.isArray(h.executionChecklist) && h.executionChecklist.length) {
    descChunks.push(
      `【执行清单】\n${h.executionChecklist.map((line: unknown, index: number) => `${index + 1}. ${line}`).join('\n')}`,
    )
  }
  h.planningContext = descChunks.join('\n\n---\n\n')
  h.description = h.planningContext
}
/** 规划面板：把 nginx 504 HTML 等转成可读中文，避免整页 HTML 贴在 planError 里 */
function friendlyPlanPanelApiError(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err || '')
  const s = raw.trim()
  if (!s) return '请求失败，请稍后重试。'
  if (/504|Gateway Time-out|网关超时/i.test(s) || /<title>\s*504/i.test(s)) {
    return '网关超时（504）：最前面的 nginx 在超时时间内没等到后端返回就断开了连接。需求规划调用模型往往较慢，请在对外提供站点的那台 nginx 里为 /api/ 增大 proxy_read_timeout、proxy_send_timeout（建议 3600s），nginx -t 后 reload；若直连本机 API 正常而域名访问 504，说明问题在这一层反代。仓库示例见 market/nginx.conf、docs/nginx-https-example.conf。'
  }
  if (/<\s*html[\s>]/i.test(s)) {
    return '服务器返回了 HTML 错误页（多为反代或网关层），请在浏览器网络面板查看该请求的 HTTP 状态码，并检查 nginx 与 modstore 服务日志。'
  }
  return s.length > 900 ? `${s.slice(0, 900)}…` : s
}
function _checklistBodyToResult(body: unknown): { text: string; lines: string[] } | null {
  const lines = String(body || '')
    .split(/\r?\n/)
    .map((line: string) => line.replace(/^\s*\d+[.)]\s*/, '').trim())
    .filter((line: string) => line && !/^<<<[\s\S]*>>>$/.test(line))
  if (!lines.length) return null
  const text = lines.map((line: string, index: number) => `${index + 1}. ${line}`).join('\n')
  return { text, lines }
}
/** 模型漏写结束标签时：取文末连续「数字. 」行作为清单（仅当正文含 <<<CHECKLIST>>> 时由上层调用） */
function parseChecklistNumberedTail(raw: unknown): { text: string; lines: string[] } | null {
  const lines = String(raw || '')
    .split(/\r?\n/)
    .map((line: string) => line.trim())
    .filter(Boolean)
  while (lines.length && /^```/.test(lines[lines.length - 1])) {
    lines.pop()
  }
  const collected: string[] = []
  for (let i = lines.length - 1; i >= 0; i -= 1) {
    const l = lines[i]
    if (/^\d+[.)]\s+\S/.test(l)) {
      collected.unshift(l.replace(/^\d+[.)]\s+/, '').trim())
    } else if (collected.length) {
      break
    }
  }
  if (collected.length < 2) return null
  return _checklistBodyToResult(collected.join('\n'))
}
function parseChecklistBlock(raw: unknown): { text: string; lines: string[] } | null {
  let s = String(raw || '').trim()
  const fullFence = s.match(/^```(?:\w*)?\s*\n([\s\S]*?)\n```\s*$/m)
  if (fullFence) s = fullFence[1].trim()
  const mer = s.match(/```mermaid\s*[\s\S]*?```/i)
  if (mer) s = s.replace(mer[0], '')
  const pd = s.match(/<<<PLAN_DETAILS>>>([\s\S]*?)<<<END_PLAN_DETAILS>>>/i)
  if (pd) s = s.replace(pd[0], '')
  const po = s.match(/<<<PLAN_OPTIONS>>>([\s\S]*?)<<<END_PLAN_OPTIONS>>>/i)
  if (po) s = s.replace(po[0], '')
  s = s.replace(/<<<\s*CHECKLIST\s*>>>/gi, '<<<CHECKLIST>>>')
  s = s.replace(/<<<\s*END\s*CHECKLIST\s*>>>/gi, '<<<END>>>')
  s = s.replace(/<<<\s*END_CHECKLIST\s*>>>/gi, '<<<END>>>')
  s = s.replace(/<<<\s*END\s*>>>/gi, '<<<END>>>')
  const tryBodies: string[] = []
  let m = s.match(/<<<CHECKLIST>>>([\s\S]*?)<<<END>>>/i)
  if (m) tryBodies.push(m[1])
  if (!tryBodies.length) {
    m = s.match(/<<<CHECKLIST>>>([\s\S]*?)$/im)
    if (m) tryBodies.push(m[1])
  }
  for (const body of tryBodies) {
    const r = _checklistBodyToResult(body)
    if (r) return r
  }
  if (/<<<CHECKLIST>>>/i.test(s)) {
    const t = parseChecklistNumberedTail(s)
    if (t) return t
  }
  return null
}
function _providerRowHasUsableKey(row: WorkbenchStateRecord | null | undefined, fernetOk: boolean): boolean {
  if (!row) return false
  if (row.provider === 'xiaomi' && row.has_platform_key) return true
  if (row.has_user_override && fernetOk) return true
  return false
}
const RESOLVE_CHAT_CACHE_MS = 5 * 60 * 1000
function pickVisionModelFromBlock(block: WorkbenchStateRecord | null | undefined): string {
  if (!block) return ''
  const detailed = Array.isArray(block.models_detailed) ? block.models_detailed : []
  const byCategory = detailed.find((m: WorkbenchStateRecord) => m?.category === 'vlm' && String(m?.id || '').trim())
  if (byCategory) return String(byCategory.id).trim()
  const ids = Array.isArray(block.models)
    ? block.models
    : detailed.map((m: WorkbenchStateRecord) => m?.id).filter(Boolean)
  const byHint = ids.find((id: unknown) =>
    modelSupportsVisionInput(String(block.provider || ''), String(id || ''), llmCatalog.value),
  )
  return byHint ? String(byHint).trim() : ''
}
async function pickUsableVisionProviderModel() {
  if (!llmCatalog.value && localStorage.getItem('modstore_token')) {
    await loadLlmCatalogForWorkbench()
  }
  let statusPayload
  try {
    statusPayload = await api.llmStatus()
  } catch {
    statusPayload = null
  }
  const fernetOk = Boolean(statusPayload?.fernet_configured)
  const rows = Array.isArray(statusPayload?.providers) ? statusPayload.providers : []
  const usableProviders = new Set(
    rows
      .filter((r: WorkbenchStateRecord) => _providerRowHasUsableKey(r, fernetOk))
      .map((r: WorkbenchStateRecord) => String(r.provider || '').trim()),
  )
  const providers: WorkbenchStateRecord[] = Array.isArray(llmCatalog.value?.providers)
    ? llmCatalog.value.providers
    : []
  const pref = llmCatalog.value?.preferences || {}
  const prefP = typeof pref.provider === 'string' ? pref.provider.trim() : ''
  const ordered = [
    ...providers.filter((block: WorkbenchStateRecord) => block.provider === prefP),
    ...providers.filter((block: WorkbenchStateRecord) => block.provider !== prefP),
  ]
  for (const block of ordered) {
    const provider = String(block?.provider || '').trim()
    if (!provider || !usableProviders.has(provider)) continue
    const model = pickVisionModelFromBlock(block)
    if (model) return { provider, model }
  }
  if (!fernetOk && rows.some((r: WorkbenchStateRecord) => r.has_user_override)) {
    throw new Error('已保存 BYOK，但服务端未配置 MODSTORE_LLM_MASTER_KEY，无法解密使用视觉模型。')
  }
  throw new Error('当前未配置支持识图的视觉模型。请在「资金与记录 → 大模型 API」配置 VLM/多模态模型，或切到「自选」选择支持图片输入的模型。')
}
/**
 * Auto 模式：优先请求服务端 /resolve-chat-default（与 /chat 共用 resolve_api_key），
 * 避免前端 /status + 目录推断与后端不一致；失败时再回退到本地推断。
 */
async function resolveChatProviderModel(opts: { needVision?: boolean } = {}) {
  const needVision = Boolean(opts.needVision)
  if (needVision && !llmCatalog.value && localStorage.getItem('modstore_token')) {
    await loadLlmCatalogForWorkbench()
  }
  if (modelMode.value === 'manual') {
    __wbState.resolveChatCache = null
    if (!selectedProvider.value || !selectedModel.value) {
      throw new Error('自选模式下请选择厂商与模型')
    }
    if (needVision && !modelSupportsVisionInput(selectedProvider.value, selectedModel.value, llmCatalog.value)) {
      throw new Error('当前自选模型不支持图片输入。请切换到支持识图的 VLM/多模态模型后重试。')
    }
    return { provider: selectedProvider.value, model: selectedModel.value }
  }
  const modeKey = needVision ? 'auto:vision' : 'auto'
  if (
    __wbState.resolveChatCache &&
    __wbState.resolveChatCache.mode === modeKey &&
    Date.now() - __wbState.resolveChatCache.at < RESOLVE_CHAT_CACHE_MS
  ) {
    if (!needVision || modelSupportsVisionInput(__wbState.resolveChatCache.provider, __wbState.resolveChatCache.model, llmCatalog.value)) {
      return { provider: __wbState.resolveChatCache.provider, model: __wbState.resolveChatCache.model }
    }
  }
  if (localStorage.getItem('modstore_token')) {
    try {
      const resolved = await api.llmResolveChatDefault()
      const rp = typeof resolved?.provider === 'string' ? resolved.provider.trim() : ''
      const rm = typeof resolved?.model === 'string' ? resolved.model.trim() : ''
      if (rp && rm) {
        if (!needVision || modelSupportsVisionInput(rp, rm, llmCatalog.value)) {
          __wbState.resolveChatCache = { at: Date.now(), mode: modeKey, provider: rp, model: rm }
          return { provider: rp, model: rm }
        }
      }
    } catch (e: unknown) {
      const msg = workbenchErrorMessage(e)
      if (/404|Not Found/i.test(msg)) {
        /* 旧服务端无此路由时回退到下方本地推断 */
      } else {
        throw e
      }
    }
  }
  if (needVision) {
    const picked = await pickUsableVisionProviderModel()
    __wbState.resolveChatCache = { at: Date.now(), mode: modeKey, provider: picked.provider, model: picked.model }
    return picked
  }
  if (!llmCatalog.value && localStorage.getItem('modstore_token')) {
    await loadLlmCatalogForWorkbench()
  }
  const pref = llmCatalog.value?.preferences || {}
  let p = typeof pref.provider === 'string' ? pref.provider.trim() : ''
  let m = typeof pref.model === 'string' ? pref.model.trim() : ''
  if (!p || !m) {
    throw new Error('请先在 LLM 设置中选择默认模型，或切换到「自选」')
  }

  let statusPayload
  try {
    statusPayload = await api.llmStatus()
  } catch {
    statusPayload = null
  }
  const fernetOk = Boolean(statusPayload?.fernet_configured)
  const rows = Array.isArray(statusPayload?.providers) ? statusPayload.providers : []
  const rowP = rows.find((row: WorkbenchStateRecord) => row.provider === p)

  if (!_providerRowHasUsableKey(rowP, fernetOk)) {
    const withModels = rows.filter((row: WorkbenchStateRecord) => {
      if (!_providerRowHasUsableKey(row, fernetOk)) return false
      const b = llmCatalog.value?.providers?.find((item: WorkbenchStateRecord) => item.provider === row.provider)
      return b && Array.isArray(b.models) && b.models.length
    })
    const fallback = withModels[0] || rows.find((row: WorkbenchStateRecord) => _providerRowHasUsableKey(row, fernetOk))
    if (!fallback) {
      if (!fernetOk && rows.some((row: WorkbenchStateRecord) => row.has_user_override)) {
        throw new Error(
          '已保存 BYOK，但服务端未配置 MODSTORE_LLM_MASTER_KEY，无法解密使用。请在部署环境设置主密钥，或改用平台环境变量密钥。',
        )
      }
      throw new Error(
        `当前默认厂商「${p}」没有可用的平台或 BYOK 密钥。请在钱包页 LLM 中为该厂商配置密钥，或切换到「自选」选择已有密钥的厂商与模型。`,
      )
    }
    const newP = fallback.provider
    const block = llmCatalog.value?.providers?.find((item: WorkbenchStateRecord) => item.provider === newP)
    const models = block?.models
    const newM = Array.isArray(models) && models.length ? models[0] : ''
    if (!newM) {
      throw new Error(
        `检测到 ${newP} 具备密钥，但模型列表不可用。请刷新页面或到钱包页确认该厂商模型目录已加载，再试需求规划。`,
      )
    }
    p = newP
    m = newM
  }

  __wbState.resolveChatCache = { at: Date.now(), mode: modeKey, provider: p, model: m }
  return { provider: p, model: m }
}

  return {
    ...ctx, handlePhonePartialStable, loadUsableMediaCatalog, buildVoiceWorkbenchPrompt, _confirmVoiceAndOpenHandoff,
    _applyStarter, buildPlanSystemPrompt, buildChecklistGenerationSystemPrompt, formatPlanMessagesForBrief, enrichEmployeeHandoffBeforeOrchestration,
    friendlyPlanPanelApiError, _checklistBodyToResult, parseChecklistNumberedTail, parseChecklistBlock, _providerRowHasUsableKey,
    RESOLVE_CHAT_CACHE_MS, pickVisionModelFromBlock, pickUsableVisionProviderModel, resolveChatProviderModel,
  }
}

export type useWbResolveChatProviderModelBinds = ReturnType<typeof useWbResolveChatProviderModel>
