import { ref, computed, watch, onMounted, onBeforeUnmount, type Ref } from 'vue'
import { useTutorialStore } from '@/stores/tutorial'
import { useModsStore } from '@/stores/mods'
import {
  readPersistedExcelAnalysisContext,
  persistExcelAnalysisContext,
  resolveExcelFilePathFromAnalysis,
  resolveExcelSheetOptionsFromContext,
  extractLikelyProductQueryKeyword,
  clearPersistedTaskPanelState,
  useChatHistoryPersistence,
  useChatTaskPanelPersistence,
} from './useChatPersistence'
import { useChatTaskList } from './useChatTaskList'
import { useChatMessages } from './useChatMessages'
import { useShipmentTask, type ShipmentTask } from './useShipmentTask'
import { usePrintService } from './usePrintService'
import { useExcelAnalysis } from './useExcelAnalysis'
import { isStartPrintMessage, detectRuntimeModeCommand } from '../utils/textParser'
import chatApi, { parseChatStreamErrorResponse } from '../api/chat'
import productsApi from '../api/products'
import { readPlannerSseResponse, isChatStreamEnabled, type PlannerSseEvent } from '@/utils/chatSseStream'
import { fetchShipmentRecordsForUnit, summarizeShipmentRecordsForAudit } from '@/utils/shipmentMgmtPostPrint'
import { isCoreWorkflowModInstalled } from '@/constants/coreWorkflowMod'
import { dispatchCoreWorkflowModRun } from '@/workflow/coreWorkflowDispatcher'
import { FHD_DB_WRITE_UNLOCKED_EVENT } from '@/fhd/dbTokenHeaders'
import { useChatWorkflowPanel } from './useChatWorkflowPanel'
import { useChatDbTokenGate } from './useChatDbTokenGate'
import { useChatExcelContext } from './useChatExcelContext'
import { useChatRequest } from './useChatRequest'
import { useChatResponseAttach } from './useChatResponseAttach'
import { useChatSessionHistory } from './useChatSessionHistory'
import type { UseChatViewOptions } from './useChatView'

function isDatabaseTokenRequirement(tokenName?: unknown, tokenDescription?: unknown): boolean {
  const raw = `${String(tokenName || '')} ${String(tokenDescription || '')}`.toUpperCase()
  return /DB_(READ|WRITE)_TOKEN|DATABASE TOKEN|数据库.*令牌|一级|二级|写入令牌|查看令牌/.test(raw)
}

