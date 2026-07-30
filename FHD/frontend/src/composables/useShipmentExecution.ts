import type { Ref } from 'vue'
import { authenticatedRequestInit } from '@/utils/authenticatedRequest'
import { fetchShipmentRecordsForUnit, summarizeShipmentRecordsForAudit } from '@/utils/shipmentMgmtPostPrint'
import { isStartPrintMessage } from '@/utils/textParser'
import { asArray, asRecord, asString } from '@/utils/typeGuards'
import { dispatchCoreWorkflowModRun } from '@/workflow/coreWorkflowDispatcher'
import type { ChatMessageExtras } from './useChatMessages'
import type { TaskItem } from './useChatPersistence'
import type { PrintSummary } from './usePrintService'
import type { ShipmentTask } from './useShipmentTask'

interface ShipmentExecutionState {
  filePath: string
  purchaseUnit: string
  orderId: number | null
  labelPaths: string[]
  printToken?: string
  taskListId?: string
  pendingPrintJobToken?: string
}

type UpsertTask = (
  item: Partial<TaskItem> & Pick<TaskItem, 'id' | 'type' | 'source' | 'title'>
) => void

interface UseShipmentExecutionOptions {
  currentTask: Ref<ShipmentTask | null>
  isExecuting: Ref<boolean>
  lastShipmentExecution: Ref<ShipmentExecutionState | null>
  taskList: Ref<TaskItem[]>
  coreWorkflowInstalled: () => boolean
  addAndSaveMessage: (
    content: string,
    role?: 'user' | 'ai' | 'task',
    extras?: ChatMessageExtras,
  ) => Promise<void>
  createTaskId: (prefix: string) => string
  upsertTask: UpsertTask
  failTask: (id: string, error: string) => void
  getLastAiMessageRef: () => string
  emitAssistantPush: (payload?: unknown) => void
  readWorkflowEmployeeEnabledMap: () => Record<string, boolean>
  upsertShipmentWorkflowEmployeeTask: (
    employeeId: string,
    options: { lastShipmentAudit: { at: number; line: string; detail: string } },
  ) => void
  executePrintTask: (
    labelPaths: string[],
    filePath: string,
    orderId?: number,
    purchaseUnit?: string,
    printToken?: string,
  ) => Promise<PrintSummary>
  buildPrintSummaryMessage: (
    summary: PrintSummary,
    labelCount: number,
    filePath?: string,
    purchaseUnit?: string,
  ) => string
  hydrateTaskOrderNumber: (task: ShipmentTask, options?: { force?: boolean }) => Promise<void>
  handleChatRequiresToken: (
    tokenName: string,
    tokenDescription: string,
    retryMessages: string[],
  ) => void
  handleAutoAction: (action: unknown, userMessage?: string) => void
}

export function buildTaskCompletedDescription(successMsg: string, data: unknown): string {
  const row = asRecord(data)
  const nestedData = asRecord(row.data)
  const document = asRecord(row.document || nestedData.document)
  const parts = [successMsg || '任务执行成功']
  const docName = row.doc_name || nestedData.doc_name || document.filename
  const orderNo = row.order_number || nestedData.order_number || document.order_number
  const filePath = row.file_path || nestedData.file_path || document.filepath
  const labels = asArray(row.labels).length ? asArray(row.labels) : asArray(nestedData.labels)
  if (docName) parts.push(`文档：${docName}`)
  if (orderNo) parts.push(`单号：${orderNo}`)
  if (typeof row.record_id !== 'undefined' && row.record_id !== null) parts.push(`记录ID：${row.record_id}`)
  if (typeof row.order_id !== 'undefined' && row.order_id !== null) parts.push(`订单ID：${row.order_id}`)
  if (labels.length) parts.push(`标签：${labels.length} 张`)
  if (filePath) parts.push(`路径：${filePath}`)
  return parts.join('；')
}

