import { ref, computed, nextTick } from 'vue'
import type { AgentBot } from '../../utils/agentBots'
import { loadAllBots, loadMyBots, saveMyBots, loadFavorites, saveFavorites, saveActiveBotId } from '../../utils/agentBots'
import { api } from '../../api'
import { getAccessToken } from '../../infrastructure/storage/tokenStore'
import type { Conversation } from '../../utils/conversationStore'
import { loadConversations, saveActiveId, makeMessage, exportConversationAsMarkdown, shouldReloadConversationFromStorage, mergeConversationsForPick } from '../../utils/conversationStore'
import { hasEmployeePlanContext, inferUserGoalFromVoiceMessages, looksLikeEmployeeTaskDescription } from '../../composables/voiceUtteranceRouter'
import { cleanTextForTts } from '../../utils/ttsTextClean'
import { directFileExt, isEmployeeExecuteFileExt, isEmployeeSpreadsheetExt } from '../../utils/directAttachments'
import { readEmployeeDisplayName, TABULAR_READ_EMPLOYEE_IDS } from '../../utils/tabularReadEmployees'
import type { useWbBuildDirectAttachItem } from './useWbBuildDirectAttachItem'
import type { DirectAttachment, DirectEmployeeOption, WorkbenchLlmCatalog, WorkbenchStateRecord } from './types'

