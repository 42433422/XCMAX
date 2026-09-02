import type { AgentBot } from '../../utils/agentBots'
import { api } from '../../api'
import { clearAuthTokens } from '../../infrastructure/storage/tokenStore'
import type { ChatMessage, Conversation } from '../../utils/conversationStore'
import { saveConversations, saveActiveId, createConversation, makeMessage, buildConversationTitle } from '../../utils/conversationStore'
import { detectOutputContract, outputContractSystemRules } from '../../utils/detectOutputContract'
import { employeeDownloadsToGeneratedFiles, filterUserFacingOfficeDownloads, mergeGeneratedFiles, type DirectGeneratedFile } from '../../utils/directGeneratedFiles'
import { DIRECT_EMPLOYEE_FILE_MAX_BYTES, DIRECT_KB_MAX_BYTES, DIRECT_KB_SUPPORTED_EXT, DIRECT_KB_SUPPORTED_EXTENSIONS, directFileExt, formatDirectFileSize, resolveReadEmployeeForExtension } from '../../utils/directAttachments'
import { compressImageFileToDataUrl, isImageFileForVision } from '../../utils/visionMultimodal'
import { extractEmployeeReadTextForLlm, formatEmployeeReadResultSummary, parseEmployeeOutputDownloads, readEmployeeDisplayName } from '../../utils/tabularReadEmployees'
import { officeEmployeeCapabilitySystemHint, type OfficeFormat } from '../../utils/officeEmployeeOrchestration'
import { runOfficeGeneratePhase } from '../../utils/officeEmployeeRunner'
import type { useWbDrawDirectWaveform } from './useWbDrawDirectWaveform'
import type { DirectAttachment, DirectWebSearchResult } from './types'

