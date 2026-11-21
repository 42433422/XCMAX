import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useWorkflowAiEmployeesStore } from '@/stores/workflowAiEmployees'
import {
  useWorkflowEmployeeSpaceStore,
  type WorkflowEmployeeSession,
  type WorkflowEmployeeSpaceSnapshot,
} from '@/stores/workflowEmployeeSpace'
import { shortNameFromPanelTitle } from '@/utils/workflowEmployeeDisplayName'
import { useAgentTaskCenterStore } from '@/stores/agentTaskCenter'
import type { AgentTaskSummary } from '@/api/agentRuns'
import { employeeStatusOfTask, employeeTaskSnapshot, tasksForEmployee } from '@/utils/workflowEmployeeTaskState'

export type WorkflowEmployeeDeskRow = {
  empId: string
  panelTitle: string
  shortName: string
  enabled: boolean
  hostModId?: string
  carrierModId?: string
  enterpriseLayer?: string
  /** 仅提示词、无本地运行时的对话型员工 */
  promptOnly?: boolean
  snapshot?: WorkflowEmployeeSpaceSnapshot
  session?: WorkflowEmployeeSession
  taskId?: string
  tasks?: AgentTaskSummary[]
  /** Completed tasks in the currently visible server list, not a lifetime counter. */
  completedCount?: number
}

export function formatWorkDurationShort(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return '0m'
  const sec = Math.floor(ms / 1000)
  if (sec < 60) return `${sec}s`
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min}m`
  const hr = Math.floor(min / 60)
  const mr = min % 60
  if (hr < 24) return mr > 0 ? `${hr}h ${mr}m` : `${hr}h`
  const day = Math.floor(hr / 24)
  const hrr = hr % 24
  return hrr > 0 ? `${day}d ${hrr}h` : `${day}d`
}

export function totalWorkMs(session: WorkflowEmployeeSession | undefined, nowMs: number): number {
  if (!session) return 0
  const live = session.enabledAt ? Math.max(0, nowMs - session.enabledAt) : 0
  return Math.max(0, session.lifetimeMs) + live
}

export function useNowMsTicker(intervalMs = 30000) {
  const nowMs = ref(Date.now())
  let timer: number | null = null
  onMounted(() => {
    if (typeof window === 'undefined') return
    nowMs.value = Date.now()
    timer = window.setInterval(
      () => {
        nowMs.value = Date.now()
      },
      Math.max(1000, intervalMs),
    )
  })
  onBeforeUnmount(() => {
    if (timer != null) {
      window.clearInterval(timer)
      timer = null
    }
  })
  return nowMs
}

/** 员工与状态：对话型员工没有副窗快照，用上岗状态表达。 */
export function resolveDeskStatusLine(row: WorkflowEmployeeDeskRow): string {
  if (row.snapshot?.authority === 'task-center') return row.snapshot.stage
  if (row.promptOnly) return row.enabled ? '待命' : '待召唤'
  if (!row.enabled) return '副窗未启用'
  const s = row.snapshot
  if (!s) return '暂无快照'
  return s.stage || s.progressLabel || s.hintLine || '待命'
}

export function useWorkflowEmployeeDesks() {
  const wfEmp = useWorkflowAiEmployeesStore()
  const spaceStore = useWorkflowEmployeeSpaceStore()
  const taskCenter = useAgentTaskCenterStore()
  const { enabled: workflowEnabled, registryEntries } = storeToRefs(wfEmp)
  const { sessions } = storeToRefs(spaceStore)
  const syncState = computed(() => ({
    connected: taskCenter.connected,
    stale: taskCenter.stale,
    lastVerifiedAt: taskCenter.lastVerifiedAt,
    error: taskCenter.error,
  }))
  onMounted(() => taskCenter.start())

  const employeeIds = computed(() => registryEntries.value.map((e) => e.id))

  function resolvePanelTitle(empId: string): string {
    const entry = registryEntries.value.find((e) => e.id === empId)
    if (entry) return `工作流 · ${entry.label}`
    return `工作流 · ${empId}`
  }

  const desks = computed<WorkflowEmployeeDeskRow[]>(() => {
    return employeeIds.value.map((empId) => {
      const entry = registryEntries.value.find((e) => e.id === empId)
      const panelTitle = resolvePanelTitle(empId)
      const en = workflowEnabled.value[empId] === true
      const employeeTasks = tasksForEmployee(taskCenter.tasks, empId)
      const snap = employeeTaskSnapshot({
        empId,
        panelTitle,
        shortName: shortNameFromPanelTitle(panelTitle),
        enabled: en,
        tasks: employeeTasks,
        stale: taskCenter.stale,
        lastVerifiedAt: taskCenter.lastVerifiedAt,
      })
      const sess = sessions.value[empId]
      return {
        empId,
        panelTitle,
        shortName: snap?.shortName || shortNameFromPanelTitle(panelTitle),
        enabled: en,
        hostModId: entry?.hostModId,
        carrierModId: entry?.carrierModId,
        enterpriseLayer: entry?.enterprise_layer,
        promptOnly: entry?.prompt_only === true,
        snapshot: snap,
        session: sess,
        taskId: employeeTasks[0]?.task_id,
        tasks: employeeTasks,
        completedCount: employeeTasks.filter((task) => task.status === 'completed' && employeeStatusOfTask(task, empId) === 'completed')
          .length,
      }
    })
  })

  const onDutyDesks = computed<WorkflowEmployeeDeskRow[]>(() => desks.value.filter((d) => d.enabled))

  function statusLine(row: WorkflowEmployeeDeskRow): string {
    return resolveDeskStatusLine(row)
  }

  function ariaLabel(row: WorkflowEmployeeDeskRow): string {
    if (row.snapshot?.authority === 'task-center') return `员工 ${row.shortName}。${statusLine(row)}`
    if (row.promptOnly) return `员工 ${row.shortName}。${row.enabled ? '已上岗，待召唤' : '待召唤'}`
    const state = !row.enabled ? '副窗未启用' : row.snapshot ? statusLine(row) : '等待活动'
    return `员工 ${row.shortName}。${state}`
  }

  function isBusy(row: WorkflowEmployeeDeskRow): boolean {
    if (row.snapshot?.authority === 'task-center') return !row.snapshot.stale && row.snapshot.visuallyBusy
    if (!row.enabled) return false
    const s = row.snapshot
    if (!s) return false
    return s.visuallyBusy === true
  }

  function processedCount(row: WorkflowEmployeeDeskRow): number {
    return row.completedCount ?? 0
  }

  return {
    employeeIds,
    desks,
    onDutyDesks,
    statusLine,
    ariaLabel,
    isBusy,
    processedCount,
    syncState,
    taskCenter,
  }
}
