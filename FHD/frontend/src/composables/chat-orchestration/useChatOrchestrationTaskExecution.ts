/**
 * useChatOrchestration 拆出的任务确认 / 执行行为（行为零变更）。
 */
import type { Ref } from 'vue'
import type { useCanonicalChatTaskBridge } from '../useCanonicalChatTaskBridge'
import type { useChatResponseAttach } from '../useChatResponseAttach'
import type { useChatTaskList } from '../useChatTaskList'
import type { useShipmentTask } from '../useShipmentTask'
import type { ShipmentTask } from '../useShipmentTask'
import { asRecord, asString } from '@/utils/typeGuards'
import {
  buildShipmentDownloadUrl,
  buildTaskCompletedDescription,
  errorMessage,
  extractShipmentExecutionContext,
  asShipmentTask,
  plannerExecutionState,
  type ChatOrchestrationAddAndSaveMessage,
} from './chatOrchestrationShared'

type TaskListApi = ReturnType<typeof useChatTaskList>
type ShipmentTaskApi = ReturnType<typeof useShipmentTask>

export interface ChatOrchestrationTaskExecutionDeps {
  currentTask: Ref<ShipmentTask | null>
  isExecuting: Ref<boolean>
  orderNumberFetching: Ref<boolean>
  canonicalTaskBridge: Pick<
    ReturnType<typeof useCanonicalChatTaskBridge>,
    'hasCanonicalTarget' | 'invalidateStagedTask' | 'stageCanonicalTask' | 'executeCanonicalTask' | 'cancelCanonicalTask'
  >
  hydrateTaskOrderNumber: ShipmentTaskApi['hydrateTaskOrderNumber']
  enrichShipmentPreviewProducts: ShipmentTaskApi['enrichShipmentPreviewProducts']
  lastShipmentExecution: ShipmentTaskApi['lastShipmentExecution']
  addAndSaveMessage: ChatOrchestrationAddAndSaveMessage
  createTaskId: TaskListApi['createTaskId']
  upsertTask: TaskListApi['upsertTask']
  failTask: TaskListApi['failTask']
  getLastAiMessageRef: ReturnType<typeof useChatResponseAttach>['getLastAiMessageRef']
  persistTaskPanelStateForSession: (targetSessionId?: string) => void
  handleAutoAction: (action: unknown, userMessage?: string) => void
}

