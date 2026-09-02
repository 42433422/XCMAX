import { ref, computed, reactive, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { readPlatformChatModePreference, writePlatformChatModePreference } from '../../utils/workbenchPlatformChatMode'
import type { SixDimensionReport } from '../../types/sixDimension'
import type { AgentBot } from '../../utils/agentBots'
import type { PersonalSettings as PersonalSettingsValue } from '../../utils/personalSettings'
import { defaultPersonalSettings, loadPersonalSettings, savePersonalSettings, applyThemeToDocument } from '../../utils/personalSettings'
import type { ChatMessage, Conversation } from '../../utils/conversationStore'
import { summarizeForTitle } from '../../utils/conversationStore'
import type { StreamHandle } from '../../utils/llmStream'
import { useWorkbenchSidebarStore } from '../../stores/workbenchSidebar'
import { useWorkbenchNavStore } from '../../stores/workbenchNav'
import { useStreamingTts, ttsConfigFromPersonalSettings } from '../../composables/useStreamingTts'
import { useVoiceS2SSession } from '../../composables/useVoiceS2SSession'
import { useVoiceUnifiedSession, createUnifiedAsrBridge } from '../../composables/useVoiceUnifiedSession'
import type { VoiceSessionState } from '../../composables/voiceSessionAgent'
import { stripInternalMarkers } from '../../utils/lightMarkdown'
import type { DirectGeneratedFile } from '../../utils/directGeneratedFiles'
import { planComposerAttachmentStrip, planHeaderGeneratedStrip } from '../../utils/workbenchFileStripPlan'
import { useButlerWorkbenchTrayStore } from '../../stores/butlerWorkbenchTray'
import { useButlerDownloadHistoryStore } from '../../stores/butlerDownloadHistory'
import { useAgentStore } from '../../stores/agent'
import type { DirectAttachment, DirectEmployeeOption, DirectGeneratingFileState, PendingHandoff, PlanSession, WorkbenchCompletionResult, WorkbenchOrchestrationSession, WorkbenchStateRecord, WorkflowLinkOffer } from './types'

// 拆分自 WorkbenchHomeView.vue（原行 2130–2148, 2151–2151, 2153–2153 …）；逐字迁移，行为不变。
export function useWbSuggestModIdFromText() {
/** 从需求正文猜一个 Mod ID（与后端 normalize_mod_id 规则对齐，可全中文时回退为 mod-<时间戳>） */
function suggestModIdFromText(raw: string): string {
  const normalize = (x: string) =>
    x
      .toLowerCase()
      .replace(/[^a-z0-9._-]+/g, '-')
      .replace(/-+/g, '-')
      .replace(/^-+|-+$/g, '')
  let t = normalize(String(raw || ''))
  if (!t || !/^[a-z0-9]/.test(t)) {
    t = `mod-${Date.now().toString(36)}`
  }
  if (t.length > 48) {
    t = normalize(t.slice(0, 48))
  }
  if (!/^[a-z0-9][a-z0-9._-]*$/.test(t)) {
    t = `mod-${Date.now().toString(36)}`
  }
  return t
}
/** 与后端 llm_model_taxonomy.CATEGORY_ORDER 一致 */
const LLM_CATEGORY_ORDER = ['llm', 'vlm', 'image', 'video', 'other']
const router = useRouter()
const route = useRoute()
const wbSidebar = useWorkbenchSidebarStore()
const wbNav = useWorkbenchNavStore()
const draft = ref('')
const displayName = ref('')
function workbenchErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
function workbenchHttpStatus(error: unknown): number {
  if (!error || typeof error !== 'object') return 0
  const status = (error as { status?: unknown }).status
  return typeof status === 'number' ? status : 0
}
const inputRef = ref<HTMLInputElement | HTMLTextAreaElement | null>(null)
const handoffPanelRef = ref<HTMLElement | null>(null)
/** 发送后暂存在页顶；补全并创建成功后才跳转画布 */
const pendingHandoff = ref<PendingHandoff | null>(null)
const makeCompletionResult = ref<WorkbenchCompletionResult | null>(null)
const employeeSixDimModalOpen = ref(false)
const employeeSixDimReport = ref<SixDimensionReport | null>(null)
const makeCompletionRef = ref<HTMLElement | null>(null)
const finalizeLoading = ref(false)
const finalizeError = ref('')
/** 编排轮询中的会话快照（含 steps） */
const orchestrationSession = ref<WorkbenchOrchestrationSession | null>(null)
const orchestrationSessionId = ref('')
const pollStop = ref(false)
/** 编排：估算耗时阶段 → 正式执行（估算结束后才开始「已用」计时） */
const orchPhase = ref('idle')
const orchestrationEtaSeconds = ref<number | null>(null)
const orchestrationEtaReason = ref('')
// ---- 统一可变状态：原顶层 let 收拢为单一 const 对象（属性读写 ≡ 原变量读写，闭包语义不变） ----
const __wbState = {
  orchElapsedTimer: (null) as ReturnType<typeof setInterval> | null,
  planLoadingIntervalId: (null) as ReturnType<typeof setInterval> | number | null,
  inlineVoicePrefix: '',
  inlineVoiceTarget: (null) as 'direct' | 'make' | 'voice' | null,
  inlineHoldActive: false,
  inlineHoldPointerId: -1,
  inlineHoldCancelIntent: false,
  inlineHoldStartY: 0,
  currentStreamHandle: (null) as StreamHandle | null,
  ttsStreamAssistantId: '',
  s2sProvisionalTurnId: '',
  s2sProvisionalStarted: false,
  s2sProvisionalAssistantIdx: -1,
  voiceStreamHandle: (null) as StreamHandle | null,
  voiceUtteranceQueue: ([]) as string[],
  voiceUtteranceDraining: false,
  waveRafId: 0,
  directWaveRafId: 0,
  syncingConvToSidebar: false,
  lastAppliedCustomerServiceQueryKey: '',
  planSummaryStreamHandle: (null) as StreamHandle | null,
  voiceBtnLongPressTimer: (null) as ReturnType<typeof setTimeout> | null,
  voiceBtnLongPressFired: false,
  planDiagramPreviewEscUnlisten: (null) as (() => void) | null,
  planDiagramPreviewPointerCleanup: (null) as (() => void) | null,
  mermaidApi: (null) as (typeof import('mermaid'))['default'] | null,
  mermaidInitDone: false,
  resolveChatCache: (null) as { at: number; mode: string; provider: string; model: string } | null,
}
const orchTimingStartMs = ref<number | null>(null)
/** 每 500ms 递增，驱动已用时间的 computed 刷新 */
const orchElapsedTick = ref(0)
/** 工作流编排成功后的「关联 Mod」卡片 */
const workflowLinkOffer = ref<WorkflowLinkOffer | null>(null)
const linkMods = ref<WorkbenchStateRecord[]>([])
const linkModId = ref('')
const linkBusy = ref(false)
const linkError = ref('')
/** 需求规划：多轮澄清 → 执行清单 → 再进入制作草稿 */
const planSession = ref<PlanSession | null>(null)
const planReplyDraft = ref('')
/** 「AI 自主全部进行」：从 summary 一路串到 runOrchestration 结束的互斥锁 */
const autoPilotRunning = ref(false)
const autoPilotError = ref('')
/** 用户 pause_checklist 后跳过清单自动开跑 */
const voiceChecklistPaused = ref(false)
/** 快捷选项：题目 id -> 选中的 choice id（含 UI 专用「其他」） */
const planOptionSelections = ref<Record<string, string>>({})
/** 「其他」在提交与 canSend 中使用的保留 choice id（勿与模型返回的 id 重复） */
const PLAN_OPTION_OTHER_ID = '__plan_ui_other__'
/** 题目 id -> 「其他」时的自定义文案 */
const planOptionOtherText = reactive<Record<string, string>>({})
function clearPlanOptionOtherText() {
  for (const k of Object.keys(planOptionOtherText)) {
    delete planOptionOtherText[k]
  }
}
const planPanelRef = ref<HTMLElement | null>(null)
/** 每次打开规划会话递增，用于 Transition 内层 :key 触发动画 */
const planSurfaceKey = ref(0)
const MAKE_PROGRESS_CACHE_KEY = 'workbench_home_make_progress_v1'
const MAKE_PROGRESS_CACHE_TTL_MS = 24 * 60 * 60 * 1000
/** 需求规划加载区：分步提示（定时推进当前步，减少「卡住」感） */
const planLoadingStepsSummary = Object.freeze([
  '校验登录与默认模型',
  '读取任务描述与上传材料',
  '请求模型生成摘要（较慢时可能需数十秒）',
  '写入确认卡片',
])
const planLoadingStepsChat = Object.freeze([
  '校验登录与默认模型',
  '整理本轮对话与隐藏上下文',
  '发起模型上游请求',
  '等待模型输出（长任务可能需数十秒）',
  '解析流程图与快捷选项格式',
  '写入本条助手回复',
])
const planLoadingAdvance = ref(0)
const planLoadingStepLabelsForUi = computed(() => {
  if (!planSession.value?.loading) return []
  return planSession.value.phase === 'summary' ? planLoadingStepsSummary : planLoadingStepsChat
})
const planLoadingProgressPercent = computed(() => {
  const list = planLoadingStepLabelsForUi.value
  if (!list.length) return 0
  const max = Math.max(1, list.length - 1)
  return Math.round((planLoadingAdvance.value / max) * 100)
})
const knowledgeStatus = ref<WorkbenchStateRecord | null>(null)
const knowledgeDocs = ref<WorkbenchStateRecord[]>([])
const knowledgeLoading = ref(false)
const knowledgeUploading = ref(false)
const knowledgeError = ref('')
const knowledgeFileInputRef = ref<HTMLInputElement | null>(null)
const knowledgeDragActive = ref(false)
/** 调 /api/knowledge/search 之前的预检：未配置 Embedding Key 时直接跳过 RAG，
 *  避免一档对话 / 二档制作发送时连带产生 503 与「未配置可用 Embedding Key」横幅，
 *  这条横幅原本只是提示性的，但放在 catch 里会让用户误以为业务流程失败。 */
function isEmbeddingConfigured(): boolean {
  return Boolean(knowledgeStatus.value?.embedding?.configured)
}
/** 与下方 starter 同步：仅标记制作类型，不写入输入框（画布 Skill 组 intent 为 `skill`） */
const CANVAS_SKILL_INTENT = 'skill'
function isCanvasSkillIntent(k: string | undefined | null): boolean {
  return k === CANVAS_SKILL_INTENT || k === 'workflow'
}
const composerIntent = ref(CANVAS_SKILL_INTENT)
const modFrontendEnabled = ref(true)
const activeGear = ref('make')
/** 侧栏「聊」：纯文字对话 */
const showDirectChatSurface = computed(() => wbSidebar.activeMode === 'direct')
/** 「做」+ 平台模式：内嵌对话区（不复用「聊」空态卡片，标题/引导不同） */
const showMakePlatformCasualChat = computed(
  () => wbSidebar.activeMode === 'make' && platformChatMode.value,
)
/** 任一档位展示 direct 消息流（聊 或 做·平台） */
const showDirectStyleConversation = computed(
  () => showDirectChatSurface.value || showMakePlatformCasualChat.value,
)
const platformChatMode = ref(readPlatformChatModePreference())
/** 「说」里退出做员工/Skill 后：仅常态化闲聊，勿因历史消息再进员工规划 */
const voiceCasualChatMode = ref(false)
const voiceHumanChatMode = computed(
  () =>
    platformChatMode.value ||
    voiceCasualChatMode.value ||
    (
      wbSidebar.activeMode === 'voice' &&
      !planSession.value &&
      !pendingHandoff.value &&
      !finalizeLoading.value &&
      !orchestrationSessionId.value &&
      orchPhase.value === 'idle'
    ),
)
function voiceSessionModeForIntent(intent: string): VoiceSessionState['mode'] {
  if (intent === 'employee') return 'employee'
  if (intent === 'mod') return 'mod'
  return 'skill'
}
function persistPlatformChatMode(on: boolean) {
  platformChatMode.value = on
  writePlatformChatModePreference(on)
}
const directDraft = ref('')
const directPlaceholder = computed(() => {
  if (wbSidebar.activeMode === 'make') return '描述需求…'
  return '输入问题…'
})
const directFileInputRef = ref<HTMLInputElement | null>(null)
/**
 * 直接聊天待发送的本地附件。每项形如：
 *   { id, name, size, status: 'uploading'|'ready'|'error'|'skipped', docId, error, file }
 * - status='ready' 的文档已上传到当前用户知识库（doc_id），发送时会做向量检索并拼到 system prompt。
 * - status='skipped'/'error' 的文件不上传，只在消息中附带文件名说明。
 */
const directAttachedFiles = ref<DirectAttachment[]>([])
const directGeneratedFiles = ref<DirectGeneratedFile[]>([])
/** 按会话缓存读取员工 raw 结果，供追问「做动画」时生成员复用（附件发送后已从输入区移除）。 */
const officeReadCacheByConversation = new Map<
  string,
  Array<{ name: string; employeeId: string; result: unknown }>
>()
const directGeneratingFile = ref<DirectGeneratingFileState | null>(null)
const directGeneratingFormatLabel = computed(() => {
  const fmt = directGeneratingFile.value?.format
  if (!fmt) return 'FILE'
  switch (fmt) {
    case 'excel':
      return 'Excel'
    case 'pdf':
      return 'PDF'
    case 'csv':
      return 'CSV'
    case 'ppt':
      return 'PPT'
    default:
      return 'Word'
  }
})
/** 顶栏仅展示已生成/生成中，与底部「待发送附件」隔离 */
const showDirectHomeFileStrip = computed(
  () =>
    showDirectStyleConversation.value &&
    (directGeneratedFiles.value.length > 0 || Boolean(directGeneratingFile.value?.active)),
)
const directLoading = ref(false)
/** 已 append 气泡、尚未进入 runDirectChatTurn 的短暂窗口 */
const directSendPending = ref(false)
const directError = ref('')
const directVoiceListening = ref(false)
const directVoiceAudioLevel = ref(0)
const directWaveformCanvas = ref<HTMLCanvasElement | null>(null)
const ttsAutoRead = ref(true)
const currentThemeIsLight = ref(false)
const isLightTheme = computed(() => currentThemeIsLight.value)
function toggleTheme() {
  const next: 'dark' | 'light' = currentThemeIsLight.value ? 'dark' : 'light'
  personalSettings.value.theme = next
  applyThemeToDocument(next)
  currentThemeIsLight.value = next === 'light'
  try { savePersonalSettings(personalSettings.value) } catch { /* ignore */ }
}
const makeVoiceListening = ref(false)
const directVoiceRecognizing = ref(false)
const makeVoiceRecognizing = ref(false)
const directVoicePermissionHint = ref('')
const makeVoicePermissionHint = ref('')
/** 一档直接聊天：单选绑定员工 id（优先于人设 id 参与知识检索）；sessionStorage 持久化 */
const WB_DIRECT_CHAT_EMPLOYEE_ID_KEY = 'wb_direct_chat_employee_id'
const WB_DIRECT_WEB_SEARCH_KEY = 'wb_direct_web_search_v1'
const WB_DIRECT_IMAGE_GEN_KEY = 'wb_direct_image_gen_v1'
const WB_DIRECT_VIDEO_GEN_KEY = 'wb_direct_video_gen_v1'
const directChatEmployeeId = ref('')
const directEmployeeOptions = ref<DirectEmployeeOption[]>([])
const directWebSearchEnabled = ref(false)
const directWebSearching = ref(false)
const directImageGenEnabled = ref(false)
const directVideoGenEnabled = ref(false)
const directMediaGenerating = ref(false)
const directImageSize = ref('1024x1024')
const directImageStyle = ref('default')
const directImageCount = ref(1)
const directVideoAspect = ref('16:9')
const directVideoDurationSec = ref(10)
// === 一档「直接聊天」会话管理 / 流式 / 多模态 / 工具栏 / 个性化 ===
const conversations = ref<Conversation[]>([])
const activeConversationId = ref<string>('')
const activeConversation = computed<Conversation | null>(
  () => conversations.value.find((c) => c.id === activeConversationId.value) || null,
)
const directMessages = computed<ChatMessage[]>(() => activeConversation.value?.messages || [])
const directIsDragging = ref(false)
const editingMessageId = ref<string>('')
const editingDraft = ref<string>('')
const personalSettings = ref<PersonalSettingsValue>(defaultPersonalSettings())
const personalSettingsOpen = ref(false)
const streamingTts = useStreamingTts(() => ttsConfigFromPersonalSettings(personalSettings.value))
const voiceS2s = useVoiceS2SSession()
const voiceUnified = useVoiceUnifiedSession()
const unifiedAsrBridge = createUnifiedAsrBridge(voiceUnified)
const voiceUseUnified = computed(
  () =>
    personalSettings.value.voiceSpeechMode === 'unified' &&
    personalSettings.value.ttsEngine === 'edge-online' &&
    ttsAutoRead.value,
)
const voiceUseS2S = computed(
  () =>
    !voiceUseUnified.value &&
    personalSettings.value.voiceSpeechMode === 's2s' &&
    personalSettings.value.ttsEngine === 'edge-online' &&
    ttsAutoRead.value,
)
/** unified 或 s2s：流式判停 + provisional 开答（豆包式电话体验） */
const voiceUsePhonePipeline = computed(() => voiceUseUnified.value || voiceUseS2S.value)
watch(
  () => [wbSidebar.activeMode, voiceUseS2S.value, voiceUseUnified.value] as const,
  ([mode, s2s, unified]) => {
    if (mode === 'voice' && s2s) {
      void voiceS2s.connect().catch(() => {})
    } else {
      voiceS2s.disconnect()
    }
    if (mode === 'voice' && unified) {
      void voiceUnified.connect().catch(() => {})
    } else {
      voiceUnified.disconnect()
    }
  },
  { immediate: true },
)
function onPersonalSettingsUpdate(v: PersonalSettingsValue) {
  personalSettings.value = v
  try {
    savePersonalSettings(v)
    applyThemeToDocument(v.theme)
    currentThemeIsLight.value = v.theme === 'light' || (v.theme === 'auto' && window.matchMedia?.('(prefers-color-scheme: light)').matches)
  } catch {
    /* ignore */
  }
}
const showAgentMarket = ref(false)
const showVoicePhone = ref(false)
const showMediaGen = ref(false)
const mediaGenInitialTab = ref<'image' | 'video' | 'ppt' | 'doc'>('image')
const allBots = ref<AgentBot[]>([])
const activeBotId = ref<string>('')
const activeBot = computed<AgentBot | null>(
  () => allBots.value.find((b) => b.id === activeBotId.value) || null,
)
/** 对话进行中：左上角一行当前主题（会话标题或最近用户提问摘要） */
const _directTaskLine = computed(() => {
  const convTitle = String(activeConversation.value?.title || '').trim()
  if (convTitle && convTitle !== '新对话') return convTitle
  const latestUser = [...directMessages.value].reverse().find((m) => m.role === 'user')
  const raw = stripInternalMarkers(latestUser?.content || '').replace(/\s+/g, ' ').trim()
  if (raw) return summarizeForTitle(raw)
  if (activeBot.value?.name) return `${activeBot.value.name} · 对话中`
  return '对话中'
})
const speakingMessageId = ref<string>('')
function stopDirectTtsPlayback() {
  streamingTts.stop()
}
const directCanSend = computed(() => {
  if (String(directDraft.value || '').trim()) return true
  const files = directAttachedFiles.value
  if (!files.length) return false
  if (files.some((f) => f.status === 'uploading')) return false
  return files.some(
    (f) =>
      (f.purpose === 'employee' && f.status === 'ready' && f.file) ||
      (f.purpose !== 'employee' && (f.status === 'ready' || f.status === 'inline')),
  )
})
const directSendDisabled = computed(() => directLoading.value || !directCanSend.value)
const butlerTrayStore = useButlerWorkbenchTrayStore()
const butlerDownloadHistory = useButlerDownloadHistoryStore()
const agentStore = useAgentStore()
const headerGeneratedStripPlan = computed(() =>
  planHeaderGeneratedStrip(directGeneratedFiles.value.length),
)
const composerAttachmentStripPlan = computed(() =>
  planComposerAttachmentStrip(directAttachedFiles.value.length),
)
const headerFileStripPlan = computed(() => ({
  stripGeneratedCount: headerGeneratedStripPlan.value.stripGeneratedCount,
  stripAttachmentCount: 0,
  overflowAttachmentCount: composerAttachmentStripPlan.value.overflowCount,
  overflowGeneratedCount: headerGeneratedStripPlan.value.overflowGeneratedCount,
  overflowCount:
    headerGeneratedStripPlan.value.overflowCount + composerAttachmentStripPlan.value.overflowCount,
}))
/** 二档 / 做 Mod 作曲栏附件卡片 */
const directVisibleAttachedFiles = computed(() => {
  const count = composerAttachmentStripPlan.value.visibleCount
  const list = directAttachedFiles.value
  if (count <= 0) return []
  return list.slice(Math.max(0, list.length - count))
})
/** 一档直接对话：输入区待发送附件（与顶栏下载区隔离） */
const directComposerVisibleFiles = directVisibleAttachedFiles
const butlerFileOverflowCount = computed(() => headerFileStripPlan.value.overflowCount)
const directHiddenAttachmentCount = computed(() => composerAttachmentStripPlan.value.overflowCount)
const directComposerHiddenCount = directHiddenAttachmentCount
function openButlerFileTray() {
  agentStore.openPanel({ focusFiles: true })
}
watch(
  () => [directAttachedFiles.value, directGeneratedFiles.value] as const,
  ([atts, gens]) => {
    butlerTrayStore.setWorkbenchFiles({
      attachments: atts.map((f) => ({
        id: String(f.id || ''),
        name: String(f.name || ''),
        status: String(f.status || ''),
        purpose: f.purpose,
        ingesting: f.ingesting,
      })),
      generated: gens,
    })
  },
  { deep: true, immediate: true },
)
const directAttachmentMentions = computed(() =>
  directAttachedFiles.value
    .map((f) => String(f?.name || '').trim())
    .filter(Boolean),
)
const CONSUMPTION_TIER_STORAGE_KEY = 'workbench_consumption_tier'
function readStoredConsumptionTier(): number {
  try {
    const raw = sessionStorage.getItem(CONSUMPTION_TIER_STORAGE_KEY)
    const n = raw == null ? NaN : parseInt(raw, 10)
    if (Number.isFinite(n) && n >= 1 && n <= 10) return n
  } catch {
    /* ignore */
  }
  return 5
}
/** 直接聊天右上角「消费档位」1–10：占位；与右侧工作台 1/2/3 挡位无关 */
const consumptionTier = ref(readStoredConsumptionTier())
const tierPanelOpen = ref(false)
const empPanelOpen = ref(false)
const empDropdownOpen = ref(false)
const tierTriggerRef = ref<HTMLElement | null>(null)
const empTriggerRef = ref<HTMLElement | null>(null)
const tierPanelAnchorStyle = ref<Record<string, string>>({})
const empPanelAnchorStyle = ref<Record<string, string>>({})
const homeStarterCards: ReadonlyArray<{
  label: string
  desc: string
  prompt: string
  requiresAttachment: boolean
}> = [
  {
    label: '总结文档',
    desc: '上传 Word/PDF 等，由读取员工解析后总结',
    prompt: '请帮我总结这份文档的要点',
    requiresAttachment: true,
  },
  {
    label: '分析 Excel',
    desc: '上传 .xlsx/.csv，由读取员工解析后分析',
    prompt: '请帮我分析表格数据并给出结论',
    requiresAttachment: true,
  },
  {
    label: '生成 Word',
    desc: '直接描述内容，或上传 docx / JSON 模板后生成',
    prompt: '请生成一份可下载的 Word（docx）文档，标题为季度总结，正文包含三个要点',
    requiresAttachment: false,
  },
  {
    label: '写方案',
    desc: '从大纲到完整方案，一键生成',
    prompt: '请帮我写一份可执行的方案',
    requiresAttachment: false,
  },
  {
    label: '调员工',
    desc: '选择 AI 员工，按岗位能力回答',
    prompt: '帮我选择合适的 AI 员工并说明能做什么',
    requiresAttachment: false,
  },
]
const homeSuggestionChips = computed(() => loadPersonalSettings().suggestions.slice(0, 3))
const recentHomeConversations = computed(() =>
  [...conversations.value]
    .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0))
    .slice(0, 2),
)
function updateTierPanelAnchor() {
  if (!tierTriggerRef.value) {
    tierPanelAnchorStyle.value = {}
    return
  }
  const r = tierTriggerRef.value.getBoundingClientRect()
  const panelMaxH = wbNav.isMobile ? 360 : 400
  const top = Math.min(r.bottom + 8, window.innerHeight - panelMaxH - 12)
  tierPanelAnchorStyle.value = {
    '--wb-panel-top': `${Math.max(8, top)}px`,
    '--wb-panel-left': `${Math.max(8, Math.min(r.left, window.innerWidth - 280))}px`,
  }
}
function updateEmpPanelAnchor() {
  if (wbNav.isMobile || !empTriggerRef.value) {
    empPanelAnchorStyle.value = {}
    return
  }
  const r = empTriggerRef.value.getBoundingClientRect()
  empPanelAnchorStyle.value = {
    '--wb-panel-top': `${r.bottom + 8}px`,
    '--wb-panel-left': `${Math.max(8, r.left)}px`,
  }
}
function toggleTierPanel() {
  const next = !tierPanelOpen.value
  tierPanelOpen.value = next
  if (next) {
    empPanelOpen.value = false
    nextTick(() => updateTierPanelAnchor())
  }
}
function toggleDirectWebSearch() {
  directWebSearchEnabled.value = !directWebSearchEnabled.value
  tierPanelOpen.value = false
  empPanelOpen.value = false
}

  return {
    suggestModIdFromText, LLM_CATEGORY_ORDER, router, route, wbSidebar,
    wbNav, draft, displayName, workbenchErrorMessage, workbenchHttpStatus,
    inputRef, handoffPanelRef, pendingHandoff, makeCompletionResult, employeeSixDimModalOpen,
    employeeSixDimReport, makeCompletionRef, finalizeLoading, finalizeError, orchestrationSession,
    orchestrationSessionId, pollStop, orchPhase, orchestrationEtaSeconds, orchestrationEtaReason,
    __wbState, orchTimingStartMs, orchElapsedTick, workflowLinkOffer, linkMods,
    linkModId, linkBusy, linkError, planSession, planReplyDraft,
    autoPilotRunning, autoPilotError, voiceChecklistPaused, planOptionSelections, PLAN_OPTION_OTHER_ID,
    planOptionOtherText, clearPlanOptionOtherText, planPanelRef, planSurfaceKey, MAKE_PROGRESS_CACHE_KEY,
    MAKE_PROGRESS_CACHE_TTL_MS, planLoadingStepsSummary, planLoadingStepsChat, planLoadingAdvance, planLoadingStepLabelsForUi,
    planLoadingProgressPercent, knowledgeStatus, knowledgeDocs, knowledgeLoading, knowledgeUploading,
    knowledgeError, knowledgeFileInputRef, knowledgeDragActive, isEmbeddingConfigured, CANVAS_SKILL_INTENT,
    isCanvasSkillIntent, composerIntent, modFrontendEnabled, activeGear, showDirectChatSurface,
    showMakePlatformCasualChat, showDirectStyleConversation, platformChatMode, voiceCasualChatMode, voiceHumanChatMode,
    voiceSessionModeForIntent, persistPlatformChatMode, directDraft, directPlaceholder, directFileInputRef,
    directAttachedFiles, directGeneratedFiles, officeReadCacheByConversation, directGeneratingFile, directGeneratingFormatLabel,
    showDirectHomeFileStrip, directLoading, directSendPending, directError, directVoiceListening,
    directVoiceAudioLevel, directWaveformCanvas, ttsAutoRead, currentThemeIsLight, isLightTheme,
    toggleTheme, makeVoiceListening, directVoiceRecognizing, makeVoiceRecognizing, directVoicePermissionHint,
    makeVoicePermissionHint, WB_DIRECT_CHAT_EMPLOYEE_ID_KEY, WB_DIRECT_WEB_SEARCH_KEY, WB_DIRECT_IMAGE_GEN_KEY, WB_DIRECT_VIDEO_GEN_KEY,
    directChatEmployeeId, directEmployeeOptions, directWebSearchEnabled, directWebSearching, directImageGenEnabled,
    directVideoGenEnabled, directMediaGenerating, directImageSize, directImageStyle, directImageCount,
    directVideoAspect, directVideoDurationSec, conversations, activeConversationId, activeConversation,
    directMessages, directIsDragging, editingMessageId, editingDraft, personalSettings,
    personalSettingsOpen, streamingTts, voiceS2s, voiceUnified, unifiedAsrBridge,
    voiceUseUnified, voiceUseS2S, voiceUsePhonePipeline, onPersonalSettingsUpdate, showAgentMarket,
    showVoicePhone, showMediaGen, mediaGenInitialTab, allBots, activeBotId,
    activeBot, _directTaskLine, speakingMessageId, stopDirectTtsPlayback, directCanSend,
    directSendDisabled, butlerTrayStore, butlerDownloadHistory, agentStore, headerGeneratedStripPlan,
    composerAttachmentStripPlan, headerFileStripPlan, directVisibleAttachedFiles, directComposerVisibleFiles, butlerFileOverflowCount,
    directHiddenAttachmentCount, directComposerHiddenCount, openButlerFileTray, directAttachmentMentions, CONSUMPTION_TIER_STORAGE_KEY,
    readStoredConsumptionTier, consumptionTier, tierPanelOpen, empPanelOpen, empDropdownOpen,
    tierTriggerRef, empTriggerRef, tierPanelAnchorStyle, empPanelAnchorStyle, homeStarterCards,
    homeSuggestionChips, recentHomeConversations, updateTierPanelAnchor, updateEmpPanelAnchor, toggleTierPanel,
    toggleDirectWebSearch,
  }
}

export type useWbSuggestModIdFromTextBinds = ReturnType<typeof useWbSuggestModIdFromText>
