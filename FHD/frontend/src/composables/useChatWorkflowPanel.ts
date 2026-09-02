/**
 * Facade：工作流任务面板装配入口（实现拆分至 chatWorkflowPanel/ 子模块，行为与拆分前一致）。
 */
import type { Ref } from 'vue'
import { useModsStore } from '@/stores/mods'
import { useWorkflowAiEmployeesStore } from '@/stores/workflowAiEmployees'
import type { TaskFilter, TaskItem } from './useChatPersistence'
import type { ShipmentTask } from './useShipmentTask'
import type { WorkflowEmployeeTaskUpdate } from './chatWorkflowPanel/useWorkflowPanelTasks'
import { useWorkflowPanelDisplay } from './chatWorkflowPanel/useWorkflowPanelDisplay'
import { usePhoneAgentPolling } from './chatWorkflowPanel/usePhoneAgentPolling'
import { useWorkflowPanelTasks } from './chatWorkflowPanel/useWorkflowPanelTasks'
import { useWorkflowPanelEvents } from './chatWorkflowPanel/useWorkflowPanelEvents'

export type { PhoneAgentStatusPayload } from './chatWorkflowPanel/phoneAgentStatus'

export interface UseChatWorkflowPanelDeps {
  taskList: Ref<TaskItem[]>
  activeTaskId: Ref<string>
  expandedTaskIds: Ref<string[]>
  taskFilter: Ref<TaskFilter>
  currentTask: Ref<ShipmentTask | null>
  upsertTask: (item: Partial<TaskItem> & Pick<TaskItem, 'id' | 'type' | 'source' | 'title' | 'status'>) => void
  sortTaskList: () => void
  createTaskId: (prefix: string) => string
  persistTaskPanelStateForSession: (targetSessionId?: string) => void
  showTaskConfirm: (task: ShipmentTask | null | undefined) => void
  emitAssistantPush: (payload?: Record<string, unknown>) => void
  maybeCloseAssistantFloatForShipmentTask: (
    task: ShipmentTask | null | undefined,
    autoAction: Record<string, unknown> | null | undefined,
  ) => void
}

export function useChatWorkflowPanel(deps: UseChatWorkflowPanelDeps) {
  const modsStore = useModsStore()
  const workflowAiEmployeesStore = useWorkflowAiEmployeesStore()
  const { taskList, activeTaskId, expandedTaskIds, taskFilter, upsertTask, sortTaskList } = deps

  /** 与副窗「一键托管」员工开关一致：启用后在任务面板展示工作流状态 */
  function readWorkflowEmployeeEnabledMap(): Record<string, boolean> {
    return { ...workflowAiEmployeesStore.enabled }
  }

  const display = useWorkflowPanelDisplay({
    getModsForUi: () => modsStore.modsForUi,
  })

  // polling ↔ tasks 互调通过惰性回填解耦（回填在装配内同步完成，调用时序与拆分前一致）
  let resolveWorkflowEmployeePanelMetaHook: ((empId: string) => { title: string; summary: string } | null) | null = null
  let upsertWorkflowEmployeeTaskHook: ((empId: string, opts?: WorkflowEmployeeTaskUpdate) => void) | null = null

  const phonePolling = usePhoneAgentPolling({
    getModsForUi: () => modsStore.modsForUi,
    readWorkflowEmployeeEnabledMap,
    resolveWorkflowEmployeePanelMeta: (empId) => resolveWorkflowEmployeePanelMetaHook?.(empId) ?? null,
    onStatusUpdate: (empId, ps) => upsertWorkflowEmployeeTaskHook?.(empId, { phoneStatus: ps }),
    resolvePhoneChannelByEmployee: display.resolvePhoneChannelByEmployee,
    getPhoneAgentApiBase: display.getPhoneAgentApiBase,
  })

  const tasks = useWorkflowPanelTasks({
    taskList,
    activeTaskId,
    upsertTask,
    sortTaskList,
    getModsForUi: () => modsStore.modsForUi,
    readWorkflowEmployeeEnabledMap,
    display,
    phonePolling,
  })
  resolveWorkflowEmployeePanelMetaHook = tasks.resolveWorkflowEmployeePanelMeta
  upsertWorkflowEmployeeTaskHook = tasks.upsertWorkflowEmployeeTask

  const events = useWorkflowPanelEvents({
    taskList,
    activeTaskId,
    expandedTaskIds,
    taskFilter,
    upsertTask,
    createTaskId: deps.createTaskId,
    showTaskConfirm: deps.showTaskConfirm,
    emitAssistantPush: deps.emitAssistantPush,
    maybeCloseAssistantFloatForShipmentTask: deps.maybeCloseAssistantFloatForShipmentTask,
    modsStore,
    workflowAiEmployeesStore,
    readWorkflowEmployeeEnabledMap,
    upsertWorkflowEmployeeTask: tasks.upsertWorkflowEmployeeTask,
    syncWorkflowEmployeePanelTasks: tasks.syncWorkflowEmployeePanelTasks,
    resyncEnabledWorkflowEmployeeTasks: tasks.resyncEnabledWorkflowEmployeeTasks,
    stopPhoneAgentStatusPoll: phonePolling.stopPhoneAgentStatusPoll,
  })

  return {
    onWechatAiTaskEnqueue: events.onWechatAiTaskEnqueue,
    readWorkflowEmployeeEnabledMap,
    upsertWorkflowEmployeeTask: tasks.upsertWorkflowEmployeeTask,
    syncWorkflowEmployeePanelTasks: tasks.syncWorkflowEmployeePanelTasks,
    mountWorkflowPanel: events.mountWorkflowPanel,
    unmountWorkflowPanel: events.unmountWorkflowPanel,
    registerWorkflowPanelWatchers: events.registerWorkflowPanelWatchers,
  }
}
