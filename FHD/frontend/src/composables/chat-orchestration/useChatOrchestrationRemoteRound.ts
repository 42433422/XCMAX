/**
 * useChatOrchestration 拆出的远程对话轮次（快路径 / SSE 流式 / JSON 与批量）（行为零变更）。
 */
import type { Ref } from 'vue'
import type { useAgentRunEventSync } from '../useAgentRunEvents'
import type { useChatDbTokenGate } from '../useChatDbTokenGate'
import type { useChatExcelContext } from '../useChatExcelContext'
import type { useChatMessages } from '../useChatMessages'
import type { useChatRequest, ChatRequestScope } from '../useChatRequest'
import type { useChatResponseAttach } from '../useChatResponseAttach'
import type { useChatSessionActivity } from '../useChatSessionActivity'
import type { ShipmentTask } from '../useShipmentTask'
import type { ChatPlannerPayload, ChatRequest } from '@/types/chat'
import chatApi, { parseChatStreamErrorResponse } from '@/api/chat'
import productsApi from '@/api/products'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import { readPlannerSseResponse, isChatStreamEnabled, type PlannerSseEvent } from '@/utils/chatSseStream'
import { collapseExactDuplicateReply } from '@/utils/chatReplyNormalization'
import { asArray, asRecord, asString } from '@/utils/typeGuards'
import { extractLikelyProductQueryKeyword } from '../useChatPersistence'
import { persistDetachedPlannerResult, recordProductFastPathTask } from '../useChatSessionActivity'
import { asPlannerPayload, errorMessage } from './chatOrchestrationShared'
import { aiModBriefFromChat, generateAndInstallAiMod } from '@/utils/aiModDeliveryApi'
import type { UiChatMessageExtras } from '@/types/chat-ui'

type ChatMessagesApi = ReturnType<typeof useChatMessages>

export interface ChatOrchestrationRemoteRoundDeps {
  sessionId: Ref<string>
  messages: ChatMessagesApi['messages']
  addMessage: ChatMessagesApi['addMessage']
  saveMessage: ChatMessagesApi['saveMessage']
  queueVoice: ChatMessagesApi['queueVoice']
  pushStreamingAiShell: ChatMessagesApi['pushStreamingAiShell']
  applyPlainTextToMessageIndex: ChatMessagesApi['applyPlainTextToMessageIndex']
  ttsEnabled: Ref<boolean>
  chatSessionActivity: ReturnType<typeof useChatSessionActivity>
  pendingDbWriteChatRetryMessages: Ref<string[] | null>
  plannerWriteUnlockResumeDraft: Ref<string>
  chatRequest: ReturnType<typeof useChatRequest>
  handleChatRequiresToken: ReturnType<typeof useChatDbTokenGate>['handleChatRequiresToken']
  resolveExcelAnalysisContextForRequest: ReturnType<typeof useChatExcelContext>['resolveExcelAnalysisContextForRequest']
  multimodalPendingCount: ReturnType<typeof useChatExcelContext>['multimodalPendingCount']
  stateSteps: Ref<Array<{ node_id: string; status: 'succeeded' | 'failed'; output_summary: string }>>
  currentTask: Ref<ShipmentTask | null>
  syncTaskFromChatResponse: ReturnType<typeof useChatResponseAttach>['syncTaskFromChatResponse']
  attachThinkingStepsToLastAiMessage: ReturnType<typeof useChatResponseAttach>['attachThinkingStepsToLastAiMessage']
  attachTodoStepsToLastAiMessage: ReturnType<typeof useChatResponseAttach>['attachTodoStepsToLastAiMessage']
  attachWorkflowTraceToLastAiMessage: ReturnType<typeof useChatResponseAttach>['attachWorkflowTraceToLastAiMessage']
  attachApprovalCardToLastAiMessage: ReturnType<typeof useChatResponseAttach>['attachApprovalCardToLastAiMessage']
  attachAgentRunTraceToLastAiMessage: ReturnType<typeof useChatResponseAttach>['attachAgentRunTraceToLastAiMessage']
  attachContextSummaryToLastAiMessage: ReturnType<typeof useChatResponseAttach>['attachContextSummaryToLastAiMessage']
  syncAgentRunFromPayload: ReturnType<typeof useAgentRunEventSync>['syncAgentRunFromPayload']
  showTaskConfirm: (task: unknown) => void
  maybeCloseAssistantFloatForShipmentTask: (task: unknown, autoAction: unknown) => void
  emitAssistantPush: (payload?: unknown) => void
  handleAutoAction: (action: unknown, userMessage?: string) => void
}

