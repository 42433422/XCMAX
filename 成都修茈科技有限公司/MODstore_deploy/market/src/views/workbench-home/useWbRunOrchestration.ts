import { nextTick, watch } from 'vue'
import { api } from '../../api'
import { streamLLMChat } from '../../utils/llmStream'
import type { VoiceTurnMessage } from '../../composables/voiceUserTurnCoalesce'
import { shouldHandleAsOfficeTask } from '../../utils/officeEmployeeOrchestration'
import type { useWbHandleModeSwitchFromSidebar } from './useWbHandleModeSwitchFromSidebar'
import type { WorkbenchStateRecord } from './types'
import { wbLate1 as __wbLate1 } from './wbLate1'

// 拆分自 WorkbenchHomeView.vue（原行 8516–8530, 9703–9717, 10308–10516 …）；逐字迁移，行为不变。
export function useWbRunOrchestration(ctx: ReturnType<typeof useWbHandleModeSwitchFromSidebar>) {
  const {
    wbSidebar, draft, workbenchErrorMessage, pendingHandoff, makeCompletionResult, finalizeLoading,
    finalizeError, orchestrationSession, orchestrationSessionId, pollStop, orchPhase, orchestrationEtaSeconds,
    orchestrationEtaReason, orchTimingStartMs, workflowLinkOffer, linkModId, linkError, planSession,
    planReplyDraft, autoPilotRunning, autoPilotError, voiceChecklistPaused, knowledgeError, isEmbeddingConfigured,
    CANVAS_SKILL_INTENT, isCanvasSkillIntent, composerIntent, modFrontendEnabled, platformChatMode, directDraft,
    directAttachedFiles, directError, directAttachmentNote, sendDirectChat, confirmEmployeeChecklistAndRunFromVoice, requireLoginForWorkbenchUse,
    selectedProvider, selectedModel, modelMode, stopOrchestrationElapsedTicker, startOrchestrationElapsedTicker, fallbackOrchestrationSecondsEstimate,
    estimateOrchestrationSeconds, canRunOrchestration, hasWorkflow, makeComposerInput, stopInlineVoice, clearWorkbenchHandoffSession,
    planQuickOptions, canSendPlanQuickPicks, planDiagramError, flushPlanMermaidDiagrams, formatKnowledgeContext, loadLinkMods,
    scrollMakeFlowToEnd, applyMakeCompletion, persistManualLlmIfNeeded, pollWorkbenchSession, buildChecklistGenerationSystemPrompt, enrichEmployeeHandoffBeforeOrchestration,
    friendlyPlanPanelApiError, parseChecklistBlock, resolveChatProviderModel, scrollPlanIntoView, openPlanSession, confirmSummaryAndStartPlanning,
    ensureAutoPilotReadyChatTurns, fastEnterChatForAutoPilot, autoPickPlanQuickOptions, sendPlanReply, sendPlanReplyFromQuickPicks, confirmPlanAndOpenHandoff,
  } = ctx

async function finishInlineHoldAndSend(target: 'direct' | 'make') {
  const finalText = (await stopInlineVoice(target)).trim()
  if (!finalText) {
    const msg = '未识别到文字，请按住说话后再松手发送。'
    if (target === 'direct') directError.value = msg
    else window.alert(msg)
    return
  }
  if (target === 'direct') {
    await sendDirectChat(finalText)
  } else {
    makeComposerInput.value = finalText
    await onComposerSendClick()
  }
}
watch(
  () => {
    const ps = planSession.value
    if (!ps?.messages) return ''
    return ps.messages.map((m: WorkbenchStateRecord) => `${m.role}\t${m.content}`).join('\n')
  },
  async () => {
    await nextTick()
    if (!planSession.value) {
      planDiagramError.value = {}
      return
    }
    await flushPlanMermaidDiagrams()
  },
)
async function runOrchestration(): Promise<boolean> {
  const h = pendingHandoff.value
  if (!h || !hasWorkflow.value || finalizeLoading.value) return false
  if (!requireLoginForWorkbenchUse()) return false
  if (!canRunOrchestration.value) {
    if (isCanvasSkillIntent(h.intentKey)) finalizeError.value = '请填写 Skill 组名称与描述'
    else finalizeError.value = '请填写描述'
    return false
  }
  enrichEmployeeHandoffBeforeOrchestration(h)
  const handoffSnapshot = { ...h }
  finalizeError.value = ''
  makeCompletionResult.value = null
  finalizeLoading.value = true
  pollStop.value = false
  orchestrationSession.value = null
  orchestrationSessionId.value = ''
  orchPhase.value = 'estimating'
  orchestrationEtaSeconds.value = null
  orchestrationEtaReason.value = ''
  orchTimingStartMs.value = null
  stopOrchestrationElapsedTicker()
  try {
    await persistManualLlmIfNeeded()
    const intent = h.intentKey || CANVAS_SKILL_INTENT
    const checklist = Array.isArray(h.executionChecklist) ? h.executionChecklist : []
    const scriptFiles = isCanvasSkillIntent(intent) && Array.isArray(h.files) ? h.files : []
    const eta = await estimateOrchestrationSeconds({
      intent,
      brief: String(handoffSnapshot.description || '').trim(),
      checklistLen: checklist.length,
      generateFrontend: intent === 'mod' ? modFrontendEnabled.value : false,
      employeeTarget: intent === 'employee' ? String(h.employeeTarget || '').trim() : '',
      scriptFileCount: scriptFiles.length,
    })
    let etaSec = eta.seconds
    let etaReason = String(eta.reason || '').trim()
    if (etaSec == null || !Number.isFinite(etaSec)) {
      etaSec = fallbackOrchestrationSecondsEstimate({
        intent,
        checklistLen: checklist.length,
        generateFrontend: intent === 'mod' ? modFrontendEnabled.value : false,
        employeeTarget: intent === 'employee' ? String(h.employeeTarget || '').trim() : '',
        scriptFileCount: scriptFiles.length,
      })
      if (!etaReason) etaReason = '按步骤量粗估（模型未返回数值）'
    }
    orchestrationEtaSeconds.value = etaSec
    orchestrationEtaReason.value = etaReason
    orchPhase.value = 'running'
    orchTimingStartMs.value = Date.now()
    startOrchestrationElapsedTicker()

    const body: Record<string, unknown> = {
      intent,
      brief:
        intent === 'employee' && String(handoffSnapshot.employeeRoutingBrief || '').trim()
          ? String(handoffSnapshot.employeeRoutingBrief).trim()
          : (handoffSnapshot.description || '').trim(),
      workflow_name:
        isCanvasSkillIntent(intent) ? (h.workflowName || '').trim() : undefined,
      plan_notes: isCanvasSkillIntent(intent) ? (h.planNotes || '').trim() : '',
      suggested_mod_id:
        intent === 'mod' ? (h.suggestedModId || '').trim() || undefined : undefined,
      replace: true,
      planning_messages: Array.isArray(h.planningMessages) ? h.planningMessages : [],
      execution_checklist: checklist,
      source_documents: Array.isArray(h.sourceDocuments) ? h.sourceDocuments : [],
      planning_context:
        intent === 'employee' ? String(handoffSnapshot.planningContext || handoffSnapshot.description || '').trim() : undefined,
      // 以当前「制作前端」开关为准，避免交接对象上缺失或陈旧的 generateFrontend
      generate_frontend: intent === 'mod' ? modFrontendEnabled.value : false,
    }
    if (intent === 'employee') {
      const et = String(h.employeeTarget || 'pack_only').trim()
      body.employee_target = et === 'pack_only' ? 'pack_only' : 'pack_plus_workflow'
      body.embed_script_workflow = true
      const wfn = String(h.employeeWorkflowName || '').trim()
      if (wfn) body.employee_workflow_name = wfn
      const fhd = String(h.fhdBaseUrl || '').trim()
      if (fhd) body.fhd_base_url = fhd
    }
    if (modelMode.value === 'manual' && selectedProvider.value && selectedModel.value) {
      body.provider = selectedProvider.value
      body.model = selectedModel.value
    } else {
      // Auto：与需求规划相同逻辑——默认厂商无密钥时换到已配置密钥的厂商，并显式传给编排接口
      const { provider, model } = await resolveChatProviderModel()
      body.provider = provider
      body.model = model
    }
    const useScriptMode = isCanvasSkillIntent(intent) && scriptFiles.length > 0
    const employeeFiles =
      intent === 'employee' && Array.isArray(h.files) && h.files.length ? h.files : []
    const started = useScriptMode
      ? await api.workbenchStartScriptSession(
          {
            brief: body.brief,
            workflow_name: body.workflow_name,
            provider: body.provider,
            model: body.model,
          },
          scriptFiles,
        )
      : employeeFiles.length
        ? await api.workbenchStartSessionWithFiles(body, employeeFiles)
        : await api.workbenchStartSession(body)
    const sid = started?.session_id
    if (!sid) throw new Error('未返回 session_id')
    orchestrationSessionId.value = String(sid)
    const final = await pollWorkbenchSession(sid)
    if (pollStop.value) return false
    if (!final) throw new Error('轮询已取消')
    void scrollMakeFlowToEnd()
    if (final.status === 'error') {
      finalizeError.value = final.error || '编排失败'
      return false
    }
    const art = final.artifact || {}
    const finIntent = final.intent || intent
    clearWorkbenchHandoffSession()
    try {
      if (modelMode.value === 'manual' && selectedProvider.value && selectedModel.value) {
        sessionStorage.setItem(
          'workbench_home_llm',
          JSON.stringify({
            provider: selectedProvider.value,
            model: selectedModel.value,
          }),
        )
        sessionStorage.setItem('workbench_home_llm_mode', 'manual')
      }
      sessionStorage.setItem('workbench_home_intent', finIntent)
    } catch {
      /* ignore */
    }
    if (art.execution_mode === 'script') {
      const scriptWorkflowId = Number(art.script_workflow_id || 0)
      const completion = applyMakeCompletion(final, finIntent, handoffSnapshot)
      if (Number.isFinite(scriptWorkflowId) && scriptWorkflowId > 0) {
        completion.primaryLabel = '打开脚本工作流沙箱'
        completion.primaryRoute = { path: `/script-workflows/${scriptWorkflowId}/edit`, query: { tab: 'sandbox' } }
        completion.usageLines = [
          '脚本工作流已生成，可在沙箱页上传同类文件反复验证脚本输出。',
          '确认脚本正确后，可保存并发布为可复用工作流。',
        ]
        makeCompletionResult.value = completion
      }
      return true
    }
    const gid = art.skill_group_id ?? art.workflow_id
    if (isCanvasSkillIntent(finIntent) && gid != null) {
      workflowLinkOffer.value = {
        workflowId: gid,
        workflowName: String(
          art.skill_group_name ||
            art.workflow_name ||
            (h.workflowName || '').trim() ||
            `Skill 组 ${gid}`,
        ),
        validationErrors: Array.isArray(art.validation_errors) ? art.validation_errors : [],
        llmWarnings: Array.isArray(art.llm_warnings) ? art.llm_warnings : [],
        sandboxOk: art.sandbox_ok !== false,
      }
      linkModId.value = ''
      linkError.value = ''
      void loadLinkMods()
      pendingHandoff.value = null
      void scrollMakeFlowToEnd()
      return true
    }
    if (finIntent === 'mod' && art.mod_id) {
      applyMakeCompletion(final, finIntent, handoffSnapshot)
      return true
    }
    if (finIntent === 'employee') {
      applyMakeCompletion(final, finIntent, handoffSnapshot)
      return true
    }
    pendingHandoff.value = null
    orchestrationSession.value = null
    orchestrationSessionId.value = ''
    return true
  } catch (e: unknown) {
    const m = workbenchErrorMessage(e)
    const low = m.toLowerCase()
    if (
      low.includes('not found') ||
      low.includes('404') ||
      m.includes('会话不存在') ||
      m.includes('已过期')
    ) {
      finalizeError.value =
        '无法查询编排会话（可能命中了另一台后端进程）。请部署并重启带「工作台会话落盘」的版本后重试；若已更新仍失败，请再点一次「开始生成 Mod」。'
    } else {
      finalizeError.value = m
    }
    pendingHandoff.value = handoffSnapshot
    return false
  } finally {
    stopOrchestrationElapsedTicker()
    orchPhase.value = 'idle'
    orchTimingStartMs.value = null
    orchestrationEtaSeconds.value = null
    orchestrationEtaReason.value = ''
    finalizeLoading.value = false
  }
  return false
}
/**
 * 「AI 自主全部进行」：从 summary 阶段一路串到后端编排完成。
 * 流程：confirmSummaryAndStartPlanning → 自动答快捷题（如有） →
 * requestExecutionChecklist → confirmPlanAndOpenHandoff → runOrchestration。
 * 任一步失败：把可读错误写入 autoPilotError，停在当前阶段，让用户手动接管。
 */
async function runAutoPilotFromSummary(opts?: { force?: boolean }) {
  const ps0 = planSession.value
  if (!ps0 || ps0.phase !== 'summary' || ps0.loading) return
  if (autoPilotRunning.value) return
  if (!ps0.summaryText) return
  if (!opts?.force && ps0.summaryNeedsClarification) return
  autoPilotRunning.value = true
  autoPilotError.value = ''
  try {
    if (opts?.force) {
      fastEnterChatForAutoPilot()
    } else {
      await confirmSummaryAndStartPlanning()
      let ps = planSession.value
      if (!ps || ps.phase !== 'chat') {
        throw new Error('未能进入澄清阶段')
      }
      if (ps.planError) throw new Error(ps.planError)

      await nextTick()
      if (planQuickOptions.value.length) {
        autoPickPlanQuickOptions()
        await nextTick()
        if (canSendPlanQuickPicks.value) {
          await sendPlanReplyFromQuickPicks()
        }
        ps = planSession.value
        if (ps?.planError) throw new Error(ps.planError)
      }
    }

    let ps = planSession.value
    if (!ps || ps.phase !== 'chat') {
      throw new Error('澄清阶段已被打断')
    }
    ensureAutoPilotReadyChatTurns(Boolean(opts?.force))
    if ((ps.messages?.length || 0) < 2) {
      throw new Error('澄清回合不足，无法生成执行清单')
    }

    await requestExecutionChecklist()
    ps = planSession.value
    if (!ps) throw new Error('规划会话已丢失')
    if (ps.planError) throw new Error(ps.planError)
    if (ps.phase !== 'checklist') throw new Error('未能生成执行清单')

    confirmPlanAndOpenHandoff()
    await nextTick()
    if (!pendingHandoff.value) throw new Error('未能生成制作草稿')

    await runOrchestration()
    if (finalizeError.value) throw new Error(finalizeError.value)
  } catch (e) {
    autoPilotError.value = friendlyPlanPanelApiError(e)
  } finally {
    autoPilotRunning.value = false
  }
}
/** 规划面板已在「需求澄清」阶段时，用户说「开始写吧」等口令 → 自动跑完清单与生成 */
async function runAutoPilotFromChat() {
  const ps0 = planSession.value
  if (!ps0 || ps0.phase !== 'chat' || ps0.loading) return
  if (autoPilotRunning.value) return
  autoPilotRunning.value = true
  autoPilotError.value = ''
  try {
    let ps = planSession.value
    if (!ps) throw new Error('规划会话已丢失')

    if ((ps.messages?.length || 0) < 2) {
      await nextTick()
      if (planQuickOptions.value.length) {
        autoPickPlanQuickOptions()
        await nextTick()
        if (canSendPlanQuickPicks.value) {
          await sendPlanReplyFromQuickPicks()
        }
      }
      ps = planSession.value
      if (ps && (ps.messages?.length || 0) < 2) {
        planReplyDraft.value = '按前面描述的需求继续，默认方案即可。'
        await sendPlanReply()
      }
    }

    ps = planSession.value
    if (!ps || ps.phase !== 'chat') throw new Error('澄清阶段已被打断')
    if (ps.planError) throw new Error(ps.planError)
    ensureAutoPilotReadyChatTurns(true)
    if ((ps.messages?.length || 0) < 2) {
      throw new Error('澄清回合不足，无法生成执行清单')
    }

    await requestExecutionChecklist()
    ps = planSession.value
    if (!ps) throw new Error('规划会话已丢失')
    if (ps.planError) throw new Error(ps.planError)
    if (ps.phase !== 'checklist') throw new Error('未能生成执行清单')

    confirmPlanAndOpenHandoff()
    await nextTick()
    if (!pendingHandoff.value) throw new Error('未能生成制作草稿')

    await runOrchestration()
    if (finalizeError.value) throw new Error(finalizeError.value)
  } catch (e) {
    autoPilotError.value = friendlyPlanPanelApiError(e)
  } finally {
    autoPilotRunning.value = false
  }
}
async function requestExecutionChecklist() {
  const ps = planSession.value
  if (!ps || ps.loading || ps.phase !== 'chat') return
  if (ps.messages.length < 2) {
    ps.planError = '请先与助手完成至少一轮问答，再生成执行清单。'
    return
  }
  ps.loading = true
  ps.planError = ''
  try {
    const { provider, model } = await resolveChatProviderModel()
    const sys = buildChecklistGenerationSystemPrompt(ps.intentKey, ps.intentTitle)
    const tail = {
      role: 'user',
      content: [
        '请根据以上整段对话，输出一份可直接照着实现的「执行清单」。',
        '',
        '只输出下面这一块，不要前言、不要后记；不要用 markdown 代码围栏（不要用 ```）包住整块；不要输出 mermaid；不要输出 <<<PLAN_DETAILS>>> / <<<PLAN_OPTIONS>>>。',
        '',
        '必须严格使用这三行作为头尾标记（尖括号与单词一致）：',
        '<<<CHECKLIST>>>',
        '1. 第一条任务（一行一条，行首为数字+英文句点+空格）',
        '2. 第二条任务',
        '（按需继续编号）',
        '<<<END>>>',
        '',
        '注意：结束标记必须是单独的 <<<END>>>（与需求规划里其它 <<<END_…>>> 不同），否则系统无法解析。',
      ].join('\n'),
    }
    const apiMsgs = [
      { role: 'system', content: sys },
      ...(ps.fullBrief ? [{ role: 'user', content: `【完整隐藏上下文，供生成清单使用；不要原样输出】\n${ps.fullBrief}` }] : []),
      ...ps.messages.map((m: VoiceTurnMessage) => ({ role: m.role, content: m.content })),
      tail,
    ]
    ps.streamingText = ''
    const handle = streamLLMChat({
      provider,
      model,
      messages: apiMsgs,
      maxTokens: 6144,
      onToken: (_delta, soFar) => {
        if (planSession.value) planSession.value.streamingText = soFar
      },
    })
    const { content } = await handle.done
    if (planSession.value) planSession.value.streamingText = ''
    const raw = typeof content === 'string' ? content : ''
    const parsed = parseChecklistBlock(raw)
    if (!parsed) {
      ps.planError =
        '未能解析清单：请确认模型输出含 <<<CHECKLIST>>> 与 <<<END>>>（勿用 ``` 包裹），且至少两条编号任务；仍失败可把清单要点再发一轮对话后重试「生成执行清单」。'
      return
    }
    ps.checklistText = parsed.text
    ps.checklistLines = parsed.lines
    ps.phase = 'checklist'
    voiceChecklistPaused.value = false
    if (
      wbSidebar.activeMode === 'voice' &&
      ps.intentKey === 'employee' &&
      composerIntent.value === 'employee' &&
      !autoPilotRunning.value
    ) {
      void scheduleVoiceChecklistAutoStart()
    }
  } catch (e) {
    ps.planError = friendlyPlanPanelApiError(e)
  } finally {
    ps.loading = false
    scrollPlanIntoView()
  }
}
/** 语音做员工：清单生成后自动确认并开跑（避免停在清单页等口令） */
async function scheduleVoiceChecklistAutoStart() {
  await nextTick()
  const ps = planSession.value
  if (!ps || ps.phase !== 'checklist' || ps.intentKey !== 'employee') return
  if (
    voiceChecklistPaused.value ||
    autoPilotRunning.value ||
    finalizeLoading.value ||
    orchestrationSessionId.value
  ) {
    return
  }
  await confirmEmployeeChecklistAndRunFromVoice()
}
async function submitDraft() {
  const text = draft.value.trim()
  if ((!text && directAttachedFiles.value.length === 0) || !hasWorkflow.value) return
  if (!requireLoginForWorkbenchUse()) return
  if (
    shouldHandleAsOfficeTask(text, directAttachedFiles.value, planSession.value) &&
    !platformChatMode.value
  ) {
    directDraft.value = text || directDraft.value
    draft.value = ''
    await sendDirectChat(text || directDraft.value.trim())
    return
  }
  if (platformChatMode.value) {
    directDraft.value = text
    draft.value = ''
    await sendDirectChat(text)
    return
  }
  if (directAttachedFiles.value.some((f) => f.status === 'uploading')) {
    knowledgeError.value = '附件仍在读取中，请稍候'
    return
  }
  if (planSession.value?.phase === 'chat') return
  if (planSession.value && planSession.value.phase !== 'done') {
    finalizeError.value = '请先完成或关闭上方的「需求规划」面板。'
    return
  }
  if (pendingHandoff.value || finalizeLoading.value || makeCompletionResult.value) {
    finalizeError.value = '请先完成当前制作任务，或点击完成卡片中的「开始新任务」。'
    return
  }
  finalizeError.value = ''
  const filesSnapshot = [...directAttachedFiles.value]
  const note = directAttachmentNote(filesSnapshot)
  const inlineBlocks = filesSnapshot
    .filter((f) => (f.status === 'inline' || f.status === 'ready') && f.extractedText)
    .map((f, idx) => `### @附件${idx + 1}：${f.name}\n\n${f.extractedText}`)
    .join('\n\n---\n\n')
  let knowledgePack = ''
  if (text && isEmbeddingConfigured()) {
    try {
      const embeddingChoice = await resolveChatProviderModel()
      const res = await api.knowledgeSearch(text, 6, {
        embeddingProvider: embeddingChoice.provider,
        embeddingModel: embeddingChoice.model,
      })
      knowledgePack = formatKnowledgeContext(res?.items)
    } catch (e: unknown) {
      knowledgeError.value = workbenchErrorMessage(e)
    }
  }
  const payloadParts = [text]
  const intent = composerIntent.value || CANVAS_SKILL_INTENT
  const wantsModFrontend = intent === 'mod' && modFrontendEnabled.value
  if (intent === 'mod') {
    payloadParts.push(
      wantsModFrontend
        ? '【制作选项】本次需要为 Mod 生成可路由的定制 Vue 前端页面，并在 manifest.frontend.menu 中暴露入口。'
        : '【制作选项】本次暂不生成定制前端，只保留 Mod 骨架、员工和工作流能力。',
    )
  }
  if (note) payloadParts.push(note)
  if (inlineBlocks) {
    payloadParts.push(`【本次上传附件全文】\n用户按上传顺序提供了以下文件；@附件1、@附件2 等编号与上方附件顺序一致，请按编号理解文件之间的先后逻辑。\n\n${inlineBlocks}`)
  }
  if (knowledgePack) payloadParts.push(`【我的文件资料库命中片段】\n${knowledgePack}`)
  const payload = payloadParts.filter(Boolean).join('\n\n---\n')
  const displayPayload = [text, note].filter(Boolean).join('\n\n')
  await openPlanSession({
    fullBrief: payload,
    displayBrief: displayPayload,
    files: filesSnapshot.map((f) => f.file),
    generateFrontend: wantsModFrontend,
  })
}
async function onComposerSendClick() {
  if (planSession.value?.phase === 'chat') {
    await sendPlanReply()
    return
  }
  await submitDraft()
}

  __wbLate1.runOrchestration = runOrchestration

  return {
    ...ctx, finishInlineHoldAndSend, runOrchestration, runAutoPilotFromSummary, runAutoPilotFromChat,
    requestExecutionChecklist, scheduleVoiceChecklistAutoStart, submitDraft, onComposerSendClick,
  }
}

export type useWbRunOrchestrationBinds = ReturnType<typeof useWbRunOrchestration>
