import type { ChatAttachmentMeta } from '../../utils/conversationStore'
import { saveActiveId, makeMessage } from '../../utils/conversationStore'
import { applyVoiceSessionPatch, classifyVoiceTurn } from '../../composables/voiceSessionAgent'
import { stripInternalMarkers } from '../../utils/lightMarkdown'
import { directFileExt } from '../../utils/directAttachments'
import { buildUserMultimodalContent } from '../../utils/visionMultimodal'
import { employeeAcceptsFileExtension, employeeFileMismatchHint } from '../../utils/tabularReadEmployees'
import { assistantGaveManualOfficeStepsOnly, assistantImpliesPendingFileGeneration, classifyOfficeTask, collectOfficeAttachmentNamesFromMessages, collectRecentUserIntentText, detectOfficeEnhanceAttachedIntent, detectUserMissingDeliverableComplaint, mergeOfficeAttachmentNames, officeGenerateMissingInputMessage, pickPptTemplateFromSources, primaryOfficeFormatFromAttachments, shouldRecoverOfficeGenerate } from '../../utils/officeEmployeeOrchestration'
import { pickGenerateFormat, runOfficeReadPhase } from '../../utils/officeEmployeeRunner'
import type { useWbRunDirectChatTurn } from './useWbRunDirectChatTurn'