// 拆分自 WorkbenchHomeView.vue（原行 3173–3177, 3179–3181, 5549–5554 …）；逐字迁移，行为不变。
export function useWbLoadDirectEmployeeOptions(ctx: ReturnType<typeof useWbBuildDirectAttachItem>) {
  const {
    router, route, wbSidebar, wbNav, draft, inputRef,
    pendingHandoff, orchPhase, __wbState, planSession, composerIntent, voiceHumanChatMode,
    directGeneratedFiles, directError, WB_DIRECT_CHAT_EMPLOYEE_ID_KEY, directChatEmployeeId, directEmployeeOptions, conversations,
    activeConversationId, directMessages, directIsDragging, editingMessageId, editingDraft, personalSettings,
    streamingTts, showAgentMarket, showMediaGen, allBots, activeBotId, speakingMessageId,
    stopDirectTtsPlayback, voiceMessages, voiceSessionState, voiceState, syncWorkPhase, clearDirectGenerating,
    persistConversations, ensureActiveConversation, patchActiveConversation,
  } = ctx

function pickHomeConversation(id: string) {
  setActiveConversation(id)
  wbSidebar.closeMobile()
  nextTick(() => inputRef.value?.focus())
}
function formatHomeConvTime(t: number | undefined) {
  return convTimeFormat(t)
}
function startEditUserMessage(messageId: string) {
  const m = directMessages.value.find((x) => x.id === messageId)
  if (!m || m.role !== 'user') return
  editingMessageId.value = messageId
  editingDraft.value = m.content
}
function cancelEditUserMessage() {
  editingMessageId.value = ''
  editingDraft.value = ''
}
function setMessageFeedback(messageId: string, fb: 'up' | 'down' | null) {
  patchActiveConversation((c) => {
    const idx = c.messages.findIndex((m) => m.id === messageId)
    if (idx < 0) return
    c.messages[idx] = { ...c.messages[idx], feedback: fb }
  })
}
async function speakMessage(messageId: string) {
  if (speakingMessageId.value === messageId) {
    stopDirectTtsPlayback()
    speakingMessageId.value = ''
    return
  }
  const m = directMessages.value.find((x) => x.id === messageId)
  if (!m?.content) return

  stopDirectTtsPlayback()
  const text = cleanTextForTts(m.content)
  if (!text) return

  speakingMessageId.value = messageId
  __wbState.ttsStreamAssistantId = ''
  try {
    await streamingTts.speak(text)
  } catch {
    directError.value = '朗读失败。'
  } finally {
    if (speakingMessageId.value === messageId) speakingMessageId.value = ''
  }
}
function copyConversationLink(c: Conversation) {
  const md = exportConversationAsMarkdown(c)
  const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${c.title || '对话'}-${c.id.slice(0, 8)}.md`
  a.click()
  URL.revokeObjectURL(url)
}
function setActiveConversation(id: string) {
  if (!id) return
  if (__wbState.currentStreamHandle) __wbState.currentStreamHandle.abort()
  const loaded = loadConversations()
  const switching = id !== activeConversationId.value
  const stale = shouldReloadConversationFromStorage(
    directMessages.value.length,
    loaded.find((c) => c.id === id)?.messages,
  )
  if (switching || stale) {
    conversations.value = mergeConversationsForPick(
      conversations.value,
      loaded,
      id,
      directMessages.value.length,
    )
  }
  if (switching) {
    directGeneratedFiles.value = []
    clearDirectGenerating()
  }
  activeConversationId.value = id
  saveActiveId(id)
  wbSidebar.setActiveConversationId(id)
}
function pickConversation(id: string) {
  setActiveConversation(id)
}
function convTimeFormat(t: number | string | null | undefined): string {
  if (!t) return ''
  const d = new Date(t)
  const diff = Date.now() - d.getTime()
  const days = Math.floor(diff / (1000 * 60 * 60 * 24))
  if (days === 0) return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  if (days === 1) return '昨天'
  if (days < 7) return `${days}天前`
  return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}
function isFileEmployeePurposeToggle(f: DirectAttachment): boolean {
  return isEmployeeSpreadsheetExt(directFileExt(String(f.name || '')))
}
function isFileAutoReadEmployee(f: DirectAttachment): boolean {
  const ext = directFileExt(String(f.name || ''))
  return isEmployeeExecuteFileExt(ext) && !isEmployeeSpreadsheetExt(ext)
}
function _pinConversation(id: string) {
  conversations.value = conversations.value.map((c) =>
    c.id === id ? { ...c, pinned: !c.pinned, updatedAt: Date.now() } : c,
  )
  persistConversations()
}
function _renameConversation(id: string, title: string) {
  conversations.value = conversations.value.map((c) =>
    c.id === id ? { ...c, title: title.slice(0, 60), updatedAt: Date.now() } : c,
  )
  persistConversations()
}
function _exportConversation(id: string) {
  const c = conversations.value.find((x) => x.id === id)
  if (!c) return
  copyConversationLink(c)
}
function _removeConversation(id: string) {
  if (!window.confirm('确定删除这个对话？删除后无法恢复。')) return
  conversations.value = conversations.value.filter((c) => c.id !== id)
  if (activeConversationId.value === id) {
    activeConversationId.value = conversations.value[0]?.id || ''
    saveActiveId(activeConversationId.value)
    wbSidebar.setActiveConversationId(activeConversationId.value)
  }
  persistConversations()
}
function _clearAllConversations() {
  if (!window.confirm('清空全部对话？此操作不可恢复。')) return
  conversations.value = []
  activeConversationId.value = ''
  saveActiveId('')
  persistConversations()
}
/** 拖入计数：dragenter/leave 在子元素切换时会成对触发，单纯靠 dragleave 关闭遮罩会闪烁，
 *  改用计数器在所有子元素都 leave 完成后再清零。 */
const directDragDepth = ref(0)
function dragHasFiles(e: DragEvent): boolean {
  const types = e.dataTransfer?.types
  if (!types) return false
  for (let i = 0; i < types.length; i += 1) {
    if (types[i] === 'Files') return true
  }
  return false
}
function onSurfaceDragEnter(e: DragEvent) {
  if (!dragHasFiles(e)) return
  e.preventDefault()
  directDragDepth.value += 1
  directIsDragging.value = true
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'
}
function onSurfaceDragOver(e: DragEvent) {
  if (!dragHasFiles(e)) return
  e.preventDefault()
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'
}
function onSurfaceDragLeave(e: DragEvent) {
  if (!dragHasFiles(e)) return
  directDragDepth.value = Math.max(0, directDragDepth.value - 1)
  if (directDragDepth.value === 0) directIsDragging.value = false
}
function refreshAllBots() {
  allBots.value = loadAllBots()
}
function onCreateAgent(bot: AgentBot) {
  const my = loadMyBots()
  const next = [{ ...bot, mine: true }, ...my.filter((b) => b.id !== bot.id)]
  saveMyBots(next)
  const fav = loadFavorites()
  fav.add(bot.id)
  saveFavorites(fav)
  refreshAllBots()
}
function onRemoveAgent(bot: AgentBot) {
  if (!bot.mine) return
  if (!window.confirm(`删除我的 Bot「${bot.name}」？`)) return
  const my = loadMyBots().filter((b) => b.id !== bot.id)
  saveMyBots(my)
  const fav = loadFavorites()
  fav.delete(bot.id)
  saveFavorites(fav)
  if (activeBotId.value === bot.id) {
    activeBotId.value = ''
    saveActiveBotId('')
  }
  refreshAllBots()
}
function onFavoriteAgent(bot: AgentBot) {
  const fav = loadFavorites()
  if (fav.has(bot.id)) fav.delete(bot.id)
  else fav.add(bot.id)
  saveFavorites(fav)
  refreshAllBots()
}
function onStartWithAgent(bot: AgentBot) {
  activeBotId.value = bot.id
  saveActiveBotId(bot.id)
  showAgentMarket.value = false
  ensureActiveConversation({ forceNew: true, bot })
}
function clearActiveBot() {
  activeBotId.value = ''
  saveActiveBotId('')
}
function customerServiceQueryContext(): string {
  const q = route.query || {}
  if (String(q.assistant || '') !== 'customer-service') return ''
  const scene = String(q.scene || 'general')
  const parts = [
    '我从市场或导航进入 AI 客服，需要处理以下问题：',
    `场景：${scene}`,
  ]
  const catalogId = String(q.catalog_id || '').trim()
  const pkgId = String(q.pkg_id || '').trim()
  const itemName = String(q.item_name || '').trim()
  const materialCategory = String(q.material_category || '').trim()
  const orderNo = String(q.order_no || '').trim()
  const complaintType = String(q.complaint_type || '').trim()
  if (catalogId) parts.push(`商品 ID：${catalogId}`)
  if (pkgId) parts.push(`包名：${pkgId}`)
  if (itemName) parts.push(`商品名称：${itemName}`)
  if (materialCategory) parts.push(`市场类目：${materialCategory}`)
  if (orderNo) parts.push(`订单号：${orderNo}`)
  if (complaintType) parts.push(`问题类型：${complaintType}`)
  parts.push('请先告诉我还需要补充哪些证据材料，并给出下一步处理路径。')
  return parts.join('\n')
}
function stripCustomerServiceEntryQueryFromUrl() {
  const q = { ...(route.query as Record<string, string | string[] | undefined>) }
  const keys = [
    'assistant',
    'scene',
    'catalog_id',
    'pkg_id',
    'item_name',
    'material_category',
    'order_no',
    'complaint_type',
  ]
  let changed = false
  for (const k of keys) {
    if (Object.prototype.hasOwnProperty.call(q, k)) {
      delete q[k]
      changed = true
    }
  }
  if (!changed) return
  void router.replace({ path: route.path, query: q })
}
/** 避免 keep-alive 下 onMounted 与 onActivated 同一帧各跑一次，重复 forceNew 会话 */
function applyCustomerServiceRouteContext() {
  if (String(route.query?.assistant || '') !== 'customer-service') return
  const bot = allBots.value.find((b) => b.id === 'customer-service')
  if (!bot) return
  const dedupeKey = JSON.stringify(route.query)
  if (dedupeKey === __wbState.lastAppliedCustomerServiceQueryKey) return
  __wbState.lastAppliedCustomerServiceQueryKey = dedupeKey
  activeBotId.value = bot.id
  saveActiveBotId(bot.id)
  const ctx = customerServiceQueryContext()
  const conv = ensureActiveConversation({ forceNew: true, bot })
  if (ctx) {
    conv.messages.push(makeMessage('user', ctx, { agentLabel: bot.name }))
    conv.messages.push(makeMessage('assistant', '我已收到这些上下文。请继续补充证据截图、链接、订单号或你希望平台采取的处理结果；如果信息已完整，我会帮你整理成可提交给管理员的工单摘要。', { agentLabel: bot.name }))
    persistConversations()
  }
  stripCustomerServiceEntryQueryFromUrl()
}
const directFontPxStyle = computed(() => ({
  '--wb-direct-font-px': `${personalSettings.value.fontPx}px`,
}))
function videoSizeForAspect(aspect: string): string {
  const a = String(aspect || '').trim()
  if (a === '9:16') return '720x1280'
  if (a === '1:1') return '1024x1024'
  return '1280x720'
}
function insertGeneratedToChat(text: string) {
  if (!text) return
  ensureActiveConversation()
  const m = makeMessage('assistant', text, {
    agentLabel: 'AI 创作',
  })
  patchActiveConversation((c) => c.messages.push(m))
  showMediaGen.value = false
}
function onComposerFocus(e: FocusEvent) {
  if (!wbNav.isMobile) return
  const el = e.target as HTMLElement | null
  if (!el) return
  window.setTimeout(() => {
    try {
      el.scrollIntoView({ block: 'center', behavior: 'smooth' })
    } catch {
      el.scrollIntoView(true)
    }
  }, 320)
}
function buildVoiceTopicHint(extra?: string): string {
  return [
    voiceSessionState.value.userGoal,
    ...voiceMessages.value.map((m) => String(m.content || '')),
    extra || '',
  ].join(' ')
}
function ensureVoiceEmployeeIntent(content?: string) {
  if (wbSidebar.activeMode !== 'voice') return
  if (voiceHumanChatMode.value) return
  if (planSession.value?.intentKey === 'employee') {
    composerIntent.value = 'employee'
    return
  }
  if (pendingHandoff.value?.intentKey === 'employee') {
    composerIntent.value = 'employee'
    return
  }
  if (hasEmployeePlanContext(voiceSessionState.value, voiceMessages.value, content)) {
    composerIntent.value = 'employee'
    return
  }
  if (content && looksLikeEmployeeTaskDescription(content)) {
    composerIntent.value = 'employee'
  }
}
function shouldRouteVoiceAsEmployee(content?: string): boolean {
  if (voiceHumanChatMode.value) return false
  if (composerIntent.value === 'employee') return true
  if (wbSidebar.activeMode !== 'voice') return false
  if (planSession.value?.intentKey === 'employee') return true
  if (pendingHandoff.value?.intentKey === 'employee') return true
  if (hasEmployeePlanContext(voiceSessionState.value, voiceMessages.value, content)) return true
  return Boolean(content && looksLikeEmployeeTaskDescription(content))
}
/** 员工模式：未进入正式规划前的 summary 面板视为过期，对话时自动收起 */
function shouldAutoDismissStaleVoicePlan(): boolean {
  const ps = planSession.value
  if (!ps || composerIntent.value !== 'employee') return false
  if (ps.phase !== 'summary') return false
  if (voiceSessionState.value.readyToPlan && voiceSessionState.value.stage === 'planning') return false
  return true
}
function ensureEmployeePlanContextFromVoice(content: string) {
  const inferred = inferUserGoalFromVoiceMessages(voiceMessages.value, content)
  if (inferred) voiceSessionState.value.userGoal = inferred
}
function textsSimilarForFinalize(a: string, b: string): boolean {
  const x = a.trim()
  const y = b.trim()
  if (!x || !y) return false
  if (x === y) return true
  return Math.abs(x.length - y.length) <= 3 && (x.includes(y) || y.includes(x))
}
function _speakText(text: string) {
  voiceState.value = 'reporting'
  void streamingTts.speak(text).finally(() => {
    if (voiceState.value === 'reporting') voiceState.value = 'idle'
  })
}
function syncVoiceWorkPhase() {
  syncWorkPhase({
    planSession: planSession.value,
    pendingHandoff: pendingHandoff.value,
    orchPhase: orchPhase.value,
  })
}
function requireLoginForWorkbenchUse() {
  if (getAccessToken()) return true
  const text = draft.value.trim()
  try {
    if (text) sessionStorage.setItem('workbench_home_pending_draft', text)
    sessionStorage.setItem('workbench_home_pending_intent', composerIntent.value)
  } catch {
    /* ignore */
  }
  void router.push({ name: 'login', query: { redirect: router.currentRoute.value.fullPath || '/' } })
  return false
}
const llmCatalog = ref<WorkbenchLlmCatalog | null>(null)
const llmCatalogLoading = ref(false)
const llmCatalogError = ref('')
const selectedProvider = ref('openai')
const selectedModel = ref('')
/** auto：发送时用账户 preferences；manual：用下方自选并写回 preferences */
const modelMode = ref('auto')
/** 自选时厂商/模型自定义下拉：'provider' | 'model' | null（避免原生 select 白底弹层） */
const llmDdOpen = ref<'provider' | 'model' | 'directProvider' | 'directModel' | null>(null)
const llmMobileSheetOpen = ref(false)
const _canvasSkillMeta = {
  title: '生成 Skill 组',
  sub: '按描述生成可复用 Skill，并在画布上编排成 Skill 组（调度图）。要「可运行程序本体」请走脚本工作流。',
}
const INTENT_META: Record<string, { title: string; sub: string }> = {
  mod: {
    title: '做 Mod',
    sub: '可先生成仓库与名片骨架，也可以继续补齐员工包登记、工作流绑定和真实执行验证。只有名片不等于可工作的员工。',
  },
  employee: {
    title: '做员工',
    sub: '提示词与工具 · 在下方用自然语言描述岗位与流程',
  },
  skill: _canvasSkillMeta,
  /** @deprecated 会话缓存旧键，等同于 skill */
  workflow: _canvasSkillMeta,
}
const intentMeta = computed(() => INTENT_META[composerIntent.value] || INTENT_META.skill)
/** Mod/employee：可收起侧栏说明，仅保留仓库跳转区 */
const intentGuideCollapsed = ref(true)
const catalogEmployeeRows = ref<WorkbenchStateRecord[]>([])
const catalogModRows = ref<WorkbenchStateRecord[]>([])
const pickEmployeeKey = ref('')
const pickModId = ref('')
const _catalogEmployeesForPick = computed(() => catalogEmployeeRows.value)
const _catalogModsForPick = computed(() =>
  (catalogModRows.value || []).map((r) => ({
    id: r.id,
    label: `${r.id}${r.manifest?.name ? ` · ${r.manifest.name}` : ''}`,
  })),
)
const _pickedEmployeeRow = computed(() => {
  const k = (pickEmployeeKey.value || '').trim()
  if (!k) return null
  return catalogEmployeeRows.value.find((r) => r.k === k) || null
})
const pickedModRow = computed(() => {
  const id = (pickModId.value || '').trim()
  if (!id) return null
  return (catalogModRows.value || []).find((r) => String(r.id) === id) || null
})
const _pickedModManifestVersion = computed(() => {
  const v = pickedModRow.value?.manifest?.version
  return typeof v === 'string' && v.trim() ? v.trim() : '?'
})
const _pickedModManifestName = computed(() => {
  const n = pickedModRow.value?.manifest?.name
  return typeof n === 'string' && n.trim() ? n.trim() : ''
})
const _pickedModManifestDescription = computed(() => {
  const d = pickedModRow.value?.manifest?.description
  return typeof d === 'string' ? d : ''
})
function truncateWorkbenchText(text: unknown, max = 280): string {
  const s = typeof text === 'string' ? text.replace(/\s+/g, ' ').trim() : ''
  if (!s) return ''
  return s.length <= max ? s : `${s.slice(0, max)}…`
}
function _releaseChannelLabel(ch: unknown): string {
  const x = String(ch || 'stable').toLowerCase()
  return x === 'draft' ? '测试通道' : '正式通道'
}
async function loadDirectEmployeeOptions() {
  directEmployeeOptions.value = []
  if (!localStorage.getItem('modstore_token')) return
  const merged = new Map<string, DirectEmployeeOption>()
  try {
    const sqlRows = await api.listEmployees()
    for (const e of Array.isArray(sqlRows) ? sqlRows : []) {
      const id = String((e as { id?: unknown })?.id ?? '').trim()
      if (!id) continue
      const name = String((e as { name?: unknown })?.name ?? id).trim() || id
      merged.set(id, { id, name, sourceLabel: '执行器' })
    }
  } catch {
    /* ignore */
  }
  try {
    const r = await api.listV1Packages('employee_pack', '', 120, 0)
    for (const p of r?.packages || []) {
      const id = String((p as { id?: unknown })?.id ?? '').trim()
      if (!id) continue
      const pkgName = String((p as { name?: unknown })?.name ?? id).trim() || id
      const existing = merged.get(id)
      if (existing) {
        const sl = existing.sourceLabel
        existing.sourceLabel = sl.includes('目录') ? sl : `${sl}·目录`
        if (pkgName && pkgName !== existing.name) existing.name = `${existing.name}（${pkgName}）`
        continue
      }
      merged.set(id, { id, name: pkgName, sourceLabel: '本地包' })
    }
  } catch {
    /* ignore */
  }
  try {
    const cat = await api.catalog('', 'employee_pack', 80, 0)
    for (const it of (cat as { items?: unknown[] })?.items || []) {
      const row = it as { pkg_id?: string; id?: string | number; name?: string }
      const id = String(row.pkg_id || row.id || '').trim()
      if (!id || !TABULAR_READ_EMPLOYEE_IDS.includes(id as (typeof TABULAR_READ_EMPLOYEE_IDS)[number])) continue
      const name = String(row.name || '').trim() || readEmployeeDisplayName(id)
      const existing = merged.get(id)
      if (existing) {
        existing.sourceLabel = existing.sourceLabel.includes('市场') ? existing.sourceLabel : `${existing.sourceLabel}·市场`
        if (name && name !== existing.name) existing.name = name
        continue
      }
      merged.set(id, { id, name, sourceLabel: 'AI 市场' })
    }
  } catch {
    /* ignore */
  }
  directEmployeeOptions.value = [...merged.values()].sort((a, b) =>
    String(a.name).localeCompare(String(b.name), 'zh-CN'),
  )
  const cur = String(directChatEmployeeId.value || '').trim()
  if (cur && !merged.has(cur)) {
    directChatEmployeeId.value = ''
    try {
      sessionStorage.removeItem(WB_DIRECT_CHAT_EMPLOYEE_ID_KEY)
    } catch {
      /* ignore */
    }
  }
}

  return {
    ...ctx, pickHomeConversation, formatHomeConvTime, startEditUserMessage, cancelEditUserMessage,
    setMessageFeedback, speakMessage, copyConversationLink, setActiveConversation, pickConversation,
    convTimeFormat, isFileEmployeePurposeToggle, isFileAutoReadEmployee, _pinConversation, _renameConversation,
    _exportConversation, _removeConversation, _clearAllConversations, directDragDepth, dragHasFiles,
    onSurfaceDragEnter, onSurfaceDragOver, onSurfaceDragLeave, refreshAllBots, onCreateAgent,
    onRemoveAgent, onFavoriteAgent, onStartWithAgent, clearActiveBot, customerServiceQueryContext,
    stripCustomerServiceEntryQueryFromUrl, applyCustomerServiceRouteContext, directFontPxStyle, videoSizeForAspect, insertGeneratedToChat,
    onComposerFocus, buildVoiceTopicHint, ensureVoiceEmployeeIntent, shouldRouteVoiceAsEmployee, shouldAutoDismissStaleVoicePlan,
    ensureEmployeePlanContextFromVoice, textsSimilarForFinalize, _speakText, syncVoiceWorkPhase, requireLoginForWorkbenchUse,
    llmCatalog, llmCatalogLoading, llmCatalogError, selectedProvider, selectedModel,
    modelMode, llmDdOpen, llmMobileSheetOpen, _canvasSkillMeta, INTENT_META,
    intentMeta, intentGuideCollapsed, catalogEmployeeRows, catalogModRows, pickEmployeeKey,
    pickModId, _catalogEmployeesForPick, _catalogModsForPick, _pickedEmployeeRow, pickedModRow,
    _pickedModManifestVersion, _pickedModManifestName, _pickedModManifestDescription, truncateWorkbenchText, _releaseChannelLabel,
    loadDirectEmployeeOptions,
  }
}

export type useWbLoadDirectEmployeeOptionsBinds = ReturnType<typeof useWbLoadDirectEmployeeOptions>
