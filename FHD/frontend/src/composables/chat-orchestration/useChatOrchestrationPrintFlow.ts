/**
 * useChatOrchestration 拆出的打印链路行为（行为零变更）。
 */
import type { useChatResponseAttach } from '../useChatResponseAttach'
import type { useChatTaskList } from '../useChatTaskList'
import type { useChatWorkflowPanel } from '../useChatWorkflowPanel'
import type { useModsStore } from '@/stores/mods'
import type { usePrintService } from '../usePrintService'
import type { useShipmentTask } from '../useShipmentTask'
import { isStartPrintMessage } from '@/utils/textParser'
import { fetchShipmentRecordsForUnit, summarizeShipmentRecordsForAudit } from '@/utils/shipmentMgmtPostPrint'
import { isCoreWorkflowModInstalled } from '@/constants/coreWorkflowMod'
import { dispatchCoreWorkflowModRun } from '@/workflow/coreWorkflowDispatcher'
import type { ChatOrchestrationAddAndSaveMessage } from './chatOrchestrationShared'

type TaskListApi = ReturnType<typeof useChatTaskList>
type ShipmentTaskApi = ReturnType<typeof useShipmentTask>

export interface ChatOrchestrationPrintFlowDeps {
  modsStore: ReturnType<typeof useModsStore>
  addAndSaveMessage: ChatOrchestrationAddAndSaveMessage
  taskList: TaskListApi['taskList']
  createTaskId: TaskListApi['createTaskId']
  upsertTask: TaskListApi['upsertTask']
  getLastAiMessageRef: ReturnType<typeof useChatResponseAttach>['getLastAiMessageRef']
  emitAssistantPush: (payload?: unknown) => void
  readWorkflowEmployeeEnabledMap: ReturnType<typeof useChatWorkflowPanel>['readWorkflowEmployeeEnabledMap']
  upsertWorkflowEmployeeTask: ReturnType<typeof useChatWorkflowPanel>['upsertWorkflowEmployeeTask']
  lastShipmentExecution: ShipmentTaskApi['lastShipmentExecution']
  executePrintTask: ReturnType<typeof usePrintService>['executePrintTask']
  buildPrintSummaryMessage: ReturnType<typeof usePrintService>['buildPrintSummaryMessage']
}

export function useChatOrchestrationPrintFlow(deps: ChatOrchestrationPrintFlowDeps) {
  const {
    modsStore,
    addAndSaveMessage,
    taskList,
    createTaskId,
    upsertTask,
    getLastAiMessageRef,
    emitAssistantPush,
    readWorkflowEmployeeEnabledMap,
    upsertWorkflowEmployeeTask,
    lastShipmentExecution,
    executePrintTask,
    buildPrintSummaryMessage,
  } = deps

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
      error: summary.success ? '' : summary.message || '打印失败',
      messageRef: getLastAiMessageRef(),
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

  function handleShipmentDownloadClick() {
    addAndSaveMessage('发货单已开始下载。是否现在执行打印？可点击"开始打印"按钮或直接发送"开始打印"。', 'ai')
  }

  async function startPrintFromTaskCard() {
    await handleStartPrintCommand('开始打印')
  }

  return {
    runShipmentMgmtAfterPrintSuccess,
    handleStartPrintCommand,
    handleShipmentDownloadClick,
    startPrintFromTaskCard,
  }
}
