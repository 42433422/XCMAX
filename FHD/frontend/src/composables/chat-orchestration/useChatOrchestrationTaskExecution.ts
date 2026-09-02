/**
 * useChatOrchestration 拆出的任务确认 / 执行行为（行为零变更）。
 */
import type { Ref } from 'vue'
import type { useCanonicalChatTaskBridge } from '../useCanonicalChatTaskBridge'
import type { useChatDbTokenGate } from '../useChatDbTokenGate'
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
    'invalidateStagedTask' | 'stageCanonicalTask' | 'executeCanonicalTask' | 'cancelCanonicalTask'
  >
  hydrateTaskOrderNumber: ShipmentTaskApi['hydrateTaskOrderNumber']
  enrichShipmentPreviewProducts: ShipmentTaskApi['enrichShipmentPreviewProducts']
  lastShipmentExecution: ShipmentTaskApi['lastShipmentExecution']
  addAndSaveMessage: ChatOrchestrationAddAndSaveMessage
  createTaskId: TaskListApi['createTaskId']
  upsertTask: TaskListApi['upsertTask']
  failTask: TaskListApi['failTask']
  getLastAiMessageRef: ReturnType<typeof useChatResponseAttach>['getLastAiMessageRef']
  handleChatRequiresToken: ReturnType<typeof useChatDbTokenGate>['handleChatRequiresToken']
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
    handleChatRequiresToken,
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

    if (nextTask.completed) return
    if (nextTask.type !== 'shipment_generate') {
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
    const apiUrl = task.api_url
    const method = (task.method || 'POST').toUpperCase()
    const payload = { ...(task.payload || {}) }

    if (task?.type === 'shipment_generate') {
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
        progress: 20,
      })
    }

    try {
      let result
      const canonicalResult = await canonicalTaskBridge.executeCanonicalTask(task, asRecord(payload.params))

      if (canonicalResult) {
        result = canonicalResult
      } else if (method === 'GET') {
        result = await fetch(apiUrl)
      } else {
        result = await fetch(apiUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })
      }

      const data = asRecord(await result.json().catch(() => ({})))

      if (data?.requires_token) {
        handleChatRequiresToken(asString(data.token_name), asString(data.token_description || data.message), [])
        const tokenMsg = String(data.message || data.token_description || '当前操作需要二级数据库写入令牌').trim()
        await addAndSaveMessage('[提示] ' + tokenMsg, 'ai')
        keepTaskCard = true
        currentTask.value = {
          ...task,
          description: `${tokenMsg}（已弹出令牌输入框，输入后请再次点击确认执行）`,
        }
        return
      }

      if (result.ok) {
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
        const errMsg = String(data.message || data.msg || data.error || `执行失败 (HTTP ${result.status})`)
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