// 拆分自 WorkbenchHomeView.vue（原行 3099–3142, 4141–4232, 4250–4261 …）；逐字迁移，行为不变。
export function useWbBuildDirectAttachItem(ctx: ReturnType<typeof useWbDrawDirectWaveform>) {
  const {
    router, wbSidebar, draft, displayName, __wbState, directDraft,
    directAttachedFiles, directGeneratedFiles, officeReadCacheByConversation, directGeneratingFile, directLoading, directSendPending,
    directError, directChatEmployeeId, directEmployeeOptions, conversations, activeConversationId, activeConversation,
    directMessages, personalSettings, activeBot, speakingMessageId, stopDirectTtsPlayback, butlerDownloadHistory,
    resolveDirectFileEmployeeId, makeDirectAttachId,
  } = ctx

async function retrieveWebForDirect(userText: string): Promise<DirectWebSearchResult> {
  const query = String(userText || '').trim()
  if (query.length < 2) {
    return { contextPack: '', citations: [], note: '检索词过短，已跳过联网搜索。' }
  }
  try {
    const res = (await withRequestTimeout(
      api.workbenchWebSearch({ query, max_results: 8, max_chars: 8000 }),
      DIRECT_WEB_SEARCH_MS,
    )) as {
      ok?: boolean
      context_pack?: string
      sources?: Array<{ title?: string; url?: string }>
      warnings?: string[]
      via?: string
      web_error?: string
      error?: string
    }
    const pack = String(res?.context_pack || '').trim()
    const citations = (Array.isArray(res?.sources) ? res.sources : [])
      .map((s, i) => ({
        title: String(s?.title || s?.url || `来源 ${i + 1}`),
        url: String(s?.url || '').trim() || undefined,
      }))
      .filter((c) => c.title)
    const warn = Array.isArray(res?.warnings) ? res.warnings.filter(Boolean).join('；') : ''
    if (!res?.ok || !pack) {
      const err = String(res?.web_error || res?.error || '未检索到可用网页').trim()
      return { contextPack: '', citations, note: warn || err || '联网检索无结果' }
    }
    return {
      contextPack: pack,
      citations,
      note: warn || (res.via ? `已通过 ${res.via} 检索网页` : '已注入联网检索摘要'),
    }
  } catch (e: unknown) {
    const msg = formatDirectChatError(e)
    return {
      contextPack: '',
      citations: [],
      note: msg.includes('429') || msg.includes('频繁') ? '联网检索过于频繁，请稍后再试' : msg,
    }
  }
}
function buildDirectAttachItem(file: File): DirectAttachment {
  if (isImageFileForVision(file)) {
    const maxBytes = 20 * 1024 * 1024
    const tooBig = Number(file.size || 0) > maxBytes
    return {
      id: makeDirectAttachId(),
      name: file.name,
      size: file.size || 0,
      status: tooBig ? 'skipped' : 'uploading',
      purpose: 'vision',
      docId: '',
      imageDataUrl: '',
      error: tooBig ? `超过图片 ${formatDirectFileSize(maxBytes)} 上限` : '',
      ingesting: false,
      ingestError: '',
      file,
    }
  }
  const ext = directFileExt(file.name)
  const readEmp = resolveReadEmployeeForExtension(ext)
  if (readEmp) {
    const tooBig = Number(file.size || 0) > DIRECT_EMPLOYEE_FILE_MAX_BYTES
    if (tooBig) {
      return {
        id: makeDirectAttachId(),
        name: file.name,
        size: file.size || 0,
        status: 'skipped',
        purpose: 'employee',
        readEmployeeId: readEmp,
        docId: '',
        error: `超过员工通道 ${formatDirectFileSize(DIRECT_EMPLOYEE_FILE_MAX_BYTES)} 上限`,
        ingesting: false,
        ingestError: '',
        file,
      }
    }
    return {
      id: makeDirectAttachId(),
      name: file.name,
      size: file.size || 0,
      status: 'ready',
      purpose: 'employee',
      readEmployeeId: readEmp,
      docId: '',
      error: '',
      ingesting: false,
      ingestError: '',
      file,
    }
  }
  const supported = DIRECT_KB_SUPPORTED_EXT.has(ext)
  const tooBig = Number(file.size || 0) > DIRECT_KB_MAX_BYTES
  if (!supported) {
    return {
      id: makeDirectAttachId(),
      name: file.name,
      size: file.size || 0,
      status: 'skipped',
      docId: '',
      error: `不支持的格式（知识库：${DIRECT_KB_SUPPORTED_EXTENSIONS.join('/')}；读取员工：Excel/CSV/PDF/Word/PPT）`,
      ingesting: false,
      ingestError: '',
      file,
    }
  }
  if (tooBig) {
    return {
      id: makeDirectAttachId(),
      name: file.name,
      size: file.size || 0,
      status: 'skipped',
      docId: '',
      error: `超过 ${formatDirectFileSize(DIRECT_KB_MAX_BYTES)} 上限`,
      ingesting: false,
      ingestError: '',
      file,
    }
  }
  return {
    id: makeDirectAttachId(),
    name: file.name,
    size: file.size || 0,
    status: 'uploading',
    purpose: 'knowledge',
    docId: '',
    error: '',
    ingesting: false,
    ingestError: '',
    file,
  }
}
function appendAttachmentMentions(files: File[], target: 'direct' | 'make') {
  const names = (Array.isArray(files) ? files : [])
    .map((file) => String(file?.name || '').trim())
    .filter(Boolean)
  if (!names.length) return
  const startIndex = Math.max(0, directAttachedFiles.value.length - names.length)
  const mentions = names.map((name, idx) => `@附件${startIndex + idx + 1} ${name}`).join(' ')
  const r = target === 'make' ? draft : directDraft
  const current = String(r.value || '')
  const joiner = current.trim() ? (/\s$/.test(current) ? '' : ' ') : ''
  r.value = `${current}${joiner}${mentions} `
}
async function prepareDirectVisionFile(item: DirectAttachment): Promise<void> {
  try {
    const imageDataUrl = await compressImageFileToDataUrl(item.file, {
      maxEdge: 2048,
      maxBytes: 5 * 1024 * 1024,
    })
    const idx = directAttachedFiles.value.findIndex((x) => x.id === item.id)
    if (idx < 0) return
    directAttachedFiles.value[idx] = {
      ...directAttachedFiles.value[idx],
      status: 'ready',
      imageDataUrl,
      docId: '',
      error: '',
      ingesting: false,
      ingestError: '',
    }
  } catch (e) {
    const idx = directAttachedFiles.value.findIndex((x) => x.id === item.id)
    if (idx < 0) return
    directAttachedFiles.value[idx] = {
      ...directAttachedFiles.value[idx],
      status: 'error',
      imageDataUrl: '',
      error: e instanceof Error ? e.message : String(e || '图片处理失败'),
      ingesting: false,
      ingestError: '',
    }
  }
}
function userFacingOutputDownloads(
  downloads: Array<{ jobId: string; filename: string; label?: string }>,
) {
  return filterUserFacingOfficeDownloads(downloads)
}
function pushDirectGeneratedDownloads(
  downloads: Array<{ jobId: string; filename: string; label?: string }> | unknown,
) {
  const parsed = Array.isArray(downloads)
    ? parseEmployeeOutputDownloads({ output_downloads: downloads })
    : parseEmployeeOutputDownloads(downloads)
  if (!parsed.length) return
  const facing = filterUserFacingOfficeDownloads(parsed)
  const incoming = employeeDownloadsToGeneratedFiles(facing)
  if (!incoming.length) return
  directGeneratedFiles.value = mergeGeneratedFiles(directGeneratedFiles.value, incoming)
  butlerDownloadHistory.recordDownloads(facing, {
    employeeId: directChatEmployeeId.value || undefined,
  })
}
function cacheOfficeReadResults(
  conversationId: string,
  rawResults: Array<{ name: string; employeeId: string; result: unknown }>,
) {
  const id = String(conversationId || '').trim()
  if (!id || !rawResults?.length) return
  officeReadCacheByConversation.set(id, rawResults)
}
function getCachedOfficeReadResults(conversationId: string) {
  return officeReadCacheByConversation.get(String(conversationId || '').trim()) || []
}
function beginDirectGenerating(format: OfficeFormat, label = '生成中…') {
  directGeneratingFile.value = { active: true, format, label }
}
function clearDirectGenerating() {
  directGeneratingFile.value = null
}
async function runDirectOfficeGeneratePhase(
  opts: Parameters<typeof runOfficeGeneratePhase>[0],
) {
  beginDirectGenerating(opts.format)
  try {
    return await runOfficeGeneratePhase(opts)
  } finally {
    clearDirectGenerating()
  }
}
function removeDirectGeneratedFile(id: string) {
  directGeneratedFiles.value = directGeneratedFiles.value.filter((f) => f.id !== id)
}
async function downloadGeneratedOutput(f: DirectGeneratedFile) {
  await downloadOutput(f.jobId, f.filename, f.name)
}
async function removeDirectAttachedFile(id: string): Promise<void> {
  const item = directAttachedFiles.value.find((f) => f.id === id)
  if (!item) return
  if (item.status === 'uploading') return
  directAttachedFiles.value = directAttachedFiles.value.filter((f) => f.id !== id)
  if (item.docId) {
    try {
      await api.knowledgeDeleteDocument(item.docId)
    } catch {
      /* 移除知识库中的副本失败不影响 UI */
    }
  }
}
function persistConversations() {
  const list = conversations.value.slice()
  saveConversations(list)
  __wbState.syncingConvToSidebar = true
  wbSidebar.setConversations(list)
  __wbState.syncingConvToSidebar = false
}
function ensureActiveConversation(opts?: { forceNew?: boolean; bot?: AgentBot | null }): Conversation {
  if (!opts?.forceNew && activeConversation.value) return activeConversation.value
  const bot = opts?.bot ?? activeBot.value
  const conv = createConversation({
    title: '新对话',
    agentId: bot?.id,
    agentLabel: bot?.name,
  })
  if (bot?.opener) {
    conv.messages.push(makeMessage('assistant', bot.opener))
  }
  conversations.value = [conv, ...conversations.value]
  activeConversationId.value = conv.id
  saveActiveId(conv.id)
  wbSidebar.setActiveConversationId(conv.id)
  persistConversations()
  return conv
}
function patchActiveConversation(mutator: (c: Conversation) => void, conversationId?: string) {
  const id = conversationId || activeConversationId.value
  if (!id) return
  conversations.value = conversations.value.map((c) => {
    if (c.id !== id) return c
    const next: Conversation = { ...c, messages: c.messages.slice() }
    mutator(next)
    next.updatedAt = Date.now()
    return next
  })
  persistConversations()
}
function appendUserAndAssistant(userMsg: ChatMessage, assistantPlaceholder: ChatMessage) {
  const convId = activeConversationId.value
  if (!convId) return
  patchActiveConversation((c) => {
    c.messages.push(userMsg)
    c.messages.push(assistantPlaceholder)
    if (!c.title || c.title === '新对话') {
      c.title = buildConversationTitle(userMsg.content)
    }
  }, convId)
}
function updateAssistantMessage(id: string, mutator: (m: ChatMessage) => void) {
  patchActiveConversation((c) => {
    const idx = c.messages.findIndex((m) => m.id === id)
    if (idx < 0) return
    const next = { ...c.messages[idx] }
    mutator(next)
    c.messages[idx] = next
  })
}
function buildHumanChatStylePrompt(channel: 'text' | 'voice'): string {
  const parts = [
    '【自然对话风格】像一个有分寸、会接话的中文同事在聊天，而不是客服脚本或说明书。',
    '- 先回应用户这句话真正想要什么；有情绪时先接住情绪，再给信息。',
    '- 不要说「作为 AI/模型/系统」；不要用「很高兴为您服务」「请提供更多信息」这类空泛套话。',
    '- 短问题短答；复杂任务先给可执行建议，再问最多 1 个关键问题。',
    '- 沿用上下文称呼和口吻，不要每轮复述用户原话凑字数。',
    '- 信息不足时，说清楚缺哪一点，并顺手给一个可选方向。',
    '- 用户只是闲聊、吐槽、试探或一句很短的话时，先自然接住，不要立刻升级成任务、流程或表单。',
    '- 回答要有“上一轮听进去了”的感觉：必要时引用上下文里的具体点，但不要机械总结。',
    '- 若用户明确要求极简（如「只答 ok」「一句话」「不要解释」），严格遵守字数与格式，不要追加背景或延伸。',
  ]
  if (channel === 'voice') {
    parts.push(
      '语音回复优先 1-3 句，像真实对话一样自然停顿；用短句，少铺垫，不要使用 Markdown 标题、表格或长列表。',
    )
  } else {
    parts.push(
      '文字回复可以用 Markdown，但只有答案较长时才加标题；不要为了格式显得生硬。',
    )
  }
  return parts.join('\n')
}
function buildSystemPrompt(
  activeBotPersona: string,
  knowledgePack: string,
  inlineFiles?: Array<{ name: string; text: string }>,
  directEmployeeHint?: string,
  readPhaseNote?: string,
  userText?: string,
  webContextPack?: string,
): string {
  const parts: string[] = []
  const outputContract = detectOutputContract(userText || '')
  if (activeBotPersona) {
    parts.push(activeBotPersona)
  } else {
    parts.push('你是一个简洁直接的中文 AI 助手。优先给出可执行答案；如果信息不足，先给合理假设，再列出需要确认的问题。')
  }
  if (String(activeBot.value?.id || '') === 'customer-service') {
    const who = String(displayName.value || '').trim().slice(0, 32)
    if (who) {
      parts.push(
        `【当前对话对象】称呼=${who}。可自然称呼对方，勿复读整段内部字段，勿向访客复述敏感信息。`,
      )
    }
  }
  parts.push(buildHumanChatStylePrompt('text'))
  const contractRules = outputContractSystemRules(outputContract)
  if (contractRules) parts.push(contractRules)
  if (directEmployeeHint && directEmployeeHint.trim()) {
    parts.push(directEmployeeHint.trim())
  }
  if (readPhaseNote && readPhaseNote.trim()) {
    parts.push(readPhaseNote.trim())
  }
  if (personalSettings.value.memory && personalSettings.value.memory.trim()) {
    parts.push(`关于用户的长期记忆（请在回答中合理利用，但不要每次都重复念出）：\n${personalSettings.value.memory.trim()}`)
  }
  const hasEmployeeRead = (inlineFiles || []).some((f) => String(f.name || '').includes('读取员工解析'))
  if (inlineFiles && inlineFiles.length > 0) {
    const blocks = inlineFiles
      .map((f, idx) => `### @附件${idx + 1}：${f.name}\n\n${f.text}`)
      .join('\n\n---\n\n')
    const lead = hasEmployeeRead
      ? '以下包含「读取员工」用 direct_python 从用户原文件解析出的结构化/全文内容（非模型臆造）。你必须以这些解析结果为准回答；禁止编造表格单元格、CSV 行、PDF/Word 段落。若某段解析为空或报错，请如实说明并建议用户检查文件格式。'
      : '以下是用户按顺序直接上传的附件全文；用户消息里的 @附件1、@附件2 会对应这里的同序号文件。请按编号理解文件之间的先后逻辑，并优先据此回答。'
    parts.push(`${lead}\n\n${blocks}`)
  }
  if (knowledgePack) {
    parts.push(
      `以下是用户当前提问相关的资料库片段（来自其本人上传的文档），优先据此回答；若与提问无关请忽略：\n${knowledgePack}`,
    )
  }
  if (webContextPack && webContextPack.trim()) {
    parts.push(
      `【联网检索摘要 · 本轮注入】\n以下内容由系统在发送前从公开网页检索并抓取（Bing/Tavily/DDG 等），请优先参考并回答；必须在文末列出「参考链接」小节（标题 + URL）。若与附件或资料库冲突，以附件/资料库为准。\n\n${webContextPack.trim()}`,
    )
  }
  if (!outputContract) {
    parts.push('回答时使用 Markdown：标题用 ## / ###，列表用「-」或「1.」，代码用 ``` 包裹并标注语言；公式用 $$ 包裹；如需画图请用 ```mermaid 代码块。')
  }
  return parts.join('\n\n')
}
function _rebuildContextMessages(forSendUpToIndex?: number): Array<{ role: string; content: string }> {
  const msgs = directMessages.value
  const sliceEnd = typeof forSendUpToIndex === 'number' ? forSendUpToIndex + 1 : msgs.length
  return msgs.slice(0, sliceEnd).map((m) => ({ role: m.role, content: m.content }))
}
function directEmployeeSystemHint(): string {
  const office = officeEmployeeCapabilitySystemHint()
  const id = String(directChatEmployeeId.value || '').trim()
  if (!id) return office
  const picked = directEmployeeOptions.value.find((e) => e.id === id)
  const label = picked ? `${picked.name}（${picked.sourceLabel}）` : id
  return [
    office,
    `【一档测试绑定员工（单选）】当前绑定 id：${id}；显示：${label}。回答时请尽量贴合该员工职责与知识边界；若问题明显超出该角色，可简要说明后给出通用建议。`,
  ].join('\n\n')
}
function withRequestTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error('request_timeout')), ms)
    promise.then(
      (v) => {
        window.clearTimeout(timer)
        resolve(v)
      },
      (e) => {
        window.clearTimeout(timer)
        reject(e)
      },
    )
  })
}
function formatDirectChatError(e: unknown): string {
  let msg = e instanceof Error ? e.message : String(e ?? '生成失败')
  try {
    if (msg.trim().startsWith('{')) {
      const parsed = JSON.parse(msg)
      if (typeof parsed?.detail === 'string') msg = parsed.detail
    }
  } catch {
    /* keep msg */
  }
  if (msg.includes('未登录') || msg.includes('登录已过期')) return '登录已过期，请重新登录'
  return msg
}
function handleDirectChatAuthFailure() {
  clearAuthTokens()
  void router.push({ name: 'login', query: { redirect: router.currentRoute.value.fullPath || '/' } })
}
const DIRECT_KB_RETRIEVE_MS = 2500
const DIRECT_WEB_SEARCH_MS = 18_000
function markDirectFirstToken() {
  try {
    performance.mark('wb-direct-first-token')
    performance.measure('wb-direct-send-to-first-token', 'wb-direct-send', 'wb-direct-first-token')
  } catch {
    /* ignore */
  }
}
async function runDirectEmployeeReadForLlm(opts: {
  files: Array<{ file: File; name: string; readEmployeeId?: string }>
  userText?: string
  onProgress?: (line: string) => void
}): Promise<{
  inlineFiles: Array<{ name: string; text: string }>
  downloads: Array<{ jobId: string; filename: string; label?: string }>
  readErrors: string[]
  readSummary: string
}> {
  const inlineFiles: Array<{ name: string; text: string }> = []
  const downloads: Array<{ jobId: string; filename: string; label?: string }> = []
  const readErrors: string[] = []
  const summaryLines: string[] = []
  for (const item of opts.files) {
    const employeeId = resolveDirectFileEmployeeId(item)
    if (!employeeId) {
      readErrors.push(`${item.name}：未匹配读取员工`)
      continue
    }
    opts.onProgress?.(`正在用 **${readEmployeeDisplayName(employeeId)}** 解析 \`${item.name}\`…`)
    try {
      const res = await api.employeeExecuteFile(employeeId, item.file, {
        task: opts.userText ? '全量读取并供后续问答' : '全量读取',
        inputData: opts.userText ? { user_query: opts.userText } : {},
      })
      const llmText = extractEmployeeReadTextForLlm(res)
      if (!llmText.trim()) {
        readErrors.push(`${item.name}：读取员工未返回可用正文（可能执行失败或 outputs 为空）`)
        const { text } = formatEmployeeReadResultSummary(employeeId, item.name, res)
        summaryLines.push(text)
        continue
      }
      inlineFiles.push({
        name: `${item.name}（读取员工解析·${readEmployeeDisplayName(employeeId)}）`,
        text: llmText,
      })
      const { text } = formatEmployeeReadResultSummary(employeeId, item.name, res)
      summaryLines.push(text)
      downloads.push(...parseEmployeeOutputDownloads(res))
    } catch (e: unknown) {
      const msg = formatDirectChatError(e)
      readErrors.push(`${item.name}：${msg}`)
    }
  }
  return {
    inlineFiles,
    downloads,
    readErrors,
    readSummary: summaryLines.join('\n\n---\n\n'),
  }
}
function stopGeneration() {
  if (__wbState.currentStreamHandle) {
    __wbState.currentStreamHandle.abort()
  }
  directLoading.value = false
  directSendPending.value = false
  if (speakingMessageId.value) {
    stopDirectTtsPlayback()
    speakingMessageId.value = ''
    __wbState.ttsStreamAssistantId = ''
  }
}
async function downloadOutput(jobId: string, filename: string, label?: string) {
  try {
    const res = await api.employeeOutputDownload(jobId, filename)
    const url = URL.createObjectURL(res)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
    butlerDownloadHistory.recordSingle(
      jobId,
      filename,
      label || filename.split(/[/\\]/).pop() || filename,
      directChatEmployeeId.value || undefined,
    )
  } catch (e: unknown) {
    console.error('下载失败', e)
    const msg = e instanceof Error ? e.message : String(e)
    directError.value = `下载失败：${msg}。若对话中只有文字「下载」链接而无上方「已生成」卡片，请先发送「生成带动画的 pptx」或重新附上 PPT 后点发送。`
  }
}

  return {
    ...ctx, retrieveWebForDirect, buildDirectAttachItem, appendAttachmentMentions, prepareDirectVisionFile,
    userFacingOutputDownloads, pushDirectGeneratedDownloads, cacheOfficeReadResults, getCachedOfficeReadResults, beginDirectGenerating,
    clearDirectGenerating, runDirectOfficeGeneratePhase, removeDirectGeneratedFile, downloadGeneratedOutput, removeDirectAttachedFile,
    persistConversations, ensureActiveConversation, patchActiveConversation, appendUserAndAssistant, updateAssistantMessage,
    buildHumanChatStylePrompt, buildSystemPrompt, _rebuildContextMessages, directEmployeeSystemHint, withRequestTimeout,
    formatDirectChatError, handleDirectChatAuthFailure, DIRECT_KB_RETRIEVE_MS, DIRECT_WEB_SEARCH_MS, markDirectFirstToken,
    runDirectEmployeeReadForLlm, stopGeneration, downloadOutput,
  }
}

export type useWbBuildDirectAttachItemBinds = ReturnType<typeof useWbBuildDirectAttachItem>