export function useChatOrchestration(options: UseChatViewOptions) {
  const tutorialStore = useTutorialStore()
  const modsStore = useModsStore()
  const { sessionId } = options
  const proIntentExperienceEnabled = options.proIntentExperienceEnabled

  const historyPersistence = useChatHistoryPersistence({
    sessionId,
    getActiveModId: () => String(modsStore.activeModId || ''),
  })
  const { toPlainText, isWelcomeMessage } = historyPersistence

  const {
    messages,
    addMessage,
    addAndSaveMessage: addAndSaveMessageRaw,
    saveMessage,
    pushStreamingAiShell,
    applyPlainTextToMessageIndex,
    clearMessages,
    loadMessages,
    syncFromServer,
    queueVoice,
    clearVoiceQueue,
  } = useChatMessages(sessionId)

  const CHAT_TTS_ENABLED_KEY = 'xcagi_chat_tts_enabled'
  const ttsEnabled = ref(localStorage.getItem(CHAT_TTS_ENABLED_KEY) !== '0')

  function setTtsEnabled(enabled: boolean) {
    ttsEnabled.value = enabled
    localStorage.setItem(CHAT_TTS_ENABLED_KEY, enabled ? '1' : '0')
    if (!enabled) clearVoiceQueue()
  }

  async function addAndSaveMessage(
    content: string,
    role: 'user' | 'ai' | 'task' = 'ai',
    extras?: Parameters<typeof addAndSaveMessageRaw>[2],
  ): Promise<void> {
    await addAndSaveMessageRaw(content, role, extras, {
      speak: ttsEnabled.value && role === 'ai',
    })
  }

  const currentTask = ref<ShipmentTask | null>(null)
  const orderNumberFetching = ref(false)
  const isLoading = ref(false)
  const isStreamingReply = ref(false)
  const isExecuting = ref(false)
  const latestAssistantPush = ref<{ title: string; description: string } | null>(null)
  const proRuntimeTask = ref<{ title: string; statusText: string; statusClass: string; description: string } | null>(null)
  const chatMessagesRef = ref<HTMLElement | null>(null)
  let persistTaskPanelStateForSession: (targetSessionId?: string) => void = () => {}

  const {
    taskList,
    activeTaskId,
    expandedTaskIds,
    taskFilter,
    activeTask,
    filteredTaskList,
    createTaskId,
    sortTaskList,
    upsertTask,
    finishTask,
    failTask,
    cancelTaskById,
    retryTask,
    toggleTaskExpanded,
    setTaskFilter,
    clearTaskHistory,
    jumpToTaskMessage,
  } = useChatTaskList({
    chatMessagesRef,
    onPersist: () => persistTaskPanelStateForSession(),
  })

  const panelPersistence = useChatTaskPanelPersistence({
    sessionId,
    taskList,
    activeTaskId,
    expandedTaskIds,
    taskFilter,
    currentTask,
    sortTaskList,
  })
  persistTaskPanelStateForSession = panelPersistence.persistTaskPanelStateForSession
  const { applyPersistedTaskPanelStateForSession } = panelPersistence

  const pendingDbWriteChatRetryMessages = ref<string[] | null>(null)
  const plannerWriteUnlockResumeDraft = ref('')
  const lastRequestContextSummary = ref('')
  const isProMode = ref(false)
  const pushCopied = ref(false)

  const executeRemoteChatRoundRef: {
    fn: (msgs: string[], opts?: { fromWriteUnlock?: boolean }) => Promise<void>
  } = { fn: async () => {} }

  const dbGate = useChatDbTokenGate({
    sessionId,
    isProMode,
    pendingDbWriteChatRetryMessages,
    plannerWriteUnlockResumeDraft,
    executeRemoteChatRound: (msgs, opts) => executeRemoteChatRoundRef.fn(msgs, opts),
  })
  const { handleChatRequiresToken, resolveEffectiveProModeState } = dbGate

  const excelCtx = useChatExcelContext({ sessionId, addAndSaveMessage })
  const {
    lastExcelAnalysisContext,
    linkedExcelSheet,
    linkedExcelAllSheets,
    multimodalStaging,
    multimodalPendingCount,
    excelSheetOptions,
    resolveExcelAnalysisContextForRequest,
    injectExcelContextPayload,
    consumeMultimodalIntoPlannerContext,
    onMultimodalFileChange,
    bindExcelSheetToChat,
    bindAllExcelSheetsToChat,
  } = excelCtx

  const responseAttach = useChatResponseAttach({
    messages,
    lastRequestContextSummary,
    taskList,
    upsertTask,
    createTaskId,
  })
  const {
    getLastAiMessageRef,
    attachThinkingStepsToLastAiMessage,
    attachTodoStepsToLastAiMessage,
    attachWorkflowTraceToLastAiMessage,
    attachContextSummaryToLastAiMessage,
    syncTaskFromChatResponse,
  } = responseAttach

  const chatRequest = useChatRequest({
    messages,
    proIntentExperienceEnabled,
    isProMode,
    lastRequestContextSummary,
    plannerWriteUnlockResumeDraft,
    resolveEffectiveProModeState: dbGate.resolveEffectiveProModeState,
    getModeScopedUserId: dbGate.getModeScopedUserId,
    resolveChatDbTokensForPayload: dbGate.resolveChatDbTokensForPayload,
    injectExcelContextPayload,
    consumeMultimodalIntoPlannerContext,
  })

  const {
    loadingProgressText,
    chatBatchQueue,
    enqueueChatBatchMessage,
    buildPlannerChatRequestPayload,
    requestChatByMode,
    requestChatByModeBatch,
    getChatBatchDebounceMs,
    setLoadingProgress,
    startWaitProgressTimer,
    stopLoadingProgress,
    requestChatByModeWithTimeout,
    requestChatByModeBatchWithTimeout,
    resolveChatTimeoutMs,
  } = chatRequest

  function generateSessionId(): string {
    return Date.now().toString(36) + Math.random().toString(36).substr(2)
  }

  function scrollToBottom() {
    if (chatMessagesRef.value) {
      chatMessagesRef.value.scrollTop = chatMessagesRef.value.scrollHeight
    }
  }

  function normalizeServerContentToHtml(raw: unknown): string {
    const text = String(raw || '')
    if (/<[a-z][\s\S]*>/i.test(text)) return text
    const div = document.createElement('div')
    div.textContent = text
    return div.innerHTML.replace(/\n/g, '<br>')
  }

  const sessionHistory = useChatSessionHistory({
    sessionId,
    taskList,
    activeTaskId,
    expandedTaskIds,
    taskFilter,
    currentTask,
    lastExcelAnalysisContext,
    linkedExcelSheet,
    linkedExcelAllSheets,
    loadMessages,
    clearMessages,
    persistTaskPanelStateForSession,
    applyPersistedTaskPanelStateForSession,
    clearPersistedTaskPanelState,
    generateSessionId,
    normalizeServerContentToHtml,
  })
  const {
    showHistory,
    historySessions,
    historyLoading,
    historyError,
    showHistoryPanel,
    loadSession,
    clearHistorySessions,
    newConversation,
    registerHistoryModWatch,
  } = sessionHistory


  const {
    lastShipmentExecution,
    handleModifyCommand: handleShipmentModify,
    hydrateTaskOrderNumber,
    enrichShipmentPreviewProducts,
    getTaskTableColumns,
    getTaskTableItems,
    getTaskOrderNumber
  } = useShipmentTask({ addAndSaveMessage }, currentTask)

  const {
    isPrinting,
    executePrintTask,
    buildPrintSummaryMessage
  } = usePrintService()

  const {
    excelAnalyzeUploading,
    excelAnalyzeInputRef,
    triggerUpload,
    onExcelAnalyzeFileChange,
    setOnMultimodalFileChangeCallback
  } = useExcelAnalysis(
    { addMessage, saveMessage },
    {
      onAnalyzed: ({ fileName, summary, result }) => {
        const persistedPath = resolveExcelFilePathFromAnalysis(result)
        const payload = {
          file_name: fileName,
          ...(persistedPath ? { file_path: persistedPath } : {}),
          summary,
          fields: Array.isArray(result?.fields) ? result.fields : [],
          preview_data: result?.preview_data || {},
          sheets: Array.isArray(result?.sheets) ? result.sheets : []
        }
        lastExcelAnalysisContext.value = payload
        linkedExcelAllSheets.value = false
        const sheetOptions = resolveExcelSheetOptionsFromContext(payload)
        linkedExcelSheet.value = sheetOptions[0] || null
        window.dispatchEvent(new CustomEvent('xcagi:excel-sheet-context', {
          detail: {
            select_all_sheets: false,
            selected_sheet: linkedExcelSheet.value,
            excel_analysis: payload
          }
        }))
        const sid = String(sessionId.value || '').trim() || 'default'
        persistExcelAnalysisContext(sid, payload)
        window.requestAnimationFrame(() => {
          const displayFileName = String(fileName || '').trim()
            || String(persistedPath || '').split(/[\\/]/).pop()
            || 'excel.xlsx'
          const prefix = `@uploads/${displayFileName} `
          const fillInput = (window as unknown).__VUE_CHAT_FILL__
          if (typeof fillInput === 'function' && fillInput(prefix)) return

          // 兜底：当宿主未注入 __VUE_CHAT_FILL__ 时，仍尝试直接写 DOM。
          const msgInput = document.querySelector('#view-chat #messageInput') as HTMLTextAreaElement | null
          if (msgInput) {
            msgInput.value = prefix
            msgInput.dispatchEvent(new Event('input', { bubbles: true }))
            msgInput.focus()
          }
        })
        const task = taskList.value.find((t) => t.type === 'excel_analyze' && t.status === 'running')
        if (task) {
          upsertTask({
            id: task.id,
            title: task.title,
            type: task.type,
            source: task.source,
            status: 'success',
            progress: 100,
            summary,
            messageRef: getLastAiMessageRef()
          })
        }
      },
      onAnalyzeStart: ({ fileName }) => {
        upsertTask({
          id: createTaskId('excel'),
          title: `分析Excel：${fileName}`,
          type: 'excel_analyze',
          source: 'excel',
          status: 'running',
          progress: 5
        })
      },
      onAnalyzeProgress: ({ step, progress }) => {
        const task = taskList.value.find((t) => t.type === 'excel_analyze' && t.status === 'running')
        if (!task) return
        upsertTask({
          id: task.id,
          title: task.title,
          type: task.type,
          source: task.source,
          status: 'running',
          progress: progress ?? task.progress,
          stage: step
        })
      },
      onAnalyzeDone: ({ success, message }) => {
        const task = taskList.value.find((t) => t.type === 'excel_analyze' && t.status === 'running')
        if (!task) return
        if (success) {
          finishTask(task.id, task.summary || 'Excel 分析完成')
        } else {
          failTask(task.id, message || 'Excel 分析失败')
        }
      }
    }
  )

  setOnMultimodalFileChangeCallback(onMultimodalFileChange)
  const taskTableColumns = computed(() => getTaskTableColumns(currentTask.value as unknown))
  const taskTableItems = computed(() => getTaskTableItems(currentTask.value as unknown))
  const taskOrderNumber = computed(() => getTaskOrderNumber(currentTask.value))
  /** 出货管理 AI 员工：打印成功后拉取出货记录、统计与审计，并提示保存（导出）/推送 */
  async function runShipmentMgmtAfterPrintSuccess(ctx: {
    purchaseUnit: string
    orderId: number | null
    filePath: string
    labelCount: number
  }): Promise<void> {
    const enabled = readWorkflowEmployeeEnabledMap()
    if (!enabled.shipment_mgmt) return
    const unit = String(ctx.purchaseUnit || '').trim()
    if (!unit) return

    const rows = await fetchShipmentRecordsForUnit(unit)
    const summary = summarizeShipmentRecordsForAudit(rows, unit, ctx.orderId)
    dispatchCoreWorkflowModRun(isCoreWorkflowModInstalled(modsStore.modsForUi), 'shipment_mgmt', {
      action: 'audit_summary',
      purchaseUnit: unit,
      orderId: ctx.orderId,
      headline: summary.headline,
    })
    const fullText = summary.detailLines.join('\n')
    const at = Date.now()

    await addAndSaveMessage(`【出货管理 · 打印后审计】\n${fullText}`, 'ai')
    const auditMsgRef = getLastAiMessageRef()

    try {
      window.dispatchEvent(new CustomEvent('xcagi:shipment-record-updated'))
    } catch {
      /* ignore */
    }

    if (taskList.value.some((t) => t.id === 'workflow_emp_shipment_mgmt')) {
      upsertWorkflowEmployeeTask('shipment_mgmt', {
        lastShipmentAudit: {
          at,
          line: summary.headline,
          detail: fullText,
        },
      })
    }

    emitAssistantPush({
      title: '出货管理 · 打印后审计',
      description: `${summary.headline}。建议打开出货记录核对，按需导出 Excel 再推送同事。`,
      feature: 'shipment',
    })

    upsertTask({
      id: createTaskId('shipment_audit'),
      type: 'shipment_audit_hint',
      source: 'system',
      title: '出货记录 · 打印后审计建议',
      status: 'success',
      progress: 100,
      summary: fullText,
      messageRef: auditMsgRef,
      payload: {
        purchaseUnit: unit,
        suggestView: 'shipment-records',
        labelCount: ctx.labelCount,
        filePath: ctx.filePath,
      },
    })
  }

  async function handleStartPrintCommand(message: string): Promise<boolean> {
    if (!isStartPrintMessage(message)) return false
    const printTaskId = createTaskId('print')
    upsertTask({
      id: printTaskId,
      type: 'print',
      source: 'print',
      title: '打印任务',
      status: 'running',
      progress: 20
    })

    const context = lastShipmentExecution.value
    if (!context) {
      await addAndSaveMessage('暂无可打印任务。请先生成发货单，再发送"开始打印"。', 'ai')
      return true
    }

    const labelPaths = Array.isArray(context.labelPaths) ? context.labelPaths : []
    const filePath = context.filePath || ''
    const purchaseUnit = String(context.purchaseUnit || '').trim()
    const orderId = context.orderId

    if (!labelPaths.length && !filePath) {
      await addAndSaveMessage('最近一次任务未包含可打印文件。请重新生成发货单后再试。', 'ai')
      return true
    }

    const summary = await executePrintTask(labelPaths, filePath, orderId ?? undefined, purchaseUnit)
    const resultText = buildPrintSummaryMessage(summary, labelPaths.length, filePath, purchaseUnit)
    await addAndSaveMessage(resultText, 'ai')
    upsertTask({
      id: printTaskId,
      type: 'print',
      source: 'print',
      title: '打印任务',
      status: summary.success ? 'success' : 'failed',
      progress: 100,
      summary: resultText,
      error: summary.success ? '' : (summary.message || '打印失败'),
      messageRef: getLastAiMessageRef()
    })
    const shipmentListId = String(context?.taskListId || '').trim()
    if (shipmentListId) {
      if (summary.success) {
        upsertTask({
          id: shipmentListId,
          type: 'shipment',
          source: 'shipment',
          title: '发货单生成任务',
          status: 'success',
          progress: 100,
          stage: '',
          summary: `已生成并打印。${resultText.replace(/\s+/g, ' ').slice(0, 240)}`,
          messageRef: getLastAiMessageRef()
        })
      } else {
        upsertTask({
          id: shipmentListId,
          type: 'shipment',
          source: 'shipment',
          title: '发货单生成任务',
          status: 'failed',
          stage: '打印失败',
          error: summary.message || '打印失败',
          summary: '发货单文档已生成，打印未成功。可重试「开始打印」。'
        })
      }
    }
    if (summary.success) {
      await runShipmentMgmtAfterPrintSuccess({
        purchaseUnit,
        orderId,
        filePath,
        labelCount: labelPaths.length,
      })
    }
    return true
  }

  function applyProRuntimeMode(actionType: string, enabled: boolean): boolean {
    if (!isProMode.value) return false
    const shouldEnable = enabled !== false
    const toggleWorkMode = (window as unknown).setWorkModeFromChat
    const toggleMonitorMode = (window as unknown).setMonitorModeFromChat

    if (actionType === 'show_monitor') {
      if (typeof toggleMonitorMode === 'function') {
        toggleMonitorMode(shouldEnable)
      } else {
        console.warn('[pro-runtime] monitor mode entry missing; skip fallback to work mode')
        return false
      }
    } else {
      if (typeof toggleWorkMode !== 'function') {
        console.warn('[pro-runtime] work mode entry missing')
        return false
      }
      toggleWorkMode(shouldEnable)
    }

    if (shouldEnable && typeof (window as unknown).refreshWorkModeMonitorList === 'function') {
      ;(window as unknown).refreshWorkModeMonitorList()
    }

    window.dispatchEvent(new CustomEvent('xcagi:pro-runtime-mode-changed', {
      detail: { type: actionType, enabled: shouldEnable }
    }))
    return true
  }

  async function tryHandleRuntimeModeCommand(message: string): Promise<boolean> {
    if (!isProMode.value) return false
    const modeAction = detectRuntimeModeCommand(message)
    if (!modeAction) return false

    const switched = applyProRuntimeMode(modeAction, true)
    const reply = switched
      ? (modeAction === 'show_monitor' ? '正在切换到监控模式...' : '正在切换到工作模式...')
      : (modeAction === 'show_monitor'
        ? '监控模式入口不可用，已保持当前模式不变。'
        : '工作模式入口不可用，已保持当前模式不变。')
    await addAndSaveMessage(reply, 'ai')
    return true
  }

  async function refetchTaskOrderNumber() {
    const t = currentTask.value
    if (!t || t.type !== 'shipment_generate' || t.completed) return
    orderNumberFetching.value = true
    try {
      await hydrateTaskOrderNumber(t as unknown, { force: true })
    } finally {
      orderNumberFetching.value = false
    }
  }

  function setCustomOrderNumber(value: string) {
    const t = currentTask.value
    if (!t) return
    t.customOrderNumber = value
  }

  function shouldAutoRunTask(task: unknown): boolean {
    if (!task || task?.completed) return false
    const taskType = String(task?.type || '').trim().toLowerCase()
    if (taskType === 'excel_import') return true
    if (taskType.includes('excel') && taskType.includes('import')) return true

    const toolId = String(
      task?.payload?.tool_id
      || task?.payload?.params?.tool_id
      || task?.tool_id
      || ''
    ).trim().toLowerCase()
    if (toolId === 'import_excel_to_database' || toolId === 'excel_import') return true
    if (toolId.includes('excel') && toolId.includes('import')) return true
    return false
  }

  function scheduleAutoConfirmTask(task: unknown): void {
    if (!task || task?.completed || !task?.api_url) return
    if (task.__xcagiAutoConfirmScheduled) return
    task.__xcagiAutoConfirmScheduled = true
    window.setTimeout(() => {
      if (currentTask.value !== task) return
      if (isExecuting.value || task?.completed) return
      void confirmTask()
    }, 0)
  }

  function showTaskConfirm(task: unknown) {
    const nextTask = { ...(task || {}) }
    currentTask.value = nextTask
    if (shouldAutoRunTask(nextTask)) {
      scheduleAutoConfirmTask(nextTask)
    }

    if (nextTask?.type !== 'shipment_generate' || nextTask?.completed) return

    const existingOrderNo = String(
      nextTask?.customOrderNumber
      || nextTask?.order_number
      || nextTask?.data?.order_number
      || nextTask?.document?.order_number
      || ''
    ).trim()

    if (existingOrderNo) {
      nextTask.customOrderNumber = existingOrderNo
      return
    }

    nextTask.customOrderNumber = ''
    hydrateTaskOrderNumber(nextTask as unknown).catch(() => {})
    enrichShipmentPreviewProducts(nextTask as unknown).catch(() => {})
  }

  function emitAssistantPush(payload: unknown = {}) {
    const detail = {
      title: String(payload.title || '任务推送').trim(),
      description: String(payload.description || '').trim(),
      feature: payload.feature || '',
      query: payload.query || ''
    }
    latestAssistantPush.value = detail
    window.dispatchEvent(new CustomEvent('xcagi:assistant-push', { detail }))
  }

  /** 待确认的发货单生成任务出现时收起顶部副窗，突出右侧「当前任务」面板；若同时需打开产品副窗则不收起 */
  function maybeCloseAssistantFloatForShipmentTask(task: unknown, autoAction: unknown) {
    // 教程步骤若声明了 assistantTab，需要副窗保持打开以定位高亮；否则发货任务触发的「收起副窗」会与教程打开副窗竞态，导致点空气。
    if (tutorialStore.isActive && tutorialStore.currentStep?.assistantTab) {
      return
    }
    if (!task || task.completed) return
    const toolId = String(
      task?.payload?.tool_id || task?.payload?.params?.tool_id || ''
    ).trim()
    const isShipment =
      task.type === 'shipment_generate' || toolId === 'shipment_generate'
    if (!isShipment) return
    const at = String(autoAction?.type || '').trim()
    if (at === 'show_products' || at === 'show_products_float') return
    window.dispatchEvent(
      new CustomEvent('xcagi:close-assistant-float', { detail: { reason: 'shipment_task_confirm' } })
    )
  }

  const workflowPanel = useChatWorkflowPanel({
    taskList,
    activeTaskId,
    expandedTaskIds,
    taskFilter,
    currentTask,
    upsertTask,
    sortTaskList,
    createTaskId,
    persistTaskPanelStateForSession,
    showTaskConfirm,
    emitAssistantPush,
    maybeCloseAssistantFloatForShipmentTask,
  })
  const { readWorkflowEmployeeEnabledMap, upsertWorkflowEmployeeTask } = workflowPanel

  /** 出货管理 AI 员工：打印成功后拉取出货记录、统计与审计，并提示保存（导出）/推送 */
  function buildTaskCompletedDescription(successMsg: string, data: unknown): string {
    const parts = [successMsg || '任务执行成功']
    const docName = data?.doc_name || data?.data?.doc_name || data?.document?.filename
    const orderNo = data?.order_number || data?.data?.order_number || data?.document?.order_number
    const filePath = data?.file_path || data?.data?.file_path || data?.document?.filepath
    const labels = Array.isArray(data?.labels) ? data.labels : (Array.isArray(data?.data?.labels) ? data.data.labels : [])
    if (docName) parts.push(`文档：${docName}`)
    if (orderNo) parts.push(`单号：${orderNo}`)
    if (typeof data?.record_id !== 'undefined' && data?.record_id !== null) parts.push(`记录ID：${data.record_id}`)
    if (typeof data?.order_id !== 'undefined' && data?.order_id !== null) parts.push(`订单ID：${data.order_id}`)
    if (labels.length) parts.push(`标签：${labels.length} 张`)
    if (filePath) parts.push(`路径：${filePath}`)
    return parts.join('；')
  }

  function buildShipmentDownloadUrl(data: unknown): string {
    const directUrl = data?.download_url || data?.data?.download_url
    if (directUrl && typeof directUrl === 'string') return directUrl

    const docName = data?.doc_name || data?.data?.doc_name || data?.document?.filename
    if (!docName || typeof docName !== 'string') return ''

    return `/api/shipment/download/${encodeURIComponent(docName)}`
  }

  function normalizeRecordId(value: unknown): number | null {
    if (value === null || value === undefined || value === '') return null
    const n = Number(value)
    if (!Number.isFinite(n)) return null
    const normalized = Math.trunc(n)
    return normalized > 0 ? normalized : null
  }

  function extractShipmentExecutionContext(data: unknown) {
    const filePath = data?.file_path || data?.data?.file_path || data?.document?.filepath || ''
    const purchaseUnit = String(
      data?.purchase_unit
      ?? data?.data?.purchase_unit
      ?? data?.document?.purchase_unit
      ?? ''
    ).trim()
    const orderId = normalizeRecordId(
      data?.order_id
      ?? data?.record_id
      ?? data?.data?.order_id
      ?? data?.data?.record_id
      ?? data?.document?.order_id
      ?? data?.document?.record_id
      ?? data?.data?.document?.order_id
      ?? data?.data?.document?.record_id
    )
    const labelsRaw = Array.isArray(data?.labels)
      ? data.labels
      : (Array.isArray(data?.data?.labels) ? data.data.labels : [])

    const labelPaths: string[] = []
    labelsRaw.forEach((label: unknown) => {
      if (typeof label === 'string' && label.trim()) {
        labelPaths.push(label.trim())
        return
      }
      if (label && typeof label === 'object') {
        const p =
          label.file_path ||
          label.path ||
          label.filePath ||
          label.filepath ||
          ''
        if (typeof p === 'string' && p.trim()) {
          labelPaths.push(p.trim())
        }
      }
    })

    return {
      filePath,
      purchaseUnit,
      orderId,
      labelPaths: Array.from(new Set(labelPaths))
    }
  }

  async function confirmTask(): Promise<void> {
    if (!currentTask.value || isExecuting.value) return

    const task = currentTask.value
    const apiUrl = task.api_url
    const method = (task.method || 'POST').toUpperCase()
    const payload = { ...(task.payload || {}) }

    if (task?.type === 'shipment_generate') {
      if (!String(task?.customOrderNumber || '').trim()) {
        await hydrateTaskOrderNumber(task as unknown)
      }
      const customOrderNumber = String(task?.customOrderNumber || '').trim()
      payload.params = { ...(payload.params || {}) }
      if (customOrderNumber) {
        payload.params.order_number = customOrderNumber
      } else if (Object.prototype.hasOwnProperty.call(payload.params, 'order_number')) {
        delete payload.params.order_number
      }
    }

    if (!apiUrl) {
      await addAndSaveMessage('任务执行失败：缺少 API 地址', 'ai')
      currentTask.value = null
      return
    }

    isExecuting.value = true
    let keepTaskCard = false
    let shipmentTaskId = ''
    if (task?.type === 'shipment_generate') {
      shipmentTaskId = createTaskId('shipment')
      upsertTask({
        id: shipmentTaskId,
        type: 'shipment',
        source: 'shipment',
        title: '发货单生成任务',
        status: 'running',
        progress: 20
      })
    }

    try {
      let result
      if (method === 'GET') {
        result = await fetch(apiUrl)
      } else {
        result = await fetch(apiUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        })
      }

      const data = await result.json().catch(() => ({}))

      if (data?.requires_token) {
        if (isDatabaseTokenRequirement(data?.token_name, data?.token_description || data?.message)) {
          return
        }
        handleChatRequiresToken(data?.token_name, data?.token_description || data?.message, null)
        const tokenMsg = String(data?.message || data?.token_description || '当前操作需要二级数据库写入令牌').trim()
        await addAndSaveMessage('[提示] ' + tokenMsg, 'ai')
        keepTaskCard = true
        currentTask.value = {
          ...task,
          description: `${tokenMsg}（已弹出令牌输入框，输入后请再次点击确认执行）`,
        }
        return
      }

      if (result.ok) {
        const successMsg = data.message || data.msg || '任务执行成功'
        const shipmentDocUrl =
          task?.type === 'shipment_generate' ? buildShipmentDownloadUrl(data) : ''
        await addAndSaveMessage('[成功] ' + successMsg, 'ai', {
          ...(shipmentDocUrl ? { shipmentDownloadUrl: shipmentDocUrl } : {})
        })
        if (task?.type === 'shipment_generate') {
          lastShipmentExecution.value = {
            ...extractShipmentExecutionContext(data),
            ...(shipmentTaskId ? { taskListId: shipmentTaskId } : {})
          }
          if (shipmentTaskId) {
            upsertTask({
              id: shipmentTaskId,
              type: 'shipment',
              source: 'shipment',
              title: '发货单生成任务',
              status: 'running',
              progress: 70,
              stage: '发货单已生成，待打印',
              summary: buildTaskCompletedDescription(successMsg, data),
              messageRef: getLastAiMessageRef()
            })
          }
        }
        currentTask.value = {
          ...task,
          title: `${task.title || '任务'}（已完成）`,
          description: buildTaskCompletedDescription(successMsg, data),
          order_number: data?.order_number || data?.data?.order_number || data?.document?.order_number || '',
          downloadUrl: task?.type === 'shipment_generate' ? buildShipmentDownloadUrl(data) : '',
          completed: true
        }
        keepTaskCard = true

        if (task.switch_view) {
          handleAutoAction({ type: task.switch_view })
        }
      } else {
        const errMsg = (data && (data.message || data.msg || data.error)) || `执行失败 (HTTP ${result.status})`
        await addAndSaveMessage('[失败] 任务执行失败：' + errMsg, 'ai')
        if (shipmentTaskId) {
          failTask(shipmentTaskId, errMsg)
        }
      }
    } catch (e: unknown) {
      await addAndSaveMessage('[失败] 任务执行失败：' + (e.message || '网络错误'), 'ai')
      if (shipmentTaskId) {
        failTask(shipmentTaskId, e.message || '网络错误')
      }
    } finally {
      isExecuting.value = false
      if (!keepTaskCard) {
        currentTask.value = null
      }
    }
  }

  function cancelTask() {
    currentTask.value = null
    persistTaskPanelStateForSession()
  }

  function handleAutoAction(action: unknown, userMessage: string = '') {
    console.log('[AutoAction] 触发:', action, '| 用户消息:', userMessage)
    const type = action?.type || ''
    const actionQuery = String(action?.query || action?.keyword || userMessage || '').trim()

    if (type === 'set_work_mode') {
      applyProRuntimeMode(type, action?.enabled)
    } else if (type === 'show_monitor') {
      applyProRuntimeMode(type, true)
    }

    // 与普通模式一致：无论是否专业 UI，产品副窗都应打开（工作流也会下发 show_products_float）
    if (type === 'show_products' || type === 'show_products_float') {
      emitAssistantPush({
        title: '产品查询',
        description: '已在副窗打开产品卡片编辑窗口，可直接查询并修改。',
        feature: 'products',
        query: actionQuery
      })
      const floatDetail: Record<string, unknown> = {
        feature: 'products',
        query: actionQuery,
        forceOpen: true
      }
      const hyd = action?.hydrateProductSearch
      if (hyd && Array.isArray(hyd.rows)) {
        floatDetail.hydrateProductSearch = { rows: hyd.rows, total: hyd.total }
      }
      window.dispatchEvent(new CustomEvent('xcagi:open-assistant-float', { detail: floatDetail }))
      // 原逻辑：仅专业 UI 下 show_products 会额外跳到产品页（show_products_float 不跳页）
      if (type === 'show_products' && isProMode.value) {
        window.dispatchEvent(new CustomEvent('xcagi:switch-view', { detail: { view: 'products' } }))
      }
      return
    }

    const viewMap: Record<string, string> = {
      'show_chat': 'chat',
      'show_products': 'products',
      'show_materials': 'materials',
      'show_orders': 'orders',
      'show_print': 'print',
      'show_customers': 'customers',
      'show_labels_export': 'print'
    }

    console.log('[AutoAction] 视图映射 type:', type, '-> 目标视图:', viewMap[type] || '未匹配')
    if (viewMap[type]) {
      console.log('[AutoAction] 派发 xcagi:switch-view 事件, detail:', { view: viewMap[type] })
      window.dispatchEvent(new CustomEvent('xcagi:switch-view', { detail: { view: viewMap[type] } }))
      if (viewMap[type] === 'products') {
        emitAssistantPush({
          title: '产品查询',
          description: '可在顶部副窗中直接查询并修改产品信息。',
          feature: 'products',
          query: userMessage || ''
        })
        window.dispatchEvent(new CustomEvent('xcagi:open-assistant-float', {
          detail: { feature: 'products', query: userMessage || '' }
        }))
      }
    }
    const event = new CustomEvent('auto-action', { detail: { action, userMessage } })
    window.dispatchEvent(event)

    if (!isProMode.value && ['set_work_mode', 'show_monitor'].includes(type)) {
      return
    }

    if (typeof (window as unknown).legacyAutoActionHandler === 'function') {
      ;(window as unknown).legacyAutoActionHandler(action, userMessage)
    }
  }
  function maybePrefetchProductAssistantFloat(userText: string) {
    // 教程进行中也需要与聊天请求并行预开产品副窗；否则会出现「不开教程立刻出副窗、走了教程反而要等 AI」的体验差。
    // 副窗切到「协助/产品查询」若与某步高亮冲突，用户仍可用教程卡片「下一步」或退出教程。
    const kw = extractLikelyProductQueryKeyword(userText)
    if (!kw) return
    window.dispatchEvent(
      new CustomEvent('xcagi:open-assistant-float', {
        detail: { feature: 'products', query: kw, forceOpen: true }
      })
    )
  }

  async function executeRemoteChatRound(
    remoteMessages: string[],
    opts?: { fromWriteUnlock?: boolean }
  ) {
    if (!remoteMessages.length) return
    if (!opts?.fromWriteUnlock) {
      pendingDbWriteChatRetryMessages.value = null
      plannerWriteUnlockResumeDraft.value = ''
    }
    const primaryText = remoteMessages[0] || ''

    /** 未开专业版界面且未勾选「专业意图体验」时：查产品类话术不必等 /ai/chat 或连通性探测，直接走产品列表接口 */
    const kwFast =
      remoteMessages.length === 1 &&
      !resolveEffectiveProModeState() &&
      !proIntentExperienceEnabled?.value &&
      !resolveExcelAnalysisContextForRequest() &&
      multimodalPendingCount.value === 0
        ? extractLikelyProductQueryKeyword(primaryText)
        : null

    // 快路径会自己拉产品列表并注水副窗；再 prefetch 会多打一遍相同接口，徒增等待
    if (!kwFast) {
      maybePrefetchProductAssistantFloat(primaryText)
    }

    if (kwFast) {
      isLoading.value = true
      setLoadingProgress('正在查询产品库…')
      startWaitProgressTimer()
      try {
        const resp = await productsApi.searchProducts(kwFast)
        if (resp && (resp as unknown).success === false) {
          throw new Error(String((resp as unknown)?.message || '产品库查询失败'))
        }
        const raw = (resp as unknown)?.data ?? (resp as unknown)?.products ?? (resp as unknown)?.items
        const rows = Array.isArray(raw) ? raw : []
        const lines = rows.slice(0, 3).map((row: unknown) => {
          const m = String(row.model_number || '').trim()
          const n = String(row.name || row.product_name || '-').trim()
          const p = Number(row.price || 0)
          const pf = Number.isFinite(p) ? p.toFixed(2) : '0.00'
          return `- ${m || '-'} / ${n} / ￥${pf}`
        })
        const previewSuffix = lines.length
          ? `\n预览命中 ${rows.length} 条：\n${lines.join('\n')}`
          : ''
        const hasResults = lines.length > 0
        const responseText = hasResults
          ? `已帮你打开产品副窗并带入「${kwFast}」。可在卡片中查看与修改。${previewSuffix}`
          : `未在产品库中找到「${kwFast}」，请确认型号或关键词后重试。`
        const payload: unknown = {
          success: true,
          response: responseText,
          ...(hasResults ? { autoAction: { type: 'show_products_float', query: kwFast } } : {})
        }
        const mappedRows = rows.slice(0, 20).map((r: unknown) => ({
          id: r.id,
          model_number: r.model_number || '',
          name: r.name || r.product_name || '',
          price: Number(r.price || 0),
          unit: r.unit || ''
        }))
        const totalFromApi = typeof (resp as unknown)?.total === 'number' ? (resp as unknown).total : rows.length
        await addAndSaveMessage(payload.response, 'ai')
        syncTaskFromChatResponse(payload, primaryText)
        attachContextSummaryToLastAiMessage()
        attachThinkingStepsToLastAiMessage(payload)
        attachTodoStepsToLastAiMessage(payload)
        attachWorkflowTraceToLastAiMessage(payload)
        if (!payload.task && (payload.autoAction?.type === 'show_products_float' || payload.autoAction?.type === 'show_products')) {
          currentTask.value = null
        }
        if (payload.autoAction) {
          handleAutoAction(
            {
              ...payload.autoAction,
              hydrateProductSearch: { rows: mappedRows, total: totalFromApi }
            },
            primaryText
          )
        }
        return
      } catch {
        /* 回退到下方 unified / chat 全链路 */
      } finally {
        isLoading.value = false
        stopLoadingProgress()
      }
    }

    /** ChatView 主路径：单条消息走 Planner SSE，token 逐字写入气泡；批量仍用 JSON。可用 ``VITE_CHAT_STREAM=0`` 关闭。 */
    if (remoteMessages.length === 1 && isChatStreamEnabled()) {
      const primaryForStream = remoteMessages[0] || ''
      isStreamingReply.value = true
      isLoading.value = true
      const runtimeProForLoadingS = resolveEffectiveProModeState()
      const hybridS = !!proIntentExperienceEnabled?.value && !runtimeProForLoadingS
      setLoadingProgress(hybridS ? '专业意图处理中（流式）…' : '正在流式生成回复…')
      startWaitProgressTimer()
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
        const { body } = buildPlannerChatRequestPayload(primaryForStream, {
          fromWriteUnlock: !!opts?.fromWriteUnlock
        })
        const res = await chatApi.sendChatStream(body as unknown, { signal: controller.signal })
        if (!res.ok) {
          throw new Error(await parseChatStreamErrorResponse(res))
        }
        await readPlannerSseResponse(res, (ev: PlannerSseEvent) => {
          if (ev.type === 'token') {
            streamPlain += ev.text || ''
            applyPlainTextToMessageIndex(msgIndex, streamPlain)
            flushTtsFromStream(streamPlain, false)
            setLoadingProgress('正在生成回复…')
          } else if (ev.type === 'done') {
            doneResult = ev.result
          } else if (ev.type === 'error') {
            sseError = String(ev.message || '流式接口错误')
          } else if (ev.type === 'requires_token') {
            const tokenName = ev.token_name || ''
            const tokenDesc = ev.token_description || ''
            if (isDatabaseTokenRequirement(tokenName, tokenDesc)) return
            handleChatRequiresToken(tokenName, tokenDesc, remoteMessages)
            streamPlain += `\n[需要授权：${tokenDesc || tokenName || '授权信息'}]\n`
            applyPlainTextToMessageIndex(msgIndex, streamPlain)
            flushTtsFromStream(streamPlain, false)
            const upTok = String(tokenName || '').toUpperCase()
            if (
              upTok.includes('WRITE') ||
              /写入|导入|入库|二级|数据库写入|DB_WRITE/i.test(String(tokenDesc || ''))
            ) {
              plannerWriteUnlockResumeDraft.value = streamPlain
            }
          }
        })
        if (sseError) {
          throw new Error(sseError)
        }
        const finalText = String((doneResult as unknown)?.response ?? streamPlain).trim() || streamPlain || '（无内容）'
        applyPlainTextToMessageIndex(msgIndex, finalText)
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
        await saveMessage('ai', finalText)
        const wrap =
          doneResult && typeof doneResult === 'object'
            ? (doneResult as unknown)
            : { success: true, response: finalText }
        syncTaskFromChatResponse(wrap, primaryText)
        attachContextSummaryToLastAiMessage()
        attachThinkingStepsToLastAiMessage(wrap)
        attachTodoStepsToLastAiMessage(wrap)
        attachWorkflowTraceToLastAiMessage(wrap)
        if (wrap.task) {
          showTaskConfirm(wrap.task)
          emitAssistantPush({
            title: wrap.task.title || '新任务',
            description: wrap.task.description || '收到一条任务，请处理'
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
          err?.name === 'AbortError'
            ? `请求超时（>${Math.floor(timeoutMsS / 1000)}s）或已中断`
            : (err?.message || '流式对话失败')
        applyPlainTextToMessageIndex(msgIndex, `处理失败：${errText}`)
        await saveMessage('ai', `处理失败：${errText}`)
      } finally {
        isStreamingReply.value = false
        window.clearTimeout(killTimer)
        isLoading.value = false
        stopLoadingProgress()
      }
      return
    }

    isLoading.value = true
    isStreamingReply.value = false
    const runtimeProForLoading = resolveEffectiveProModeState()
    const hybridNormalUiProChannel =
      !!proIntentExperienceEnabled?.value && !runtimeProForLoading
    setLoadingProgress(
      hybridNormalUiProChannel
        ? '专业意图处理中（普通界面槽位）...'
        : '正在理解你的问题...'
    )
    let data: unknown
    try {
      // 不再在发聊天前阻塞等待 /api/ai/test（最多 3s），否则「慢」往往来自这里而非 AI
      setLoadingProgress(
        remoteMessages.length > 1
          ? `正在批量处理 ${remoteMessages.length} 条消息...`
          : '正在整理上下文...'
      )
      startWaitProgressTimer()
      const base = resolveChatTimeoutMs(primaryText)
      const timeoutMs = Math.min(120000, remoteMessages.length <= 1 ? base : base * remoteMessages.length)
      if (remoteMessages.length === 1) {
        data = await requestChatByModeWithTimeout(remoteMessages[0], timeoutMs, {
          fromWriteUnlock: !!opts?.fromWriteUnlock
        })
      } else {
        data = await requestChatByModeBatchWithTimeout(remoteMessages, timeoutMs)
      }
      const head = remoteMessages.length === 1 ? data : data?.results?.[0]
      setLoadingProgress('已收到响应，正在解析执行计划...')
      if (head?.data?.action === 'workflow_confirmation_required') {
        setLoadingProgress('已生成计划，等待你确认执行...')
      } else if (head?.data?.action === 'workflow_done') {
        setLoadingProgress('执行完成，正在整理结果...')
      } else if (head?.data?.action === 'workflow_failed') {
        setLoadingProgress('执行失败，正在整理错误信息...')
      }
    } catch (err: unknown) {
      data = {
        success: false,
        message: err?.message || '请求失败'
      }
    } finally {
      isStreamingReply.value = false
      isLoading.value = false
      stopLoadingProgress()
    }

    if (data.batch && Array.isArray(data.results)) {
      if (data.success) {
        for (const part of data.results) {
          if (part && part.success) {
            if (part?.requires_token) {
              if (!isDatabaseTokenRequirement(part?.token_name, part?.token_description)) {
                handleChatRequiresToken(part?.token_name, part?.token_description, remoteMessages)
              }
            }
            await addAndSaveMessage(part.response, 'ai')
            syncTaskFromChatResponse(part, primaryText)
          } else {
            await addAndSaveMessage('处理失败: ' + (part?.message || '未知错误'), 'ai')
          }
        }
        attachContextSummaryToLastAiMessage()
        const lastOk = [...data.results].reverse().find((p: unknown) => p && p.success)
        if (lastOk) {
          attachThinkingStepsToLastAiMessage(lastOk)
          attachTodoStepsToLastAiMessage(lastOk)
          attachWorkflowTraceToLastAiMessage(lastOk)
        }
        const lastTask = [...data.results].reverse().find((p: unknown) => p?.task)
        if (lastTask?.task) {
          showTaskConfirm(lastTask.task)
          emitAssistantPush({
            title: lastTask.task.title || '新任务',
            description: lastTask.task.description || '收到一条任务，请处理'
          })
        }
        const lastFloat = [...data.results].reverse().find(
          (p: unknown) =>
            p?.autoAction?.type === 'show_products_float' || p?.autoAction?.type === 'show_products'
        )
        if (!lastTask?.task && lastFloat?.autoAction) {
          currentTask.value = null
        }
        const lastAction = [...data.results].reverse().find((p: unknown) => p?.autoAction)
        if (lastAction?.autoAction) {
          handleAutoAction(lastAction.autoAction, remoteMessages[remoteMessages.length - 1] || '')
        }
        if (lastTask?.task) {
          maybeCloseAssistantFloatForShipmentTask(lastTask.task, lastAction?.autoAction)
        }
      } else {
        await addAndSaveMessage('处理失败: ' + (data.message || '批量请求失败'), 'ai')
      }
      return
    }

    if (data.success) {
      if (data?.requires_token) {
        if (!isDatabaseTokenRequirement(data?.token_name, data?.token_description)) {
          handleChatRequiresToken(data?.token_name, data?.token_description, remoteMessages)
        }
      }
      await addAndSaveMessage(data.response, 'ai')
      syncTaskFromChatResponse(data, primaryText)
      attachContextSummaryToLastAiMessage()
      attachThinkingStepsToLastAiMessage(data)
      attachTodoStepsToLastAiMessage(data)
      attachWorkflowTraceToLastAiMessage(data)

      if (data.task) {
        showTaskConfirm(data.task)
        emitAssistantPush({
          title: data.task.title || '新任务',
          description: data.task.description || '收到一条任务，请处理'
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
      await addAndSaveMessage('处理失败: ' + data.message, 'ai')
    }
  }

  async function sendMessage(message: string) {
    await addAndSaveMessage(message, 'user')

    const modeHandled = await tryHandleRuntimeModeCommand(message)
    if (modeHandled) return

    const previewModified = await handleShipmentModify(message)
    if (previewModified) return

    if (
      isProMode.value &&
      typeof (window as unknown).isProTaskAcquisitionMessage === 'function' &&
      (window as unknown).isProTaskAcquisitionMessage(message) &&
      typeof (window as unknown).jarvisSendMessage === 'function'
    ) {
      ;(window as unknown).jarvisSendMessage(message)
      return
    }

    const printHandled = await handleStartPrintCommand(message)
    if (printHandled) return

    const debounceMs = getChatBatchDebounceMs()
    if (debounceMs <= 0) {
      await executeRemoteChatRound([message])
      return
    }
    enqueueChatBatchMessage(message, debounceMs, (msgs) => {
      void executeRemoteChatRound(msgs)
    })
  }
  function handleShipmentDownloadClick() {
    addAndSaveMessage('发货单已开始下载。是否现在执行打印？可点击"开始打印"按钮或直接发送"开始打印"。', 'ai')
  }

  async function startPrintFromTaskCard() {
    await handleStartPrintCommand('开始打印')
  }

  async function copyAssistantPushContent() {
    const title = String(latestAssistantPush.value?.title || '').trim()
    const desc = String(latestAssistantPush.value?.description || '').trim()
    const text = [title, desc].filter(Boolean).join('\n')
    if (!text) return
    try {
      pushCopied.value = true
      window.setTimeout(() => {
        pushCopied.value = false
      }, 1200)
    } catch (_e) {
      pushCopied.value = false
    }
  }

  function openAssistantFloatFromTaskPanel() {
    const detail = latestAssistantPush.value || {}
    window.dispatchEvent(new CustomEvent('xcagi:open-assistant-float', { detail }))
  }

  async function syncSessionMessages(): Promise<void> {
    try {
      await syncFromServer()
    } finally {
      applyPersistedTaskPanelStateForSession(String(sessionId.value || '').trim() || 'default')
    }
  }

  executeRemoteChatRoundRef.fn = executeRemoteChatRound

  registerHistoryModWatch(showHistoryPanel)

  workflowPanel.registerWorkflowPanelWatchers(persistTaskPanelStateForSession, currentTask)

  onMounted(() => {
    const sid = String(sessionId.value || '').trim() || 'default'
    if (!lastExcelAnalysisContext.value) {
      const restored = readPersistedExcelAnalysisContext(sid)
      if (restored) lastExcelAnalysisContext.value = restored
    }
    if (!linkedExcelSheet.value) {
      const first = excelSheetOptions.value[0]
      if (first) linkedExcelSheet.value = first
    }
    window.addEventListener(FHD_DB_WRITE_UNLOCKED_EVENT, dbGate.onDbWriteUnlockedForChatRetry)
    workflowPanel.mountWorkflowPanel()
  })

  onBeforeUnmount(() => {
    window.removeEventListener(FHD_DB_WRITE_UNLOCKED_EVENT, dbGate.onDbWriteUnlockedForChatRetry)
    workflowPanel.unmountWorkflowPanel()
  })

  return {
    messages,
    lastMessage: computed(() => messages.value[messages.value.length - 1] ?? null),
    currentTask,
    orderNumberFetching,
    isLoading,
    isStreamingReply,
    isExecuting,
    latestAssistantPush,
    proRuntimeTask,
    taskList,
    filteredTaskList,
    activeTask,
    activeTaskId,
    expandedTaskIds,
    taskFilter,
    showHistory,
    historySessions,
    historyLoading,
    historyError,
    chatMessagesRef,
    pushCopied,
    loadingProgressText,
    excelAnalyzeUploading,
    excelAnalyzeInputRef,
    multimodalPendingCount,
    excelSheetOptions,
    linkedExcelSheet,
    linkedExcelAllSheets,
    isProMode,
    isPrinting,
    taskTableColumns,
    taskTableItems,
    taskOrderNumber,
    generateSessionId,
    scrollToBottom,
    syncProModeState: dbGate.syncProModeState,
    sendMessage,
    confirmTask,
    refetchTaskOrderNumber,
    setCustomOrderNumber,
    cancelTask,
    showTaskConfirm,
    triggerUpload,
    onExcelAnalyzeFileChange,
    showHistoryPanel,
    loadSession,
    clearHistorySessions,
    newConversation,
    handleShipmentDownloadClick,
    startPrintFromTaskCard,
    copyAssistantPushContent,
    openAssistantFloatFromTaskPanel,
    syncSessionMessages,
    bindExcelSheetToChat,
    bindAllExcelSheetsToChat,
    toggleTaskExpanded,
    setTaskFilter,
    clearTaskHistory,
    cancelTaskById,
    retryTask,
    jumpToTaskMessage,
    handleAutoAction,
    isStartPrintMessage,
    ttsEnabled,
    setTtsEnabled,
  }
}