// 拆分自 WorkbenchHomeView.vue（原行 5006–5488, 6122–6130, 6132–6136 …）；逐字迁移，行为不变。
export function useWbSendDirectChat(ctx: ReturnType<typeof useWbRunDirectChatTurn>) {
  const {
    wbSidebar, composerIntent, directDraft, directAttachedFiles, directLoading, directSendPending,
    directError, directChatEmployeeId, directImageGenEnabled, directVideoGenEnabled, directMediaGenerating, directImageSize,
    directImageStyle, directImageCount, directVideoAspect, directVideoDurationSec, activeConversationId, directMessages,
    voiceMessages, voiceSessionState, directAttachmentNote, resolveDirectFileEmployeeId, userFacingOutputDownloads, pushDirectGeneratedDownloads,
    cacheOfficeReadResults, getCachedOfficeReadResults, runDirectOfficeGeneratePhase, ensureActiveConversation, appendUserAndAssistant, updateAssistantMessage,
    formatDirectChatError, handleDirectChatAuthFailure, runDirectChatTurn, mediaGenRunner, buildVoiceRouteContext, requireLoginForWorkbenchUse,
    placeholder, resolveChatProviderModel,
  } = ctx

async function sendDirectChat(text = '') {
  if (directAttachedFiles.value.some((f) => f.status === 'uploading')) {
    directError.value = '附件仍在上传中，请稍候'
    return
  }
  const userText = String(text || directDraft.value || '').trim()
  const filesSnapshot = [...directAttachedFiles.value]
  const employeeFiles = filesSnapshot.filter(
    (f) => f.purpose === 'employee' && f.status === 'ready' && f.file instanceof File,
  )
  const visionFiles = filesSnapshot.filter(
    (f) => f.purpose === 'vision' && f.status === 'ready' && typeof f.imageDataUrl === 'string' && f.imageDataUrl,
  )
  const knowledgeFiles = filesSnapshot.filter((f) => f.purpose !== 'employee' && f.purpose !== 'vision')
  const note = directAttachmentNote(filesSnapshot)
  let userContent = userText
  if (!userContent && visionFiles.length) {
    userContent = '请描述这些图片并回答我的问题。'
  }
  if (note) userContent = userContent ? `${userContent}\n\n${note}` : note
  if (!userContent && employeeFiles.length) {
    userContent = note || '请全量读取以上附件'
  }
  if (!userContent || directLoading.value) return
  if (!requireLoginForWorkbenchUse()) return
  if ((directImageGenEnabled.value || directVideoGenEnabled.value) && !userText) {
    directError.value = '生图/生视频需要文字描述，请在输入框填写后发送'
    return
  }

  for (const f of employeeFiles) {
    const eid = resolveDirectFileEmployeeId(f)
    const ext = directFileExt(f.name)
    if (!eid || !employeeAcceptsFileExtension(eid, ext)) {
      const hint = eid ? employeeFileMismatchHint(eid, ext) : employeeFileMismatchHint(directChatEmployeeId.value, ext)
      directError.value = `${f.name}：${hint}`
      return
    }
  }

  const conv = ensureActiveConversation()
  if (activeConversationId.value !== conv.id) {
    activeConversationId.value = conv.id
    saveActiveId(conv.id)
    wbSidebar.setActiveConversationId(conv.id)
  }
  directDraft.value = ''
  directError.value = ''

  const multimodalContent = buildUserMultimodalContent(
    userContent,
    visionFiles.map((f) => String(f.imageDataUrl || '')).filter(Boolean),
  )
  const userMsg = makeMessage('user', userContent, {
    skills: [],
    ...(Array.isArray(multimodalContent) ? { multimodalContent } : {}),
    attachments: filesSnapshot.map((f): ChatAttachmentMeta => ({
      name: f.name,
      size: f.size,
      status: f.status,
      docId: f.docId,
      kind: f.purpose === 'vision' ? 'vision' : 'file',
    })),
  })
  const inlineFiles = knowledgeFiles
    .filter((f) => (f.status === 'inline' || f.status === 'ready') && f.extractedText)
    .map((f) => ({ name: f.name, text: f.extractedText as string }))

  const placeholder = makeMessage('assistant', '', { pending: true })
  appendUserAndAssistant(userMsg, placeholder)
  directAttachedFiles.value = []
  directSendPending.value = true
  try {
    performance.mark('wb-direct-send')
  } catch {
    /* ignore */
  }

  if (directImageGenEnabled.value) {
    directSendPending.value = false
    directLoading.value = true
    directMediaGenerating.value = true
    updateAssistantMessage(placeholder.id, (m) => {
      m.pending = true
      m.content = '正在生成图片…'
    })
    try {
      const urls = await mediaGenRunner.generateImages(userText, {
        size: directImageSize.value,
        style: directImageStyle.value,
        count: directImageCount.value,
      })
      const list = Array.isArray(urls) ? urls.filter(Boolean) : []
      const md = list.map((u, i) => `![生成图${i + 1}](${u})`).join('\n')
      updateAssistantMessage(placeholder.id, (m) => {
        m.pending = false
        m.agentLabel = 'AI 创作'
        m.content = list.length
          ? `（AI 生图）${userText}\n\n${md}`
          : `（AI 生图）${userText}\n\n未返回图片，请检查模型配置后重试。`
      })
    } catch (e: unknown) {
      const msg = formatDirectChatError(e)
      if (msg.includes('登录已过期')) handleDirectChatAuthFailure()
      directError.value = msg
      updateAssistantMessage(placeholder.id, (m) => {
        m.pending = false
        m.error = msg
        m.content = msg
      })
    } finally {
      directLoading.value = false
      directMediaGenerating.value = false
    }
    return
  }

  if (directVideoGenEnabled.value) {
    directSendPending.value = false
    directLoading.value = true
    directMediaGenerating.value = true
    updateAssistantMessage(placeholder.id, (m) => {
      m.pending = true
      m.content = '正在提交生视频任务…'
    })
    try {
      const res = await mediaGenRunner.generateVideo(userText, {
        aspect: directVideoAspect.value,
        durationSec: directVideoDurationSec.value,
      })
      const body = [res.message]
      if (res.previewUrl) body.push(`预览：${res.previewUrl}`)
      updateAssistantMessage(placeholder.id, (m) => {
        m.pending = false
        m.agentLabel = 'AI 创作'
        m.content = `（AI 生视频）${userText}\n\n${body.filter(Boolean).join('\n\n')}`
      })
    } catch (e: unknown) {
      const msg = formatDirectChatError(e)
      if (msg.includes('登录已过期')) handleDirectChatAuthFailure()
      directError.value = msg
      updateAssistantMessage(placeholder.id, (m) => {
        m.pending = false
        m.error = msg
        m.content = msg
      })
    } finally {
      directLoading.value = false
      directMediaGenerating.value = false
    }
    return
  }

  const allAttachNames = filesSnapshot.map((f) => f.name)
  const conversationAttachNames = collectOfficeAttachmentNamesFromMessages(directMessages.value)
  const officeAttachNames = mergeOfficeAttachmentNames(allAttachNames, conversationAttachNames)
  const conversationUserText = collectRecentUserIntentText(directMessages.value)
  const officeTask = classifyOfficeTask(userText, officeAttachNames, { conversationUserText })
  const cachedReadResults = getCachedOfficeReadResults(conv.id)
  const missingDeliverable = detectUserMissingDeliverableComplaint(userText)

  if (missingDeliverable && cachedReadResults.length && !employeeFiles.length) {
    directSendPending.value = false
    directLoading.value = true
    const fmt = pickGenerateFormat(`${userText}\n${conversationUserText}`, officeAttachNames)
    updateAssistantMessage(placeholder.id, (m) => {
      m.pending = true
      m.content = '**补跑生成**：正在根据已读取的附件调用 PPT/Office 生成员产出可下载文件…'
    })
    try {
      const genPhase = await runDirectOfficeGeneratePhase({
        format: fmt,
        userText: userText || conversationUserText,
        readResults: cachedReadResults,
        extraAttachmentFiles: [],
        templateFile: pickPptTemplateFromSources(
          filesSnapshot
            .filter((f) => f.file instanceof File)
            .map((f) => ({ name: f.name, file: f.file as File })),
        ),
      })
      if (genPhase.errors.length && !genPhase.downloads.length) {
        const msg = genPhase.errors.join('；')
        directError.value = msg
        updateAssistantMessage(placeholder.id, (m) => {
          m.pending = false
          m.error = msg
          m.content = msg
        })
      } else {
        pushDirectGeneratedDownloads(genPhase.downloads)
        const facing = userFacingOutputDownloads(genPhase.downloads)
        updateAssistantMessage(placeholder.id, (m) => {
          m.pending = false
          m.content = [
            genPhase.summary,
            facing.length
              ? '请在输入框上方「已生成」卡片或下方按钮下载 **output.pptx**（含模板增强与动画），勿使用对话里的占位下载链接。'
              : '',
          ]
            .filter(Boolean)
            .join('\n\n')
          if (facing.length) m.outputDownloads = facing
        })
      }
    } catch (e: unknown) {
      const msg = formatDirectChatError(e)
      if (msg.includes('登录已过期')) handleDirectChatAuthFailure()
      directError.value = msg
      updateAssistantMessage(placeholder.id, (m) => {
        m.pending = false
        m.error = msg
        m.content = msg
      })
    } finally {
      directLoading.value = false
      directSendPending.value = false
    }
    return
  }

  if (officeTask === 'generate' && !employeeFiles.length) {
    directSendPending.value = false
    directLoading.value = true
    const fmt = pickGenerateFormat(userText, officeAttachNames)
    const stepTotal = 2
    const extraFiles = filesSnapshot
      .filter((f) => f.file instanceof File)
      .map((f) => f.file as File)
    updateAssistantMessage(placeholder.id, (m) => {
      m.pending = true
      m.content = cachedReadResults.length
        ? `**步骤 1/${stepTotal}**：正在根据已读取的附件调用生成员工产出可下载文件…`
        : `**步骤 1/${stepTotal}**：正在用生成员工根据您的描述产出可下载文件（支持纯文本 / JSON 模板）…`
    })
    try {
      const genPhase = await runDirectOfficeGeneratePhase({
        format: fmt,
        userText,
        readResults: cachedReadResults,
        extraAttachmentFiles: extraFiles,
        templateFile: pickPptTemplateFromSources(
          extraFiles.map((f) => ({ name: f.name, file: f })),
        ),
      })
      if (genPhase.errors.length && !genPhase.downloads.length) {
        const msg = genPhase.errors.join('；')
        directError.value = msg
        updateAssistantMessage(placeholder.id, (m) => {
          m.pending = false
          m.error = msg
          m.content = genPhase.summary || msg
        })
        directLoading.value = false
        return
      }
      pushDirectGeneratedDownloads(genPhase.downloads)
      updateAssistantMessage(placeholder.id, (m) => {
        m.pending = true
        m.content = `${genPhase.summary}\n\n**步骤 2/${stepTotal}**：正在根据生成结果由 AI 解读…`
        const facingGen = userFacingOutputDownloads(genPhase.downloads)
        if (facingGen.length) m.outputDownloads = facingGen
      })
      await runDirectChatTurn({
        userMsg,
        assistantId: placeholder.id,
        userText:
          userText ||
          '请根据上方生成结果简要说明产出文件用途；用户可在输入框上方「已生成」文件卡片中下载。',
        inlineFiles,
        readPhaseNote:
          '生成阶段已完成：用户已在输入框上方看到「已生成」文件卡片，请引导其点击卡片下载；勿输出 sandbox: 链接，勿声称无法提供 Office 文件。',
        outputDownloads: userFacingOutputDownloads(genPhase.downloads),
      })
    } catch (e: unknown) {
      const msg = formatDirectChatError(e)
      if (msg.includes('登录已过期')) handleDirectChatAuthFailure()
      directError.value = msg
      updateAssistantMessage(placeholder.id, (m) => {
        m.pending = false
        m.error = msg
        m.content = msg
      })
    } finally {
      directLoading.value = false
      directSendPending.value = false
    }
    return
  }

  if (employeeFiles.length) {
    directSendPending.value = false
    directLoading.value = true
    let wantGenerate = officeTask === 'generate'
    if (
      !wantGenerate &&
      primaryOfficeFormatFromAttachments(officeAttachNames) === 'ppt' &&
      detectOfficeEnhanceAttachedIntent(`${userText}\n${conversationUserText}`, officeAttachNames)
    ) {
      wantGenerate = true
    }
    const stepTotal = wantGenerate ? 3 : 2
    updateAssistantMessage(placeholder.id, (m) => {
      m.pending = true
      m.content = `**步骤 1/${stepTotal}**：正在用读取员工全量解析附件（direct_python，非编造）…`
    })
    let readPhase: Awaited<ReturnType<typeof runOfficeReadPhase>> | null = null
    try {
      readPhase = await runOfficeReadPhase({
        files: employeeFiles.map((f) => ({
          file: f.file as File,
          name: f.name,
          readEmployeeId: f.readEmployeeId,
        })),
        userText,
        resolveReadEmployeeId: resolveDirectFileEmployeeId,
        onProgress: (line) => {
          updateAssistantMessage(placeholder.id, (m) => {
            m.pending = true
            m.content = `**步骤 1/${stepTotal}**：${line}`
          })
        },
      })
      if (readPhase?.rawResults?.length) {
        cacheOfficeReadResults(conv.id, readPhase.rawResults)
      }
    } catch (e: unknown) {
      const msg = formatDirectChatError(e)
      if (msg.includes('登录已过期')) handleDirectChatAuthFailure()
      directError.value = msg
      updateAssistantMessage(placeholder.id, (m) => {
        m.pending = false
        m.error = msg
        m.content = msg
      })
      directLoading.value = false
      directSendPending.value = false
      return
    }
    const empInline = readPhase?.inlineFiles || []
    const readErrors = readPhase?.readErrors || []
    let allDownloads = userFacingOutputDownloads(readPhase?.downloads || [])
    let genSummary = ''
    if (wantGenerate && readPhase?.rawResults?.length) {
      updateAssistantMessage(placeholder.id, (m) => {
        m.pending = true
        m.content = `**步骤 2/${stepTotal}**：正在调用生成员工产出可下载文件…`
        if (allDownloads.length) m.outputDownloads = allDownloads
      })
      const genFmt = pickGenerateFormat(userText, officeAttachNames)
      const genPhase = await runDirectOfficeGeneratePhase({
        format: genFmt,
        userText,
        readResults: readPhase.rawResults,
        templateFile: pickPptTemplateFromSources(
          employeeFiles.map((f) => ({ name: f.name, file: f.file as File })),
        ),
      })
      genSummary = genPhase.summary
      allDownloads = userFacingOutputDownloads([...allDownloads, ...genPhase.downloads])
      pushDirectGeneratedDownloads(genPhase.downloads)
      if (genPhase.errors.length && !genPhase.downloads.length) {
        readErrors.push(...genPhase.errors)
      }
    }
    if (!empInline.length && !allDownloads.length) {
      const msg =
        readErrors.join('；') || '读取员工未能解析出可用内容，请确认已部署对应员工包且服务器依赖（openpyxl/pypdf/python-docx）已安装'
      directError.value = msg
      updateAssistantMessage(placeholder.id, (m) => {
        m.pending = false
        m.error = msg
        m.content = readPhase?.readSummary || msg
        if (allDownloads.length) m.outputDownloads = allDownloads
      })
      directLoading.value = false
      directSendPending.value = false
      return
    }
    const readNote =
      readErrors.length > 0
        ? `读取/生成阶段部分失败：${readErrors.join('；')}`
        : wantGenerate && allDownloads.length
          ? '读取与生成已完成：用户可在输入框上方「已生成」文件卡片中下载 Office 文件；对话回答仅作解读，勿输出 sandbox: 链接，勿声称无法提供文件。'
          : '读取阶段已完成：以下附件正文来自读取员工真实解析。'
    const summaryBlock = [readPhase?.readSummary, genSummary].filter(Boolean).join('\n\n---\n\n')
    updateAssistantMessage(placeholder.id, (m) => {
      m.pending = true
      m.content = `${summaryBlock}\n\n**步骤 ${stepTotal}/${stepTotal}**：正在根据解析结果由 AI 分析回答…`
      if (allDownloads.length) m.outputDownloads = allDownloads
    })
    const combinedInline = [...empInline, ...inlineFiles]
    const llmUserText =
      userText ||
      (wantGenerate
        ? '请根据上方读取/生成结果简要说明产出文件用途与结构要点；用户可点击下载。'
        : '请根据上方「读取员工解析」的附件内容回答：先简要概括文件结构/要点，再按用户后续意图给出可执行建议。禁止编造未出现在解析中的数据。')
    await runDirectChatTurn({
      userMsg,
      assistantId: placeholder.id,
      userText: llmUserText,
      inlineFiles: combinedInline,
      readPhaseNote: readNote,
      outputDownloads: allDownloads,
    })
    return
  }

  await runDirectChatTurn({ userMsg, assistantId: placeholder.id, userText, inlineFiles })
  const assistantAfterChat = directMessages.value.find((m) => m.id === placeholder.id)
  const promisedFile = Boolean(
    assistantAfterChat &&
      !userFacingOutputDownloads(assistantAfterChat.outputDownloads || []).length &&
      assistantImpliesPendingFileGeneration(assistantAfterChat.content),
  )
  const manualStepsOnly = Boolean(
    assistantAfterChat && assistantGaveManualOfficeStepsOnly(assistantAfterChat.content),
  )
  const canRecoverGenerate = shouldRecoverOfficeGenerate(
    userText,
    allAttachNames,
    conversationAttachNames,
    promisedFile || manualStepsOnly,
    conversationUserText,
  )
  if (promisedFile && canRecoverGenerate) {
    directLoading.value = true
    const fmt = pickGenerateFormat(userText, officeAttachNames)
    const extraFiles = filesSnapshot
      .filter((f) => f.file instanceof File)
      .map((f) => f.file as File)
    updateAssistantMessage(placeholder.id, (m) => {
      m.pending = true
      m.content = '**补跑生成**：正在调用生成员工产出可下载文件…'
    })
    try {
      const genPhase = await runDirectOfficeGeneratePhase({
        format: fmt,
        userText,
        readResults: cachedReadResults,
        extraAttachmentFiles: extraFiles,
        templateFile: pickPptTemplateFromSources(
          extraFiles.map((f) => ({ name: f.name, file: f })),
        ),
      })
      if (genPhase.errors.length && !genPhase.downloads.length) {
        const msg = genPhase.errors.join('；')
        directError.value = msg
        updateAssistantMessage(placeholder.id, (m) => {
          m.pending = false
          m.error = msg
          m.content = `${assistantAfterChat?.content || ''}\n\n---\n\n**生成失败**：${msg}`
        })
      } else {
        pushDirectGeneratedDownloads(genPhase.downloads)
        updateAssistantMessage(placeholder.id, (m) => {
          m.pending = false
          m.content = [assistantAfterChat?.content, genPhase.summary].filter(Boolean).join('\n\n---\n\n')
          const facingRecover = userFacingOutputDownloads(genPhase.downloads)
          if (facingRecover.length) m.outputDownloads = facingRecover
        })
      }
    } catch (e: unknown) {
      const msg = formatDirectChatError(e)
      if (msg.includes('登录已过期')) handleDirectChatAuthFailure()
      directError.value = msg
      updateAssistantMessage(placeholder.id, (m) => {
        m.pending = false
        m.error = msg
        m.content = `${assistantAfterChat?.content || ''}\n\n---\n\n**生成失败**：${msg}`
      })
    } finally {
      directLoading.value = false
    }
  } else if (promisedFile) {
    const warn = officeGenerateMissingInputMessage(pickGenerateFormat(userText, officeAttachNames))
    directError.value =
      '助手提到正在生成文件，但本次未调用生成员工；请重新附上 Office 文件，或在消息中加入「生成/导出/动画」等描述后重试。'
    updateAssistantMessage(placeholder.id, (m) => {
      m.content = `${m.content}\n\n---\n\n⚠️ ${warn}`
    })
  }
}
async function handleVoicePhoneTurn(userText: string): Promise<string> {
  ensureActiveConversation()
  const userMsg = makeMessage('user', userText, { agentLabel: '语音电话' })
  const placeholder = makeMessage('assistant', '', { pending: true })
  appendUserAndAssistant(userMsg, placeholder)
  await runDirectChatTurn({ assistantId: placeholder.id, userText })
  const m = directMessages.value.find((x) => x.id === placeholder.id)
  return stripInternalMarkers(m?.content || '')
}
function onDirectKeydown(e: KeyboardEvent): void {
  if (e.key !== 'Enter' || e.shiftKey) return
  e.preventDefault()
  void sendDirectChat()
}
async function applyEmployeeSessionClassify(text: string) {
  if (composerIntent.value !== 'employee') return
  try {
    const routeCtx = buildVoiceRouteContext()
    const { provider, model } = await resolveChatProviderModel()
    const classification = await classifyVoiceTurn({
      text,
      state: voiceSessionState.value,
      recentMessages: voiceMessages.value.slice(-6),
      routeCtx,
      composerIntent: composerIntent.value,
      provider,
      model,
    })
    applyVoiceSessionPatch(voiceSessionState.value, classification.statePatch)
  } catch {
    /* 预响应路径不阻塞 TTS */
  }
}

  return {
    ...ctx, sendDirectChat, handleVoicePhoneTurn, onDirectKeydown, applyEmployeeSessionClassify,
  }
}

export type useWbSendDirectChatBinds = ReturnType<typeof useWbSendDirectChat>
