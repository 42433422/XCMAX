/**
 * useChatWorkflowPanel 拆分：工作流面板事件监听与挂载/卸载生命周期。
 */
import { watch, type Ref } from 'vue'
import {
  buildLabelPrintHostUpdate,
  buildReceiptFeedbackHostUpdate,
  buildWechatMonitorUpdate,
  dispatchCoreWorkflowModRun,
  runLabelPrintSideEffect,
} from '@/workflow/coreWorkflowDispatcher'
import { isCoreWorkflowModInstalled } from '@/constants/coreWorkflowMod'
import { workflowAiEmployeesStorageKey } from '@/stores/workflowAiEmployees'
import type { useModsStore } from '@/stores/mods'
import type { useWorkflowAiEmployeesStore } from '@/stores/workflowAiEmployees'
import type { TaskFilter, TaskItem } from '../useChatPersistence'
import type { ShipmentTask } from '../useShipmentTask'
import type { WorkflowEmployeeTaskUpdate } from './useWorkflowPanelTasks'

export interface WorkflowPanelEventsDeps {
  taskList: Ref<TaskItem[]>
  activeTaskId: Ref<string>
  expandedTaskIds: Ref<string[]>
  taskFilter: Ref<TaskFilter>
  upsertTask: (item: Partial<TaskItem> & Pick<TaskItem, 'id' | 'type' | 'source' | 'title' | 'status'>) => void
  createTaskId: (prefix: string) => string
  showTaskConfirm: (task: ShipmentTask | null | undefined) => void
  emitAssistantPush: (payload?: Record<string, unknown>) => void
  maybeCloseAssistantFloatForShipmentTask: (task: ShipmentTask | null | undefined, autoAction: Record<string, unknown> | null | undefined) => void
  modsStore: ReturnType<typeof useModsStore>
  workflowAiEmployeesStore: ReturnType<typeof useWorkflowAiEmployeesStore>
  readWorkflowEmployeeEnabledMap: () => Record<string, boolean>
  upsertWorkflowEmployeeTask: (empId: string, opts?: WorkflowEmployeeTaskUpdate) => void
  syncWorkflowEmployeePanelTasks: (enabled: Record<string, boolean>) => void
  resyncEnabledWorkflowEmployeeTasks: () => void
  stopPhoneAgentStatusPoll: () => void
}