export function useChatOrchestrationRemoteRound(deps: ChatOrchestrationRemoteRoundDeps) {
  const {
    sessionId,
    messages,
    addMessage,
    saveMessage,
    queueVoice,
    pushStreamingAiShell,
    applyPlainTextToMessageIndex,
    ttsEnabled,
    chatSessionActivity,
    pendingDbWriteChatRetryMessages,
    plannerWriteUnlockResumeDraft,
    chatRequest,
    handleChatRequiresToken,
    resolveExcelAnalysisContextForRequest,
    multimodalPendingCount,
    stateSteps,
    currentTask,
    syncTaskFromChatResponse,
    attachThinkingStepsToLastAiMessage,
    attachTodoStepsToLastAiMessage,
    attachWorkflowTraceToLastAiMessage,
    attachApprovalCardToLastAiMessage,
    attachAgentRunTraceToLastAiMessage,
    attachContextSummaryToLastAiMessage,
    syncAgentRunFromPayload,
    showTaskConfirm,
    maybeCloseAssistantFloatForShipmentTask,
    emitAssistantPush,
    handleAutoAction,
  } = deps
  const {
    setLoadingProgress,
    startWaitProgressTimer,
    buildPlannerChatRequestPayload,
    stopLoadingProgress,
    requestChatByModeWithTimeout,
    requestChatByModeBatchWithTimeout,
    resolveChatTimeoutMs,
  } = chatRequest

  function responseCameFromCache(payload: unknown): boolean {
    const row = asRecord(payload)
    const data = asRecord(row.data)
    const inner = asRecord(data.data)
    return row.cached === true || data.cached === true || inner.cached === true
  }

  /** 消费后端 state.update 事件（payload.data.data.state_updates），维护「步骤进度」UI 状态 */
  function consumeStateUpdates(payload: ChatPlannerPayload): void {
    const row = asRecord(payload)
    const data = asRecord(row.data)
    const inner = asRecord(data.data ?? data)
    const updates = asArray<Record<string, unknown>>(inner.state_updates ?? row.state_updates)
    if (!updates.length) return
    for (const u of updates) {
      if (String(u.type || '') !== 'state.update') continue
      const nodeId = String(u.node_id || '')
      if (!nodeId) continue
      const entry = {
        node_id: nodeId,
        status: String(u.status || 'succeeded') === 'failed' ? ('failed' as const) : ('succeeded' as const),
        output_summary: String(u.output_summary || ''),
      }
      const idx = stateSteps.value.findIndex((s) => s.node_id === nodeId)
      if (idx >= 0) {
        stateSteps.value[idx] = entry
      } else {
        stateSteps.value.push(entry)
      }
    }
  }

  function maybePrefetchProductAssistantFloat(userText: string) {
    // 教程进行中也需要与聊天请求并行预开产品副窗；否则会出现「不开教程立刻出副窗、走了教程反而要等 AI」的体验差。
    // 副窗切到「协助/产品查询」若与某步高亮冲突，用户仍可用教程卡片「下一步」或退出教程。
    const kw = extractLikelyProductQueryKeyword(userText)
    if (!kw) return
    window.dispatchEvent(
      new CustomEvent('xcagi:open-assistant-float', {
        detail: { feature: 'products', query: kw, forceOpen: true },
      }),
    )
  }

  async function executeRemoteChatRound(remoteMessages: string[], opts?: { fromWriteUnlock?: boolean }, scope?: ChatRequestScope) {
    if (!remoteMessages.length) return
    const requestScope = scope || { sessionId: sessionId.value, messages: [...messages.value] }
    const round = chatSessionActivity.forSession(requestScope.sessionId)
    const addRoundMessage = async (text: string, extras?: UiChatMessageExtras) => {
      if (round.isActive()) addMessage(text, 'ai', extras, { speak: ttsEnabled.value })
    }
    if (!opts?.fromWriteUnlock) {
      pendingDbWriteChatRetryMessages.value = null
      plannerWriteUnlockResumeDraft.value = ''
    }
    const primaryText = remoteMessages[0] || ''
    const aiModBrief = remoteMessages.length === 1 && !isAdminConsoleSpa() ? aiModBriefFromChat(primaryText) : ''

    if (aiModBrief) {
      round.setLoading(true)
      setLoadingProgress('正在创建自用 MOD…', requestScope.sessionId)
      startWaitProgressTimer(requestScope.sessionId)
      try {
        const result = await generateAndInstallAiMod(aiModBrief, {
          onProgress: (progress) => setLoadingProgress(progress.label, requestScope.sessionId),
        })
        const responseText = `已生成并安装自用 MOD「${result.modId}」。${result.installMessage}`
        const extras: UiChatMessageExtras = {
          workflowAction: 'mod_generated_and_installed',
          nodeResults: [
            { node_id: 'generate', tool_id: 'workbench', action: 'generate_mod', success: true },
            { node_id: 'validate', tool_id: 'workbench', action: 'validate_mod', success: true },
            { node_id: 'install', tool_id: 'mod_store', action: 'install_self_use', success: true },
          ],
        }
        await addRoundMessage(responseText, extras)
        await Promise.all([
          saveMessage('user', primaryText, requestScope.sessionId),
          saveMessage('ai', responseText, requestScope.sessionId, extras),
        ])
      } catch (err) {
        const responseText = `MOD 生成或安装失败：${errorMessage(err, '未知错误')}`
        await addRoundMessage(responseText)
        await Promise.all([
          saveMessage('user', primaryText, requestScope.sessionId),
          saveMessage('ai', responseText, requestScope.sessionId),
        ])
      } finally {
        round.setLoading(false)
        stopLoadingProgress(requestScope.sessionId)
      }
      return
    }

    /** 查产品类话术可不必等 /ai/chat 或连通性探测，直接走产品列表接口 */
    /** 管理端（admin-console）无产品库业务，不走产品快路径，避免「查询…」话术被误判为产品检索 */
    const kwFast =
      remoteMessages.length === 1 && !isAdminConsoleSpa() && !resolveExcelAnalysisContextForRequest() && multimodalPendingCount.value === 0
        ? extractLikelyProductQueryKeyword(primaryText)
        : null

    // 快路径会自己拉产品列表并注水副窗；再 prefetch 会多打一遍相同接口，徒增等待
    if (!kwFast) {
      maybePrefetchProductAssistantFloat(primaryText)
    }

    if (kwFast) {
      round.setLoading(true)
      setLoadingProgress('正在查询产品库…', requestScope.sessionId)
      startWaitProgressTimer(requestScope.sessionId)
      try {
        const resp = await productsApi.searchProducts(kwFast)
        const respRow = asRecord(resp)
        if (resp && resp.success === false) {
          throw new Error(String(resp.message || '产品库查询失败'))
        }
        const raw = resp.data ?? respRow.products ?? respRow.items
        const rows = asArray<Record<string, unknown>>(raw)
        const lines = rows.slice(0, 3).map((row) => {
          const m = String(row.model_number || '').trim()
          const n = String(row.name || row.product_name || '-').trim()
          const p = Number(row.price || 0)
          const pf = Number.isFinite(p) ? p.toFixed(2) : '0.00'
          return `- ${m || '-'} / ${n} / ￥${pf}`
        })
        const previewSuffix = lines.length ? `\n预览命中 ${rows.length} 条：\n${lines.join('\n')}` : ''
        const hasResults = lines.length > 0
        const responseText = hasResults
          ? `已帮你打开产品副窗并带入「${kwFast}」。可在卡片中查看与修改。${previewSuffix}`
          : `未在产品库中找到「${kwFast}」，请确认型号或关键词后重试。`
        const payload: ChatPlannerPayload = {
          success: true,
          response: responseText,
          ...(hasResults ? { autoAction: { type: 'show_products_float', query: kwFast } } : {}),
        }
        const mappedRows = rows.slice(0, 20).map((r) => ({
          id: r.id,
          model_number: r.model_number || '',
          name: r.name || r.product_name || '',
          price: Number(r.price || 0),
          unit: r.unit || '',
        }))
        const totalFromApi = typeof respRow.total === 'number' ? respRow.total : rows.length
        await recordProductFastPathTask(requestScope.sessionId, primaryText, kwFast, mappedRows, totalFromApi, responseText)
        await addRoundMessage(payload.response || '')
        await Promise.all([
          saveMessage('user', primaryText, requestScope.sessionId),
          saveMessage('ai', payload.response || '', requestScope.sessionId),
        ])
        if (!round.isActive()) return
        syncTaskFromChatResponse(payload, primaryText)
        attachContextSummaryToLastAiMessage()
        attachThinkingStepsToLastAiMessage(payload)
        attachTodoStepsToLastAiMessage(payload)
        attachWorkflowTraceToLastAiMessage(payload)
        attachApprovalCardToLastAiMessage(payload)
        if (!payload.task && (payload.autoAction?.type === 'show_products_float' || payload.autoAction?.type === 'show_products')) {
          currentTask.value = null
        }
        if (payload.autoAction) {
          handleAutoAction(
            {
              ...payload.autoAction,
              hydrateProductSearch: { rows: mappedRows, total: totalFromApi },
            },
            primaryText,
          )
        }
        return
      } catch {
        /* 回退到下方 unified / chat 全链路 */
      } finally {
        round.setLoading(false)
        stopLoadingProgress(requestScope.sessionId)
      }
    }

    /** ChatView 主路径：单条消息走 Planner SSE，token 逐字写入气泡；批量仍用 JSON。可用 ``VITE_CHAT_STREAM=0`` 关闭。 */
    if (remoteMessages.length === 1 && isChatStreamEnabled()) {
      const primaryForStream = remoteMessages[0] || ''
      round.setStreaming(true)
      round.setLoading(true)
      setLoadingProgress('正在流式生成回复…', requestScope.sessionId)
      startWaitProgressTimer(requestScope.sessionId)
      const baseS = resolveChatTimeoutMs(primaryForStream)
      const timeoutMsS = Math.min(120000, baseS)
      const controller = new AbortController()
      const killTimer = window.setTimeout(() => controller.abort(), timeoutMsS)
      const msgIndex = pushStreamingAiShell()
      let streamPlain = ''
      let doneResult: unknown = null
      let sseError: string | null = null
      // TTS 增量朗读：以句末标点为界把已稳定的前缀丢给语音队列，避免边生成边合成后半句卡顿或被重复打断
      let ttsSpokenOffset = 0
      const ttsShouldSpeakThisMessage = ttsEnabled.value
      const SPEAK_SENTENCE_BOUNDARY = /[。！？!?；;\n]/g
      const flushTtsFromStream = (text: string, force: boolean) => {
        if (!round.isActive()) return
        // 开关状态可能在流式过程中被改掉；每次检查当前值，关闭后立即停止追加
        if (!ttsShouldSpeakThisMessage || !ttsEnabled.value) return
        const pending = text.slice(ttsSpokenOffset)
        if (!pending) return
        if (force) {
          queueVoice(pending)
          ttsSpokenOffset = text.length
          return
        }
        // 找到最后一个句末标点的位置；若没有就暂不朗读，等后续 token 到达再重新判
        SPEAK_SENTENCE_BOUNDARY.lastIndex = 0
        let lastBoundary = -1
        let match: RegExpExecArray | null
        while ((match = SPEAK_SENTENCE_BOUNDARY.exec(pending)) !== null) {
          lastBoundary = match.index + match[0].length
        }
        if (lastBoundary < 0) return
        const chunk = pending.slice(0, lastBoundary).trim()
        if (chunk) queueVoice(chunk)
        ttsSpokenOffset += lastBoundary
      }
      try {
        const { body } = buildPlannerChatRequestPayload(
          primaryForStream,
          {
            fromWriteUnlock: !!opts?.fromWriteUnlock,
          },
          requestScope,
        )
        const res = await chatApi.sendChatStream(
          { ...body, message: String(body.message || primaryForStream) } as ChatRequest & Record<string, unknown>,
          { signal: controller.signal },
        )
        if (!res.ok) {
          throw new Error(await parseChatStreamErrorResponse(res))
        }
        await readPlannerSseResponse(res, (ev: PlannerSseEvent) => {
          if (ev.type === 'token') {
            streamPlain += ev.text || ''
            if (round.isActive()) applyPlainTextToMessageIndex(msgIndex, streamPlain)
            flushTtsFromStream(streamPlain, false)
            setLoadingProgress('正在生成回复…', requestScope.sessionId)
          } else if (ev.type === 'done') {
            doneResult = ev.result
          } else if (ev.type === 'error') {
            sseError = String(ev.message || '流式接口错误')
          } else if (ev.type === 'requires_token') {
            const tokenName = ev.token_name || ''
            const tokenDesc = ev.token_description || ''
            handleChatRequiresToken(tokenName, tokenDesc, remoteMessages)
            streamPlain += `\n[需要授权：${tokenDesc || tokenName || '授权信息'}]\n`
            if (round.isActive()) applyPlainTextToMessageIndex(msgIndex, streamPlain)
            flushTtsFromStream(streamPlain, false)
            const upTok = String(tokenName || '').toUpperCase()
            if (upTok.includes('WRITE') || /写入|导入|入库|二级|数据库写入|DB_WRITE/i.test(String(tokenDesc || ''))) {
              plannerWriteUnlockResumeDraft.value = streamPlain
            }
          }
        })
        if (sseError) {
          throw new Error(sseError)
        }
        const donePayload = asPlannerPayload(doneResult)
        const finalText = collapseExactDuplicateReply(String(donePayload.response ?? streamPlain).trim() || streamPlain || '（无内容）')
        if (round.isActive()) {
          if (responseCameFromCache(donePayload)) {
            applyPlainTextToMessageIndex(msgIndex, finalText, { sameAsPrevious: true })
          } else {
            applyPlainTextToMessageIndex(msgIndex, finalText)
          }
        }
        // 后端 done 事件可能带一段非 token 的尾部文本（比如总结段），统一再做一次兜底朗读
        if (ttsShouldSpeakThisMessage && ttsEnabled.value) {
          if (finalText.length >= ttsSpokenOffset) {
            // 用 finalText 做最终来源，确保 done 额外补的那段也能被念到
            const tail = finalText.slice(ttsSpokenOffset).trim()
            if (tail) queueVoice(tail)
            ttsSpokenOffset = finalText.length
          } else {
            flushTtsFromStream(streamPlain, true)
          }
        }
        if (!round.isActive()) return
        const wrap: ChatPlannerPayload = doneResult && typeof doneResult === 'object' ? donePayload : { success: true, response: finalText }
        syncTaskFromChatResponse(wrap, primaryText)
        await syncAgentRunFromPayload(wrap, primaryText)
        attachAgentRunTraceToLastAiMessage()
        consumeStateUpdates(wrap)
        attachContextSummaryToLastAiMessage()
        attachThinkingStepsToLastAiMessage(wrap)
        attachTodoStepsToLastAiMessage(wrap)
        attachWorkflowTraceToLastAiMessage(wrap)
        attachApprovalCardToLastAiMessage(wrap)
        if (wrap.task) {
          showTaskConfirm(wrap.task)
          emitAssistantPush({
            title: asString(asRecord(wrap.task).title || '新任务'),
            description: asString(asRecord(wrap.task).description || '收到一条任务，请处理'),
          })
        }
        if (!wrap.task && (wrap?.autoAction?.type === 'show_products_float' || wrap?.autoAction?.type === 'show_products')) {
          currentTask.value = null
        }
        if (wrap.autoAction) {
          handleAutoAction(wrap.autoAction, primaryText)
        }
        if (wrap.task) {
          maybeCloseAssistantFloatForShipmentTask(wrap.task, wrap.autoAction)
        }
      } catch (err: unknown) {
        const errText =
          err instanceof Error && err.name === 'AbortError'
            ? `请求超时（>${Math.floor(timeoutMsS / 1000)}s）或已中断`
            : errorMessage(err, '流式对话失败')
        if (round.isActive()) applyPlainTextToMessageIndex(msgIndex, `处理失败：${errText}`)
      } finally {
        round.setStreaming(false)
        window.clearTimeout(killTimer)
        round.setLoading(false)
        stopLoadingProgress(requestScope.sessionId)
      }
      return
    }

    round.setLoading(true)
    round.setStreaming(false)
    setLoadingProgress('正在理解你的问题...', requestScope.sessionId)
    let data: ChatPlannerPayload = {}
    try {
      // 不再在发聊天前阻塞等待 /api/ai/test（最多 3s），否则「慢」往往来自这里而非 AI
      setLoadingProgress(
        remoteMessages.length > 1 ? `正在批量处理 ${remoteMessages.length} 条消息...` : '正在整理上下文...',
        requestScope.sessionId,
      )
      startWaitProgressTimer(requestScope.sessionId)
      const base = resolveChatTimeoutMs(primaryText)
      const timeoutMs = Math.min(120000, remoteMessages.length <= 1 ? base : base * remoteMessages.length)
      let rawData: unknown
      if (remoteMessages.length === 1) {
        rawData = await requestChatByModeWithTimeout(
          remoteMessages[0],
          timeoutMs,
          {
            fromWriteUnlock: !!opts?.fromWriteUnlock,
          },
          requestScope,
        )
      } else {
        rawData = await requestChatByModeBatchWithTimeout(remoteMessages, timeoutMs, requestScope)
      }
      data = asPlannerPayload(rawData)
      const head = remoteMessages.length === 1 ? data : asPlannerPayload(data.results?.[0])
      const headData = asRecord(head.data)
      setLoadingProgress('已收到响应，正在解析执行计划...', requestScope.sessionId)
      if (headData.action === 'workflow_confirmation_required') {
        setLoadingProgress('已生成计划，等待你确认执行...', requestScope.sessionId)
      } else if (headData.action === 'workflow_done') {
        setLoadingProgress('执行完成，正在整理结果...', requestScope.sessionId)
      } else if (headData.action === 'workflow_failed') {
        setLoadingProgress('执行失败，正在整理错误信息...', requestScope.sessionId)
      }
    } catch (err: unknown) {
      data = {
        success: false,
        message: errorMessage(err, '请求失败'),
      }
    } finally {
      round.setStreaming(false)
      round.setLoading(false)
      stopLoadingProgress(requestScope.sessionId)
    }

    if (!round.isActive()) return persistDetachedPlannerResult(data, requestScope.sessionId, saveMessage)
    if (data.batch && Array.isArray(data.results)) {
      const results = data.results.map((part) => asPlannerPayload(part))
      if (data.success) {
        for (const part of results) {
          if (part && part.success) {
            if (part.requires_token) {
              handleChatRequiresToken(part.token_name || '', part.token_description || '', remoteMessages)
            }
            await addRoundMessage(part.response || '', responseCameFromCache(part) ? { sameAsPrevious: true } : undefined)
            syncTaskFromChatResponse(part, primaryText)
            await syncAgentRunFromPayload(part, primaryText)
            attachAgentRunTraceToLastAiMessage()
          } else {
            await addRoundMessage('处理失败: ' + (part.message || '未知错误'))
          }
        }
        attachContextSummaryToLastAiMessage()
        const lastOk = [...results].reverse().find((p) => p && p.success)
        if (lastOk) {
          consumeStateUpdates(lastOk)
          attachThinkingStepsToLastAiMessage(lastOk)
          attachTodoStepsToLastAiMessage(lastOk)
          attachWorkflowTraceToLastAiMessage(lastOk)
          attachApprovalCardToLastAiMessage(lastOk)
        }
        const lastTask = [...results].reverse().find((p) => p.task)
        if (lastTask?.task) {
          showTaskConfirm(lastTask.task)
          const taskRow = asRecord(lastTask.task)
          emitAssistantPush({
            title: taskRow.title || '新任务',
            description: taskRow.description || '收到一条任务，请处理',
          })
        }
        const lastFloat = [...results]
          .reverse()
          .find((p) => p.autoAction?.type === 'show_products_float' || p.autoAction?.type === 'show_products')
        if (!lastTask?.task && lastFloat?.autoAction) {
          currentTask.value = null
        }
        const lastAction = [...results].reverse().find((p) => p.autoAction)
        if (lastAction?.autoAction) {
          handleAutoAction(lastAction.autoAction, remoteMessages[remoteMessages.length - 1] || '')
        }
        if (lastTask?.task) {
          maybeCloseAssistantFloatForShipmentTask(lastTask.task, lastAction?.autoAction)
        }
      } else {
        await addRoundMessage('处理失败: ' + (data.message || '批量请求失败'))
      }
      return
    }

    if (data.success) {
      if (data?.requires_token) {
        handleChatRequiresToken(data.token_name || '', data.token_description || '', remoteMessages)
      }
      await addRoundMessage(data.response || '', responseCameFromCache(data) ? { sameAsPrevious: true } : undefined)
      syncTaskFromChatResponse(data, primaryText)
      await syncAgentRunFromPayload(data, primaryText)
      attachAgentRunTraceToLastAiMessage()
      consumeStateUpdates(data)
      attachContextSummaryToLastAiMessage()
      attachThinkingStepsToLastAiMessage(data)
      attachTodoStepsToLastAiMessage(data)
      attachWorkflowTraceToLastAiMessage(data)
      attachApprovalCardToLastAiMessage(data)

      if (data.task) {
        showTaskConfirm(data.task)
        const taskRow = asRecord(data.task)
        emitAssistantPush({
          title: taskRow.title || '新任务',
          description: taskRow.description || '收到一条任务，请处理',
        })
      }
      if (!data.task && (data?.autoAction?.type === 'show_products_float' || data?.autoAction?.type === 'show_products')) {
        currentTask.value = null
      }

      if (data.autoAction) {
        handleAutoAction(data.autoAction, primaryText)
      }
      if (data.task) {
        maybeCloseAssistantFloatForShipmentTask(data.task, data.autoAction)
      }
    } else {
      await addRoundMessage('处理失败: ' + (data.message || '未知错误'))
    }
  }

  return {
    consumeStateUpdates,
    maybePrefetchProductAssistantFloat,
    executeRemoteChatRound,
  }
}
