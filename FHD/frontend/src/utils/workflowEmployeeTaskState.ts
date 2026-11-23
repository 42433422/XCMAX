import type { AgentTaskSummary } from '@/api/agentRuns'
import type { WorkflowEmployeeSpaceSnapshot } from '@/stores/workflowEmployeeSpace'
import { runHasUncertainReceipt } from '@/utils/agentRunExecution'
import { taskProgressPercent, taskStatusLabel } from '@/utils/taskWorkspacePresentation'
import { asArray, asRecord, asString } from '@/utils/typeGuards'

const RUNNING = new Set(['running', 'claimed', 'retrying'])
const WAITING = new Set(['queued', 'pending', 'accepted', 'waiting_user', 'waiting_approval', 'awaiting_approval', 'paused'])
const ATTENTION = new Set(['failed', 'blocked', 'unknown', 'rejected', 'timed_out'])

export function taskEmployeeAssignments(task: AgentTaskSummary): { employee_id: string; status: string; step_id: string }[] {
  const projected = asArray(task.metadata?.employee_assignments).map(asRecord)
  if (projected.length)
    return projected
      .map((row) => ({ employee_id: asString(row.employee_id), status: asString(row.status), step_id: asString(row.step_id) }))
      .filter((row) => row.employee_id)
  const run = task.active_run || task.runs?.find((item) => item.run_id === task.active_run_id)
  return (run?.steps || [])
    .filter((step) => step.tool_id === 'employee' && (step.params?.employee_id || step.params?.pack_id))
    .map((step) => ({
      employee_id: asString(step.params?.employee_id || step.params?.pack_id),
      status: step.status || 'unknown',
      step_id: step.step_id,
    }))
}

/** Explicit assignments, never task-title or label matching. */
export function taskEmployeeIds(task: AgentTaskSummary): string[] {
  const assignments = taskEmployeeAssignments(task)
  if (assignments.length) return [...new Set(assignments.map((row) => row.employee_id))]
  const metadata = asRecord(task.metadata)
  const ids = asArray(metadata.employee_ids)
    .map((value) => asString(value))
    .filter(Boolean)
  if (ids.length) return [...new Set(ids)]
  const request = asRecord(metadata.task_request)
  const params = request.tool_id === 'employee' ? asRecord(request.params) : {}
  const run = task.active_run || task.runs?.find((item) => item.run_id === task.active_run_id)
  const context = asRecord(asRecord(run?.metadata).runtime_context)
  const id = asString(metadata.employee_id || params.employee_id || params.pack_id || context.employee_id).trim()
  return id ? [id] : []
}

/** A multi-worker task has no single assignee unless exactly one is executing. */
export function employeeIdOfTask(task: AgentTaskSummary): string {
  const active = [
    ...new Set(
      taskEmployeeAssignments(task)
        .filter((row) => RUNNING.has(row.status))
        .map((row) => row.employee_id),
    ),
  ]
  const ids = active.length ? active : taskEmployeeIds(task)
  return ids.length === 1 ? ids[0] : ''
}

export function employeeStatusOfTask(task: AgentTaskSummary, employeeId: string): string {
  const run = task.active_run || task.runs?.find((item) => item.run_id === task.active_run_id)
  if (task.metadata?.reconciliation_required === true || (run && runHasUncertainReceipt(run))) return 'unknown'
  if (['paused', 'cancelled', ...ATTENTION].includes(task.status)) return task.status
  const own = taskEmployeeAssignments(task).filter((row) => row.employee_id === employeeId)
  if (!own.length) return taskEmployeeIds(task).length > 1 ? 'unknown' : task.status
  if (own.some((row) => RUNNING.has(row.status))) return task.status === 'waiting_user' ? 'waiting_user' : 'running'
  for (const status of ['waiting_user', 'failed', 'blocked', 'pending']) if (own.some((row) => row.status === status)) return status
  if (own.every((row) => row.status === 'completed')) return 'completed'
  if (own.every((row) => row.status === 'skipped')) return 'skipped'
  return 'unknown'
}

function priority(status: string): number {
  return RUNNING.has(status) || status === 'planning' ? 0 : WAITING.has(status) ? 1 : ATTENTION.has(status) ? 2 : 3
}

export function tasksForEmployee(tasks: AgentTaskSummary[], employeeId: string): AgentTaskSummary[] {
  return tasks
    .filter((task) => taskEmployeeIds(task).includes(employeeId))
    .sort(
      (left, right) =>
        priority(employeeStatusOfTask(left, employeeId)) - priority(employeeStatusOfTask(right, employeeId)) ||
        (Date.parse(right.updated_at || '') || 0) - (Date.parse(left.updated_at || '') || 0),
    )
}

/** One read-only projection for the office, inspector and department graph. */
export function employeeTaskSnapshot(input: {
  empId: string
  panelTitle: string
  shortName: string
  enabled: boolean
  tasks: AgentTaskSummary[]
  stale: boolean
  lastVerifiedAt: number
}): WorkflowEmployeeSpaceSnapshot {
  const task = input.tasks[0]
  const run = task?.active_run
  const uncertain = task?.metadata?.reconciliation_required === true || (run ? runHasUncertainReceipt(run) : false)
  const status = uncertain ? 'unknown' : task ? employeeStatusOfTask(task, input.empId) : input.enabled ? 'idle' : 'off'
  const officeState = input.stale
    ? 'offline'
    : ATTENTION.has(status)
      ? 'error'
      : RUNNING.has(status)
        ? 'working'
        : status === 'planning'
          ? 'reading'
          : WAITING.has(status)
            ? 'waiting'
            : status === 'completed'
              ? 'done'
              : 'idle'
  const stage = input.stale
    ? '连接中断或状态待核对'
    : uncertain || status === 'unknown'
      ? '执行结果待核对'
      : task
        ? (status === task.status && task.progress?.stage) || taskStatusLabel(status)
        : input.enabled
          ? '待命 · 当前无任务'
          : '未启用 · 当前无任务'
  const own = task && taskEmployeeIds(task).length > 1 ? taskEmployeeAssignments(task).filter((row) => row.employee_id === input.empId) : []
  return {
    empId: input.empId,
    panelTitle: input.panelTitle,
    shortName: input.shortName,
    authority: 'task-center',
    status,
    taskId: task?.task_id,
    runId: task?.active_run_id,
    stage,
    hintLine: task?.title || '',
    progressLabel: stage,
    progressPct: own.length
      ? Math.round((own.filter((row) => row.status === 'completed').length / own.length) * 100)
      : taskProgressPercent(task),
    indeterminate: own.length ? false : (task?.progress?.indeterminate ?? !task?.progress),
    idle: !['working', 'reading'].includes(officeState),
    visuallyBusy: ['working', 'reading'].includes(officeState),
    lastActivityAt: Date.parse(task?.updated_at || '') || input.lastVerifiedAt,
    stale: input.stale,
    officeState,
  }
}