export function buildShipmentDownloadUrl(data: unknown): string {
  const row = asRecord(data)
  const nestedData = asRecord(row.data)
  const document = asRecord(row.document || nestedData.document)
  const directUrl = row.download_url || nestedData.download_url
  if (directUrl && typeof directUrl === 'string') return directUrl
  const docName = row.doc_name || nestedData.doc_name || document.filename
  return docName && typeof docName === 'string'
    ? `/api/shipment/download/${encodeURIComponent(docName)}`
    : ''
}

function normalizeRecordId(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const n = Number(value)
  if (!Number.isFinite(n)) return null
  const normalized = Math.trunc(n)
  return normalized > 0 ? normalized : null
}

export function extractShipmentExecutionContext(data: unknown): ShipmentExecutionState {
  const row = asRecord(data)
  const nestedData = asRecord(row.data)
  const document = asRecord(row.document || nestedData.document)
  const printAuthorization = asRecord(
    row.print_authorization || nestedData.print_authorization || document.print_authorization,
  )
  const filePath = asString(row.file_path || nestedData.file_path || document.filepath)
  const purchaseUnit = String(
    row.purchase_unit ?? nestedData.purchase_unit ?? document.purchase_unit ?? '',
  ).trim()
  const orderId = normalizeRecordId(
    row.order_id
    ?? row.record_id
    ?? nestedData.order_id
    ?? nestedData.record_id
    ?? document.order_id
    ?? document.record_id,
  )
  const labelsRaw = asArray(row.labels).length ? asArray(row.labels) : asArray(nestedData.labels)
  const labelPaths: string[] = []
  labelsRaw.forEach((label: unknown) => {
    if (typeof label === 'string' && label.trim()) {
      labelPaths.push(label.trim())
      return
    }
    const labelRow = asRecord(label)
    const path = labelRow.file_path || labelRow.path || labelRow.filePath || labelRow.filepath || ''
    if (typeof path === 'string' && path.trim()) labelPaths.push(path.trim())
  })
  return {
    filePath,
    purchaseUnit,
    orderId,
    labelPaths: Array.from(new Set(labelPaths)),
    printToken: asString(
      printAuthorization.document_token
      || row.print_token
      || nestedData.print_token
      || document.print_token,
    ),
  }
}

