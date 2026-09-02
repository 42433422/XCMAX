import { api } from '../../api'
import type { ChatMessage } from '../../utils/conversationStore'
import { makeMessage } from '../../utils/conversationStore'
import { streamLLMChat } from '../../utils/llmStream'
import { softenSandboxDownloadLinks } from '../../utils/directGeneratedFiles'
import { directFileExt, resolveDirectAttachmentOutcome, resolveReadEmployeeForExtension } from '../../utils/directAttachments'
import type { useWbResolveChatProviderModel } from './useWbResolveChatProviderModel'
import type { DirectAttachment, DirectKbResult, DirectWebSearchResult } from './types'

// 拆分自 WorkbenchHomeView.vue（原行 4263–4341, 4374–4394, 4794–4951 …）；逐字迁移，行为不变。
export function useWbRunDirectChatTurn(ctx: ReturnType<typeof useWbResolveChatProviderModel>) {
  const {
    draft, __wbState, directAttachedFiles, directLoading, directSendPending, directError,
    ttsAutoRead, directWebSearchEnabled, directWebSearching, directMessages, directIsDragging, editingMessageId,
    editingDraft, streamingTts, activeBot, speakingMessageId, retrieveWebForDirect, applyDirectReadEmployeePick,
    buildDirectAttachItem, appendAttachmentMentions, prepareDirectVisionFile, userFacingOutputDownloads, pushDirectGeneratedDownloads, patchActiveConversation,
    updateAssistantMessage, buildSystemPrompt, directEmployeeSystemHint, formatDirectChatError, handleDirectChatAuthFailure, retrieveKnowledgeForDirect,
    markDirectFirstToken, directDragDepth, videoSizeForAspect, loadUsableMediaCatalog, placeholder, resolveChatProviderModel,
  } = ctx

async function uploadDirectAttachedFile(item: DirectAttachment): Promise<void> {
  let extractedText = ''
  try {
    const extractRes = await api.knowledgeExtractText(item.file)
    const outcome = resolveDirectAttachmentOutcome({ extractedText: extractRes?.text })
    const idx = directAttachedFiles.value.findIndex((x) => x.id === item.id)
    if (idx < 0) return
    if (!outcome.canSend) throw new Error(outcome.error)
    extractedText = outcome.extractedText
    directAttachedFiles.value[idx] = {
      ...directAttachedFiles.value[idx],
      status: 'inline',
      extractedText,
      docId: '',
      error: '',
      ingesting: true,
      ingestError: '',
    }
  } catch (e) {
    const idx = directAttachedFiles.value.findIndex((x) => x.id === item.id)
    if (idx < 0) return
    const outcome = resolveDirectAttachmentOutcome({ extractError: e })
    directAttachedFiles.value[idx] = {
      ...directAttachedFiles.value[idx],
      status: 'error',
      extractedText: '',
      docId: '',
      error: outcome.error,
      ingesting: false,
      ingestError: '',
    }
    return
  }

  try {
    const embeddingChoice = await resolveChatProviderModel()
    const res = await api.knowledgeUploadDocument(item.file, {
      embeddingProvider: embeddingChoice.provider,
      embeddingModel: embeddingChoice.model,
    })
    const docId = res?.document?.doc_id || res?.document?.docId || ''
    const idx = directAttachedFiles.value.findIndex((x) => x.id === item.id)
    if (idx < 0) {
      // 已被移除：尝试回收资料库中的副本，避免脏数据
      if (docId) {
        try {
          await api.knowledgeDeleteDocument(docId)
        } catch {
          /* ignore cleanup error */
        }
      }
      return
    }
    const outcome = resolveDirectAttachmentOutcome({ extractedText, docId, uploadError: docId ? undefined : '上传未返回文档 ID' })
    directAttachedFiles.value[idx] = {
      ...directAttachedFiles.value[idx],
      status: outcome.status,
      docId: outcome.docId,
      extractedText: outcome.extractedText,
      error: outcome.error,
      ingesting: false,
      ingestError: outcome.ingestError,
      embedding: res?.embedding || null,
    }
  } catch (e) {
    const idx = directAttachedFiles.value.findIndex((x) => x.id === item.id)
    if (idx < 0) return
    const outcome = resolveDirectAttachmentOutcome({ extractedText, uploadError: e })
    directAttachedFiles.value[idx] = {
      ...directAttachedFiles.value[idx],
      status: outcome.status,
      docId: '',
      extractedText: outcome.extractedText,
      error: outcome.error,
      ingesting: false,
      ingestError: outcome.ingestError,
    }
  }
}
function onDirectFilesChange(e: Event): void {
  const input = e?.target as HTMLInputElement | null
  if (!input || typeof input.files === 'undefined') return
  const picked: File[] = Array.from(input.files || [])
  input.value = ''
  if (!picked.length) return
  const maxFiles = 12
  const remaining = Math.max(0, maxFiles - directAttachedFiles.value.length)
  const accepted = picked.slice(0, remaining)
  const items = accepted.map((file: File) => buildDirectAttachItem(file))
  const firstRead = items.find((it) => it.readEmployeeId)
  if (firstRead?.readEmployeeId) applyDirectReadEmployeePick(firstRead.readEmployeeId)
  directAttachedFiles.value = [...directAttachedFiles.value, ...items]
  appendAttachmentMentions(accepted, 'direct')
  for (const it of items) {
    if (it.status === 'uploading') {
      if (it.purpose === 'vision') void prepareDirectVisionFile(it)
      else void uploadDirectAttachedFile(it)
    }
  }
}
async function runDirectChatTurn(opts: {
  userMsg?: ChatMessage
  assistantId: string
  userText: string
  inlineFiles?: Array<{ name: string; text: string }>
  readPhaseNote?: string
  outputDownloads?: Array<{ jobId: string; filename: string; label?: string }>
}) {
  directError.value = ''
  directSendPending.value = false
  directLoading.value = true
  let firstTokenMarked = false
  let kbResult: DirectKbResult | null = null
  let webResult: DirectWebSearchResult | null = null
  const hasOutputDownloads = userFacingOutputDownloads(opts.outputDownloads || []).length > 0
  const polishAssistantContent = (raw: string) => {
    let s = String(raw || '')
    if (/sandbox:|file:\/\//i.test(s)) s = softenSandboxDownloadLinks(s)
    if (hasOutputDownloads && !/见下方文件卡片/.test(s)) {
      s = s ? `${s}\n\n_可下载文件见下方按钮或输入框上方「已生成」卡片。_` : '_可下载文件见下方按钮或输入框上方「已生成」卡片。_'
    }
    return s
  }
  try {
    const needVision = directMessages.value.some((m) =>
      m.id !== opts.assistantId &&
      Array.isArray(m.multimodalContent) &&
      m.multimodalContent.some((p) => p?.type === 'image_url'),
    )
    const resolvePromise = resolveChatProviderModel({ needVision })
    const kbPromise = opts.userText
      ? resolvePromise.then(({ provider, model }) =>
          retrieveKnowledgeForDirect(opts.userText, provider, model).then((r) => {
            kbResult = r
          }),
        )
      : Promise.resolve()
    const webPromise =
      directWebSearchEnabled.value && opts.userText.trim()
        ? (async () => {
            directWebSearching.value = true
            try {
              webResult = await retrieveWebForDirect(opts.userText)
            } finally {
              directWebSearching.value = false
            }
          })()
        : Promise.resolve()

    const { provider, model } = await resolvePromise
    await Promise.all([kbPromise, webPromise])
    const resolvedKb = kbResult as DirectKbResult | null
    const resolvedWeb = webResult as DirectWebSearchResult | null

    const readNoteParts = [opts.readPhaseNote, resolvedWeb?.note].filter(Boolean)
    const sys = buildSystemPrompt(
      activeBot.value?.persona || '',
      resolvedKb?.knowledgePack || '',
      opts.inlineFiles,
      directEmployeeSystemHint(),
      readNoteParts.length ? readNoteParts.join('；') : undefined,
      opts.userText,
      resolvedWeb?.contextPack,
    )
    const ctx = directMessages.value
      .filter((m) => m.id !== opts.assistantId)
      .map((m) => ({
        role: m.role,
        content: Array.isArray(m.multimodalContent) ? m.multimodalContent : m.content,
      }))
    const msgs = [{ role: 'system', content: sys }, ...ctx]
    if (ttsAutoRead.value) {
      streamingTts.stop()
      streamingTts.resetStream()
      __wbState.ttsStreamAssistantId = opts.assistantId
      speakingMessageId.value = opts.assistantId
    }
    const handle = streamLLMChat({
      provider,
      model,
      messages: msgs,
      maxTokens: 2048,
      onToken: (_delta, soFar) => {
        if (soFar.trim() && !firstTokenMarked) {
          firstTokenMarked = true
          markDirectFirstToken()
        }
        updateAssistantMessage(opts.assistantId, (m) => {
          m.content = polishAssistantContent(soFar)
          m.pending = true
        })
        if (ttsAutoRead.value && __wbState.ttsStreamAssistantId === opts.assistantId) {
          streamingTts.feed(polishAssistantContent(soFar))
        }
      },
      onError: (e) => {
        const msg = formatDirectChatError(e)
        if (msg.includes('登录已过期')) handleDirectChatAuthFailure()
        directError.value = msg
        updateAssistantMessage(opts.assistantId, (m) => {
          m.pending = false
          m.error = msg
          if (!m.content) m.content = msg
        })
      },
      onDone: (full, aborted) => {
        const cits = resolvedKb?.citations ?? []
        updateAssistantMessage(opts.assistantId, (m) => {
          m.pending = false
          if (aborted) {
            m.content = m.content ? `${m.content}\n\n_（已中断）_` : '_（已中断）_'
          } else if (full) {
            m.content = polishAssistantContent(full)
          }
          if (cits.length) m.citations = cits
          if (opts.outputDownloads?.length) {
            const facing = userFacingOutputDownloads(opts.outputDownloads)
            if (facing.length) {
              m.outputDownloads = facing
              pushDirectGeneratedDownloads(facing)
            }
          }
        })
        if (ttsAutoRead.value && __wbState.ttsStreamAssistantId === opts.assistantId) {
          if (aborted) {
            streamingTts.stop()
          } else {
            streamingTts.finish(polishAssistantContent(full))
          }
          speakingMessageId.value = ''
          __wbState.ttsStreamAssistantId = ''
        }
      },
    })
    __wbState.currentStreamHandle = handle
    await handle.done
    await kbPromise
    const lateCits = resolvedKb?.citations ?? []
    if (lateCits.length) {
      updateAssistantMessage(opts.assistantId, (m) => {
        if (!m.citations?.length) m.citations = lateCits
      })
    }
  } catch (e: unknown) {
    const msg = formatDirectChatError(e)
    if (msg.includes('登录已过期')) handleDirectChatAuthFailure()
    directError.value = msg
    updateAssistantMessage(opts.assistantId, (m) => {
      m.pending = false
      m.error = msg
      if (!m.content) m.content = msg
    })
  } finally {
    __wbState.currentStreamHandle = null
    directLoading.value = false
    directSendPending.value = false
  }
}
async function regenerateAssistant(messageId: string) {
  if (directLoading.value) return
  const msgs = directMessages.value
  const idx = msgs.findIndex((m) => m.id === messageId)
  if (idx <= 0) return
  let userIdx = -1
  for (let i = idx - 1; i >= 0; i -= 1) {
    if (msgs[i].role === 'user') {
      userIdx = i
      break
    }
  }
  if (userIdx < 0) return
  const userText = msgs[userIdx].content
  patchActiveConversation((c) => {
    c.messages.splice(idx, 1)
  })
  const placeholder = makeMessage('assistant', '', { pending: true })
  patchActiveConversation((c) => {
    c.messages.push(placeholder)
  })
  await runDirectChatTurn({ assistantId: placeholder.id, userText })
}
async function commitEditedUserMessage() {
  const id = editingMessageId.value
  const draft = String(editingDraft.value || '').trim()
  if (!id || !draft) {
    editingMessageId.value = ''
    editingDraft.value = ''
    return
  }
  const idx = directMessages.value.findIndex((m) => m.id === id)
  if (idx < 0) {
    editingMessageId.value = ''
    return
  }
  patchActiveConversation((c) => {
    c.messages[idx] = { ...c.messages[idx], content: draft }
    c.messages.splice(idx + 1)
  })
  editingMessageId.value = ''
  editingDraft.value = ''
  const placeholder = makeMessage('assistant', '', { pending: true })
  patchActiveConversation((c) => {
    c.messages.push(placeholder)
  })
  await runDirectChatTurn({ assistantId: placeholder.id, userText: draft })
}
function setFilePurpose(fileId: string, purpose: string) {
  const f = directAttachedFiles.value.find((a) => String(a.id) === fileId)
  if (!f) return
  f.purpose = purpose
  if (purpose === 'employee') {
    const readId = resolveReadEmployeeForExtension(directFileExt(String(f.name || '')))
    if (readId) {
      f.readEmployeeId = readId
      applyDirectReadEmployeePick(readId)
    }
    if (f.status === 'uploading') {
      f.status = 'ready'
      f.docId = ''
      f.ingesting = false
      f.ingestError = ''
    }
  } else if (purpose === 'knowledge' && f.status === 'ready' && f.file && !f.extractedText && !f.docId) {
    f.status = 'uploading'
    void uploadDirectAttachedFile(f)
  }
}
function onComposerPaste(e: ClipboardEvent) {
  const items = e.clipboardData?.items
  if (!items?.length) return
  const images: File[] = []
  for (const it of Array.from(items)) {
    if (it.kind === 'file') {
      const f = it.getAsFile()
      if (f && f.type.startsWith('image/')) images.push(f)
    }
  }
  if (!images.length) return
  e.preventDefault()
  void ingestComposerFiles(images)
}
function onSurfaceDrop(e: DragEvent) {
  directDragDepth.value = 0
  directIsDragging.value = false
  const list = e.dataTransfer?.files
  if (!list?.length) return
  e.preventDefault()
  void ingestComposerFiles(Array.from(list))
}
async function ingestComposerFiles(files: File[], target: 'direct' | 'make' = 'direct') {
  const remaining = Math.max(0, 12 - directAttachedFiles.value.length)
  const accepted = files.slice(0, remaining)
  const items = accepted.map((file) => buildDirectAttachItem(file))
  const firstRead = items.find((it) => it.readEmployeeId)
  if (firstRead?.readEmployeeId) applyDirectReadEmployeePick(firstRead.readEmployeeId)
  directAttachedFiles.value = [...directAttachedFiles.value, ...items]
  appendAttachmentMentions(accepted, target)
  for (const it of items) {
    if (it.status === 'uploading') {
      if (it.purpose === 'vision') void prepareDirectVisionFile(it)
      else void uploadDirectAttachedFile(it)
    }
  }
}
const mediaGenRunner = {
  async generateImages(prompt: string, opts: { size: string; style: string; count: number }) {
    const safePrompt = prompt.slice(0, 240)
    const styled = opts.style && opts.style !== 'default' ? `${opts.style} 风格，` : ''
    const mediaCatalog = await loadUsableMediaCatalog()
    const { resolveMediaProviderModel } = await import('../../llmMedia')
    const { provider, model } = resolveMediaProviderModel('image', mediaCatalog)
    if (!model) {
      throw new Error('未找到可用的生图模型，请在「资金与记录 → 大模型 API」中选择含生图模型的厂商并刷新目录')
    }
    const res = await api.llmGenerateImage(provider, model, `${styled}${safePrompt}`, {
      size: opts.size,
      count: opts.count,
    })
    const urls = Array.isArray(res?.images) ? res.images.filter(Boolean) : []
    if (!urls.length) throw new Error('生图模型没有返回图片，请检查供应商返回或模型配置')
    return urls
  },
  async generatePptOutline(topic: string, audience: string, pages: number) {
    const { provider, model } = await resolveChatProviderModel()
    const sys = '你是高级 PPT 大纲编写者。为给定主题生成精炼的 markdown 大纲：每页用 ## 标题，下方 3-5 个要点（- 开头），并附 1 行口播说明。控制在指定页数内。'
    const usr = `主题：${topic}\n受众/风格：${audience || '通用商务'}\n页数：${pages}\n请直接输出 markdown 大纲。`
    const res = await api.llmChat(provider, model, [
      { role: 'system', content: sys },
      { role: 'user', content: usr },
    ], 1800)
    return String(res?.content || '').trim() || '（无输出）'
  },
  async generatePptx(topic: string, markdown: string) {
    return await api.llmGeneratePptxBlob(topic, markdown, `${topic.slice(0, 32) || 'ai-presentation'}.pptx`)
  },
  async generateDocument(kind: string, inputs: string) {
    const { provider, model } = await resolveChatProviderModel()
    const kindMap: Record<string, string> = {
      weekly: '周报',
      proposal: '商业方案/提案',
      article: '公众号文章',
      redbook: '小红书种草文案',
      email: '商务邮件',
    }
    const sys = `你是擅长写「${kindMap[kind] || kind}」的中文写手。结构清晰、节奏流畅、有重点；输出 markdown，必要时用列表与小标题。不要套话，先抓重点。`
    const usr = `信息素材：${inputs}\n请直接输出成稿。`
    const res = await api.llmChat(provider, model, [
      { role: 'system', content: sys },
      { role: 'user', content: usr },
    ], 2200)
    return String(res?.content || '').trim() || '（无输出）'
  },
  async generateVideo(prompt: string, opts: { aspect: string; durationSec: number }) {
    const safePrompt = prompt.slice(0, 240)
    const mediaCatalog = await loadUsableMediaCatalog()
    const { resolveMediaProviderModel } = await import('../../llmMedia')
    const { provider, model } = resolveMediaProviderModel('video', mediaCatalog)
    if (!provider || !model) {
      throw new Error('未找到可用的生视频模型，请在「资金与记录 → 大模型 API」中配置含生视频模型的厂商并刷新目录')
    }
    const res = await api.llmGenerateVideo(provider, model, safePrompt, {
      size: videoSizeForAspect(opts.aspect),
      seconds: opts.durationSec,
    })
    const status = String(res?.status || 'pending')
    const jobId = String(res?.job_id || '')
    const previewUrl = String(res?.preview_url || '')
    const lines = [
      `任务状态：${status}`,
      jobId ? `任务 ID：${jobId}` : '',
      previewUrl ? `预览地址：${previewUrl}` : '视频任务已提交，上游生成完成后请按供应商任务状态查看结果。',
    ].filter(Boolean)
    return {
      status: status as 'pending' | 'succeeded' | 'failed' | 'processing',
      message: lines.join('\n'),
      previewUrl,
    }
  },
}

  return {
    ...ctx, uploadDirectAttachedFile, onDirectFilesChange, runDirectChatTurn, regenerateAssistant,
    commitEditedUserMessage, setFilePurpose, onComposerPaste, onSurfaceDrop, ingestComposerFiles,
    mediaGenRunner,
  }
}

export type useWbRunDirectChatTurnBinds = ReturnType<typeof useWbRunDirectChatTurn>