export function useWorkflowPanelEvents(deps: WorkflowPanelEventsDeps) {
  const {
    taskList,
    activeTaskId,
    expandedTaskIds,
    taskFilter,
    upsertTask,
    createTaskId,
    showTaskConfirm,
    emitAssistantPush,
    maybeCloseAssistantFloatForShipmentTask,
    modsStore,
    workflowAiEmployeesStore,
    readWorkflowEmployeeEnabledMap,
    upsertWorkflowEmployeeTask,
    syncWorkflowEmployeePanelTasks,
    resyncEnabledWorkflowEmployeeTasks,
    stopPhoneAgentStatusPoll,
  } = deps

  /** 副窗星标轮询 + 微信 AI 员工链路：写入右侧任务列表（仅 API/事件，不模拟点击） */
  function onWechatAiTaskEnqueue(evt: Event) {
    const d = (evt as CustomEvent).detail || {}
    const msg = String(d.messageText || '').trim()
    const contactId = String(d.contactId ?? '').trim()
    if (!msg && !contactId) return
    const taskId = createTaskId('wechat_ai')
    const name = String(d.contactName || '星标联系人').trim()
    const title = `微信消息处理 · ${name}`
    const lines: string[] = []
    if (msg) lines.push(`最新消息：${msg}`)
    lines.push(`预处理意图：${String(d.intentLabel || '—').trim()}`)
    const idetail = String(d.intentDetail || '').trim()
    if (idetail) lines.push(idetail)
    const pi = String(d.primaryIntent || '').trim()
    if (pi) lines.push(`primary_intent：${pi}`)
    const toolKey = String(d.toolKey || '').trim()
    if (toolKey) lines.push(`tool_key：${toolKey}`)
    upsertTask({
      id: taskId,
      type: 'wechat_intent',
      source: 'wechat',
      title,
      status: 'success',
      progress: 100,
      stage: d.sourceApi === 'intent_test' ? '专业模式·意图 API' : '本地规则预处理',
      summary: lines.join('\n'),
      payload: { ...d },
    })

    const wf = taskList.value.find((t) => t.id === 'workflow_emp_wechat_msg')
    if (wf) {
      const line = `${name}：${msg.replace(/\s+/g, ' ').slice(0, 120)}`
      dispatchCoreWorkflowModRun(isCoreWorkflowModInstalled(modsStore.modsForUi), 'wechat_msg', {
        action: 'enqueue_ack',
        contact: name,
        line,
      })
      upsertWorkflowEmployeeTask('wechat_msg', {
        lastWechat: {
          at: Date.now(),
          line,
        },
      })
    }
  }

  /** 微信星标链路解析出可开单话术时，右侧「当前任务」展示与对话内一致的发货单预览 */
  function onWechatShipmentPreviewTask(evt: Event) {
    const d = (evt as CustomEvent).detail || {}
    const task = d.task
    if (!task || task.type !== 'shipment_generate') return
    const contact = String(d.contactName || '').trim()
    const hint = '\n\n可在左侧对话发送「再加 / 删除第几行 / 改成…」调整明细后再点确认执行。（与智能对话内改预览一致）'
    const baseDesc = String(task.description || '').trim()
    const next = {
      ...task,
      title: contact ? `${task.title}（微信 · ${contact}）` : `${task.title}（微信消息）`,
      description: `${baseDesc}${hint}`,
      payload: {
        ...(task.payload || {}),
        wechat_preview_source: {
          contactName: d.contactName,
          contactId: d.contactId,
          messageText: d.messageText,
        },
      },
    }
    showTaskConfirm(next)
    maybeCloseAssistantFloatForShipmentTask(next, null)
    emitAssistantPush({
      title: '微信发货单预览',
      description: contact ? `来自 ${contact}，请在右侧任务面板确认或先对话改明细` : '请在右侧任务面板确认或先对话改明细',
    })
  }

  async function onWorkflowLabelPrintSignal(evt: Event) {
    const d = (evt as CustomEvent).detail || {}
    const enabled = readWorkflowEmployeeEnabledMap()
    if (!enabled.label_print) return
    if (!taskList.value.some((t) => t.id === 'workflow_emp_label_print')) return
    const modInstalled = isCoreWorkflowModInstalled(modsStore.modsForUi)
    dispatchCoreWorkflowModRun(modInstalled, 'label_print', { action: 'signal_ack', ...d })
    upsertWorkflowEmployeeTask('label_print', buildLabelPrintHostUpdate(d))
    await runLabelPrintSideEffect(d)
  }

  /** 星标微信命中收货/对账类意图时，写入收货确认工作流 */
  function onWorkflowReceiptFeedbackSignal(evt: Event) {
    const d = (evt as CustomEvent).detail || {}
    const enabled = readWorkflowEmployeeEnabledMap()
    if (!enabled.receipt_confirm) return
    if (!taskList.value.some((t) => t.id === 'workflow_emp_receipt_confirm')) return
    const modInstalled = isCoreWorkflowModInstalled(modsStore.modsForUi)
    const host = buildReceiptFeedbackHostUpdate(d)
    dispatchCoreWorkflowModRun(modInstalled, 'receipt_confirm', {
      action: 'feedback_ack',
      line: host.lastReceiptFeedback.line,
      detail: host.lastReceiptFeedback.detail,
    })
    upsertWorkflowEmployeeTask('receipt_confirm', {
      lastReceiptFeedback: host.lastReceiptFeedback,
    })
    emitAssistantPush({
      title: host.pushTitle,
      description: host.pushDescription,
      feature: 'assistant',
    })
  }

  function onWechatStarFeedPolled(evt: Event) {
    const d = (evt as CustomEvent).detail || {}
    const enabled = readWorkflowEmployeeEnabledMap()
    if (!enabled.wechat_msg) return
    if (!taskList.value.some((t) => t.id === 'workflow_emp_wechat_msg')) return
    upsertWorkflowEmployeeTask('wechat_msg', buildWechatMonitorUpdate(d))
  }

  /**
   * 兜底同步：避免仅靠自定义事件导致偶发漏同步（例如页面切换后返回聊天页）。
   * 只要本地存在已启用员工，就从 storage 重建任务面板常驻项。
   */
  function ensureWorkflowEmployeePanelTasksFromStorage() {
    const enabled = readWorkflowEmployeeEnabledMap()
    if (!Object.values(enabled).some(Boolean)) return
    syncWorkflowEmployeePanelTasks(enabled)
  }

  function onWorkflowAiEmployeesChanged(evt: Event) {
    const d = (evt as CustomEvent).detail || {}
    const en = d.enabled
    if (en && typeof en === 'object') {
      syncWorkflowEmployeePanelTasks(en as Record<string, boolean>)
      return
    }
    syncWorkflowEmployeePanelTasks(readWorkflowEmployeeEnabledMap())
  }

  function onWorkflowEmployeesStorage(e: StorageEvent) {
    if (e.key !== workflowAiEmployeesStorageKey()) return
    workflowAiEmployeesStore.reloadFromLocalStorage()
    syncWorkflowEmployeePanelTasks(readWorkflowEmployeeEnabledMap())
  }

  function onStarRefreshOrIntentChangedForWorkflow() {
    resyncEnabledWorkflowEmployeeTasks()
  }

  function onWindowFocusForWorkflowTasks() {
    ensureWorkflowEmployeePanelTasksFromStorage()
  }

  function onVisibilityChangeForWorkflowTasks() {
    if (document.visibilityState === 'visible') {
      ensureWorkflowEmployeePanelTasksFromStorage()
    }
  }

  function registerWorkflowPanelWatchers(
    persistTaskPanelStateForSession: (targetSessionId?: string) => void,
    currentTask: { value: ShipmentTask | null },
  ) {
    watch(
      [taskList, activeTaskId, expandedTaskIds, taskFilter, currentTask],
      () => {
        persistTaskPanelStateForSession()
      },
      { deep: true },
    )

    watch(
      () => modsStore.modsForWorkflowUi,
      (mods) => {
        workflowAiEmployeesStore.hydrateFromMods(mods)
        workflowAiEmployeesStore.pruneOrphanWorkflowEmployeeToggles(mods)
        syncWorkflowEmployeePanelTasks(readWorkflowEmployeeEnabledMap())
      },
      { deep: true },
    )

    watch(
      () => workflowAiEmployeesStore.enabled,
      () => {
        syncWorkflowEmployeePanelTasks(readWorkflowEmployeeEnabledMap())
      },
      { deep: true },
    )
  }

  function mountWorkflowPanel() {
    window.addEventListener('xcagi:wechat-ai-task-enqueue', onWechatAiTaskEnqueue)
    window.addEventListener('xcagi:wechat-shipment-preview-task', onWechatShipmentPreviewTask)
    window.addEventListener('xcagi:workflow-label-print-signal', onWorkflowLabelPrintSignal)
    window.addEventListener('xcagi:workflow-receipt-feedback-signal', onWorkflowReceiptFeedbackSignal)
    window.addEventListener('xcagi:workflow-ai-employees-changed', onWorkflowAiEmployeesChanged)
    window.addEventListener('storage', onWorkflowEmployeesStorage)
    window.addEventListener('xcagi:auto-refresh-wechat-changed', onStarRefreshOrIntentChangedForWorkflow)
    window.addEventListener('xcagi:wechat-star-feed-polled', onWechatStarFeedPolled)
    window.addEventListener('focus', onWindowFocusForWorkflowTasks)
    document.addEventListener('visibilitychange', onVisibilityChangeForWorkflowTasks)
    syncWorkflowEmployeePanelTasks(readWorkflowEmployeeEnabledMap())
    window.setTimeout(() => ensureWorkflowEmployeePanelTasksFromStorage(), 120)
  }

  function unmountWorkflowPanel() {
    window.removeEventListener('xcagi:wechat-ai-task-enqueue', onWechatAiTaskEnqueue)
    window.removeEventListener('xcagi:wechat-shipment-preview-task', onWechatShipmentPreviewTask)
    window.removeEventListener('xcagi:workflow-label-print-signal', onWorkflowLabelPrintSignal)
    window.removeEventListener('xcagi:workflow-receipt-feedback-signal', onWorkflowReceiptFeedbackSignal)
    window.removeEventListener('xcagi:workflow-ai-employees-changed', onWorkflowAiEmployeesChanged)
    window.removeEventListener('storage', onWorkflowEmployeesStorage)
    window.removeEventListener('xcagi:auto-refresh-wechat-changed', onStarRefreshOrIntentChangedForWorkflow)
    window.removeEventListener('xcagi:wechat-star-feed-polled', onWechatStarFeedPolled)
    window.removeEventListener('focus', onWindowFocusForWorkflowTasks)
    document.removeEventListener('visibilitychange', onVisibilityChangeForWorkflowTasks)
    stopPhoneAgentStatusPoll()
  }

  return {
    onWechatAiTaskEnqueue,
    mountWorkflowPanel,
    unmountWorkflowPanel,
    registerWorkflowPanelWatchers,
  }
}