export function useShipmentExecution(options: UseShipmentExecutionOptions) {
  const {
    currentTask,
    isExecuting,
    lastShipmentExecution,
    taskList,
    coreWorkflowInstalled,
    addAndSaveMessage,
    createTaskId,
    upsertTask,
    failTask,
    getLastAiMessageRef,
    emitAssistantPush,
    readWorkflowEmployeeEnabledMap,
    upsertShipmentWorkflowEmployeeTask,
    executePrintTask,
    buildPrintSummaryMessage,
    hydrateTaskOrderNumber,
    handleChatRequiresToken,
    handleAutoAction,
  } = options

  async function runShipmentMgmtAfterPrintSuccess(context: {
    purchaseUnit: string
    orderId: number | null
    filePath: string
    labelCount: number
  }): Promise<void> {
    if (!readWorkflowEmployeeEnabledMap().shipment_mgmt) return
    const unit = String(context.purchaseUnit || '').trim()
    if (!unit) return
    const rows = await fetchShipmentRecordsForUnit(unit)
    const summary = summarizeShipmentRecordsForAudit(rows, unit, context.orderId)
    dispatchCoreWorkflowModRun(coreWorkflowInstalled(), 'shipment_mgmt', {
      action: 'audit_summary',
      purchaseUnit: unit,
      orderId: context.orderId,
      headline: summary.headline,
    })
    const fullText = summary.detailLines.join('\n')
    const at = Date.now()
    await addAndSaveMessage(`【出货管理 · 打印后审计】\n${fullText}`, 'ai')
    const auditMsgRef = getLastAiMessageRef()
    window.dispatchEvent(new CustomEvent('xcagi:shipment-record-updated'))
    if (taskList.value.some((task) => task.id === 'workflow_emp_shipment_mgmt')) {
      upsertShipmentWorkflowEmployeeTask('shipment_mgmt', {
        lastShipmentAudit: { at, line: summary.headline, detail: fullText },
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
        labelCount: context.labelCount,
        filePath: context.filePath,
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
      progress: 20,
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
    const printToken = String(context.printToken || '').trim()
    if (!labelPaths.length && !filePath) {
      await addAndSaveMessage('最近一次任务未包含可打印文件。请重新生成发货单后再试。', 'ai')
      return true
    }
    const summary = await executePrintTask(labelPaths, filePath, orderId ?? undefined, purchaseUnit, printToken)
    const resultText = buildPrintSummaryMessage(summary, labelPaths.length, filePath, purchaseUnit)
    await addAndSaveMessage(resultText, 'ai')
    const hasTrackablePendingJob = Boolean(summary.pending && summary.pendingPrintJobToken)
    upsertTask({
      id: printTaskId,
      type: 'print',
      source: 'print',
      title: '打印任务',
      status: hasTrackablePendingJob ? 'running' : (summary.success ? 'success' : 'failed'),
      progress: 100,
      stage: hasTrackablePendingJob ? '等待打印机完成' : '',
      summary: resultText,
      error: summary.success || hasTrackablePendingJob ? '' : (summary.message || '打印失败'),
      messageRef: getLastAiMessageRef(),
    })
    const shipmentListId = String(context.taskListId || '').trim()
    if (shipmentListId) {
      if (hasTrackablePendingJob) {
        upsertTask({
          id: shipmentListId,
          type: 'shipment',
          source: 'shipment',
          title: '发货单生成任务',
          status: 'running',
          progress: 85,
          stage: '等待打印机完成',
          summary: '发货单已提交到打印队列，正在等待设备完成；未标记已打印。',
        })
      } else if (summary.pending) {
        upsertTask({
          id: shipmentListId,
          type: 'shipment',
          source: 'shipment',
          title: '发货单生成任务',
          status: 'failed',
          stage: '无法确认打印状态',
          error: '打印机已接收任务，但缺少可追踪的 CUPS 作业号；请核验后重新生成发货单。',
          summary: '发货单已提交，但未标记已打印，不能重复提交当前任务。',
        })
      } else if (summary.success) {
        upsertTask({
          id: shipmentListId,
          type: 'shipment',
          source: 'shipment',
          title: '发货单生成任务',
          status: 'success',
          progress: 100,
          stage: '',
          summary: `已生成并打印。${resultText.replace(/\s+/g, ' ').slice(0, 240)}`,
          messageRef: getLastAiMessageRef(),
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
          summary: '发货单文档已生成，打印未成功。可重试「开始打印」。',
        })
      }
    }
    if (summary.pending && currentTask.value?.type === 'shipment_generate') {
      const printJobToken = String(summary.pendingPrintJobToken || '').trim()
      const canTrack = Boolean(printJobToken && summary.printTrackingAvailable !== false)
      lastShipmentExecution.value = {
        ...lastShipmentExecution.value!,
        pendingPrintJobToken: printJobToken || undefined,
      }
      currentTask.value = {
        ...currentTask.value,
        printPending: canTrack,
        printJobToken: printJobToken || undefined,
        printTrackingAvailable: canTrack,
        printTerminal: !canTrack,
        description: `${String(currentTask.value.description || '').trim()}\n${canTrack
          ? '打印任务已提交到 macOS CUPS，等待设备确认完成；可点击“检查打印状态”，在此之前不会标记为已打印。'
          : '打印任务已提交但未取得可追踪的 CUPS 作业号；请核验后重新生成发货单，不能重复提交当前任务。'
        }`.trim(),
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

  async function confirmTask(): Promise<void> {
    if (!currentTask.value || isExecuting.value) return
    const task = currentTask.value
    const apiUrl = task.api_url
    const method = (task.method || 'POST').toUpperCase()
    const payload = { ...(task.payload || {}) }
    if (task.type === 'shipment_generate') {
      if (!String(task.customOrderNumber || '').trim()) await hydrateTaskOrderNumber(task)
      const customOrderNumber = String(task.customOrderNumber || '').trim()
      payload.params = { ...(payload.params || {}) }
      if (customOrderNumber) payload.params.order_number = customOrderNumber
      else if (Object.prototype.hasOwnProperty.call(payload.params, 'order_number')) delete payload.params.order_number
    }
    if (!apiUrl) {
      await addAndSaveMessage('任务执行失败：缺少 API 地址', 'ai')
      currentTask.value = null
      return
    }
    isExecuting.value = true
    let keepTaskCard = false
    let shipmentTaskId = ''
    if (task.type === 'shipment_generate') {
      shipmentTaskId = createTaskId('shipment')
      upsertTask({
        id: shipmentTaskId,
        type: 'shipment',
        source: 'shipment',
        title: '发货单生成任务',
        status: 'running',
        progress: 20,
      })
    }
    try {
      const requestInit = await authenticatedRequestInit(method === 'GET' ? 'GET' : 'POST', {
        ...(method === 'GET' ? {} : { 'Content-Type': 'application/json' }),
      })
      const response = await fetch(apiUrl, {
        method,
        ...requestInit,
        ...(method === 'GET' ? {} : { body: JSON.stringify(payload) }),
      })
      const data = asRecord(await response.json().catch(() => ({})))
      if (data.requires_token) {
        handleChatRequiresToken(
          asString(data.token_name),
          asString(data.token_description || data.message),
          [],
        )
        const tokenMessage = String(
          data.message || data.token_description || '当前操作需要二级数据库写入令牌',
        ).trim()
        await addAndSaveMessage(`[提示] ${tokenMessage}`, 'ai')
        keepTaskCard = true
        currentTask.value = {
          ...task,
          description: `${tokenMessage}（已弹出令牌输入框，输入后请再次点击确认执行）`,
        }
        return
      }
      if (response.ok) {
        const successMessage = String(data.message || data.msg || '任务执行成功')
        const shipmentDocumentUrl = task.type === 'shipment_generate' ? buildShipmentDownloadUrl(data) : ''
        await addAndSaveMessage(`[成功] ${successMessage}`, 'ai', {
          ...(shipmentDocumentUrl ? { shipmentDownloadUrl: shipmentDocumentUrl } : {}),
        })
        if (task.type === 'shipment_generate') {
          lastShipmentExecution.value = {
            ...extractShipmentExecutionContext(data),
            ...(shipmentTaskId ? { taskListId: shipmentTaskId } : {}),
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
              summary: buildTaskCompletedDescription(successMessage, data),
              messageRef: getLastAiMessageRef(),
            })
          }
        }
        currentTask.value = {
          ...task,
          title: `${task.title || '任务'}（已完成）`,
          description: buildTaskCompletedDescription(successMessage, data),
          order_number: asString(data.order_number)
            || asString(asRecord(data.data).order_number)
            || asString(asRecord(data.document).order_number),
          downloadUrl: shipmentDocumentUrl,
          completed: true,
        }
        keepTaskCard = true
        if (task.switch_view) handleAutoAction({ type: task.switch_view })
      } else {
        const message = String(data.message || data.msg || data.error || `执行失败 (HTTP ${response.status})`)
        await addAndSaveMessage(`[失败] 任务执行失败：${message}`, 'ai')
        if (shipmentTaskId) failTask(shipmentTaskId, message)
      }
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : asString(error, '网络错误')
      await addAndSaveMessage(`[失败] 任务执行失败：${message}`, 'ai')
      if (shipmentTaskId) failTask(shipmentTaskId, message)
    } finally {
      isExecuting.value = false
      if (!keepTaskCard) currentTask.value = null
    }
  }

  return { runShipmentMgmtAfterPrintSuccess, handleStartPrintCommand, confirmTask }
}