export function useChatOrchestrationTaskExecution(deps: ChatOrchestrationTaskExecutionDeps) {
  const {
    currentTask,
    isExecuting,
    orderNumberFetching,
    canonicalTaskBridge,
    hydrateTaskOrderNumber,
    enrichShipmentPreviewProducts,
    lastShipmentExecution,
    addAndSaveMessage,
    createTaskId,
    upsertTask,
    failTask,
    getLastAiMessageRef,
    persistTaskPanelStateForSession,
    handleAutoAction,
  } = deps

  async function refetchTaskOrderNumber() {
    const t = currentTask.value
    if (!t || t.type !== 'shipment_generate' || t.completed) return
    orderNumberFetching.value = true
    try {
      await hydrateTaskOrderNumber(t, { force: true })
    } finally {
      orderNumberFetching.value = false
    }
  }

  function setCustomOrderNumber(value: string) {
    const t = currentTask.value
    if (!t) return
    canonicalTaskBridge.invalidateStagedTask(t, value)
    t.customOrderNumber = value
  }

  function showTaskConfirm(task: unknown) {
    const nextTask = asShipmentTask(task)
    currentTask.value = nextTask

    if (nextTask.completed || asRecord(nextTask).requires_token || nextTask.data?.requires_token
      || !canonicalTaskBridge.hasCanonicalTarget(nextTask)) return
    if (nextTask.type !== 'shipment_generate' || asRecord(nextTask).agentRunId) {
      void canonicalTaskBridge.stageCanonicalTask(nextTask).catch(() => {
        /* execution stays blocked */
      })
      return
    }

    const existingOrderNo = String(
      nextTask.customOrderNumber || nextTask.order_number || nextTask.data?.order_number || nextTask.document?.order_number || '',
    ).trim()

    if (existingOrderNo) {
      nextTask.customOrderNumber = existingOrderNo
      void canonicalTaskBridge.stageCanonicalTask(nextTask).catch(() => {
        /* execution stays blocked */
      })
      return
    }

    nextTask.customOrderNumber = ''
    Promise.allSettled([hydrateTaskOrderNumber(nextTask), enrichShipmentPreviewProducts(nextTask)]).then(() => {
      if (currentTask.value === nextTask) {
        void canonicalTaskBridge.stageCanonicalTask(nextTask).catch(() => {
          /* execution stays blocked */
        })
      }
    })
  }

  async function confirmTask(): Promise<void> {
    if (!currentTask.value || isExecuting.value) return

    const task = currentTask.value
    const waitingAuthorization = Boolean(asRecord(task).requires_token || task.data?.requires_token)
    if (waitingAuthorization && !String(asRecord(task).agentRunId || '').trim()) {
      const state = plannerExecutionState(task)
      const message = state === 'unknown' ? '原任务结果待核对，请在任务工作区核对；未重复提交。'
        : '原任务仍在等待授权，请在任务工作区处理；未重复提交。'
      await addAndSaveMessage('[任务] ' + message, 'ai', { workflowAction: state })
      return
    }
    if (!canonicalTaskBridge.hasCanonicalTarget(task)) {
      const message = '任务未开始：缺少有效能力契约，请重新选择可用能力。'
      currentTask.value = { ...task, completed: false, description: message, data: { ...task.data, execution_state: 'not_started' } }
      await addAndSaveMessage('[任务] ' + message, 'ai', { workflowAction: 'not_started' })
      return
    }
    const payload = { ...(task.payload || {}) }

    if (task?.type === 'shipment_generate' && !asRecord(task).agentRunId) {
      if (!String(task?.customOrderNumber || '').trim()) {
        await hydrateTaskOrderNumber(task)
      }
      const customOrderNumber = String(task?.customOrderNumber || '').trim()
      payload.params = { ...(payload.params || {}) }
      if (customOrderNumber) {
        payload.params.order_number = customOrderNumber
      } else if (Object.prototype.hasOwnProperty.call(payload.params, 'order_number')) {
        delete payload.params.order_number
      }
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
        progress: 20,
      })
    }

    try {
      const canonicalResult = await canonicalTaskBridge.executeCanonicalTask(task, asRecord(payload.params))
      if (!canonicalResult) {
        const message = '任务未开始：缺少有效能力契约，请重新选择可用能力。'
        currentTask.value = { ...task, completed: false, description: message, data: { ...task.data, execution_state: 'not_started' } }
        await addAndSaveMessage('[任务] ' + message, 'ai', { workflowAction: 'not_started' })
        keepTaskCard = true
        return
      }

      const data = asRecord(await canonicalResult.json().catch(() => ({})))

      const executionState = String(data.execution_state || '')
      if (!['completed', 'failed', 'cancelled', 'interrupted', 'rejected'].includes(executionState)) {
        const message = String(data.message || '任务结果待核对，请查看原任务进度。')
        await addAndSaveMessage('[任务] ' + message, 'ai')
        keepTaskCard = true
        currentTask.value = { ...task, completed: false, description: message }
        if (shipmentTaskId) upsertTask({
          id: shipmentTaskId, type: 'shipment', source: 'shipment', title: '发货单生成任务',
          status: ['queued', 'accepted'].includes(executionState) ? 'queued'
            : ['planning', 'running', 'retrying'].includes(executionState) ? 'running'
              : executionState === 'paused' ? 'paused' : 'blocked',
          stage: message, payload: { activeRunId: data.run_id, taskId: data.task_id, rawRunStatus: executionState },
        })
        return
      }

      if (data?.requires_token) {
        const state = plannerExecutionState(data)
        const message = state === 'unknown' ? '原任务结果待核对，请在任务工作区核对。'
          : String(data.message || data.token_description || '原任务正在等待授权，请在任务工作区处理。').trim()
        await addAndSaveMessage('[任务] ' + message, 'ai', { workflowAction: state })
        keepTaskCard = true
        currentTask.value = {
          ...task,
          completed: false,
          data: { ...task.data, requires_token: true, execution_state: state },
          description: `${message}（未重新执行）`,
        }
        return
      }

      if (canonicalResult.ok) {
        const successMsg = String(data.message || data.msg || '任务执行成功')
        const shipmentDocUrl = task?.type === 'shipment_generate' ? buildShipmentDownloadUrl(data) : ''
        await addAndSaveMessage('[成功] ' + successMsg, 'ai', {
          ...(shipmentDocUrl ? { shipmentDownloadUrl: shipmentDocUrl } : {}),
        })
        if (task?.type === 'shipment_generate') {
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
              summary: buildTaskCompletedDescription(successMsg, data),
              messageRef: getLastAiMessageRef(),
            })
          }
        }
        currentTask.value = {
          ...task,
          title: `${task.title || '任务'}（已完成）`,
          description: buildTaskCompletedDescription(successMsg, data),
          order_number:
            asString(data.order_number) || asString(asRecord(data.data).order_number) || asString(asRecord(data.document).order_number),
          downloadUrl: task?.type === 'shipment_generate' ? buildShipmentDownloadUrl(data) : '',
          completed: true,
        }
        keepTaskCard = true

        if (task.switch_view) {
          handleAutoAction({ type: task.switch_view })
        }
      } else {
        const errMsg = String(data.message || data.msg || data.error || `执行失败 (HTTP ${canonicalResult.status})`)
        await addAndSaveMessage('[失败] 任务执行失败：' + errMsg, 'ai')
        if (shipmentTaskId) {
          failTask(shipmentTaskId, errMsg)
        }
      }
    } catch (e: unknown) {
      const msg = errorMessage(e, '网络错误')
      await addAndSaveMessage('[失败] 任务执行失败：' + msg, 'ai')
      if (shipmentTaskId) {
        failTask(shipmentTaskId, msg)
      }
    } finally {
      isExecuting.value = false
      if (!keepTaskCard) {
        currentTask.value = null
      }
    }
  }

  function cancelTask() {
    canonicalTaskBridge.cancelCanonicalTask(currentTask.value)
    currentTask.value = null
    persistTaskPanelStateForSession()
  }

  return {
    showTaskConfirm,
    setCustomOrderNumber,
    refetchTaskOrderNumber,
    confirmTask,
    cancelTask,
  }
}
