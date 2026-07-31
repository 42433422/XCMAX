import type { TaskItem } from '@/composables/useChatPersistence'
import type { OrchestrationTraceStep } from '@/types/orchestration'

export type WorkflowTaskPayload = {
  workflowProgressPct?: number
  workflowMonitorLine?: string
  workflowCurrentHint?: string
  workflowProgressStarted?: boolean
  workflowProgressLabel?: string
  workflowSteps?: Array<{ id: string; label: string; status: string }>
}

export function workflowPayload(task: TaskItem): WorkflowTaskPayload {
  return (task.payload ?? {}) as WorkflowTaskPayload
}

export function hasWorkflowBody(task: TaskItem): boolean {
  const payload = workflowPayload(task)
  return (
    payload.workflowProgressPct != null
    || !!payload.workflowMonitorLine
    || !!payload.workflowCurrentHint
    || (Array.isArray(payload.workflowSteps) && payload.workflowSteps.length > 0)
  )
}

export function agentRunEvidenceSummary(task: TaskItem): string {
  const trace = Array.isArray(task.payload?.orchestrationTrace)
    ? task.payload.orchestrationTrace as OrchestrationTraceStep[]
    : []
  if (!trace.length) return ''
  const databases = new Set<string>()
  let employees = 0
  let prints = 0
  const changes = { created: 0, updated: 0, deleted: 0 }
  for (const step of trace) {
    for (const database of step.evidence?.databases || []) {
      const name = String(database.runtime_database || database.database_id || '').trim()
      if (name) databases.add(name)
    }
    employees += step.evidence?.employees?.length || 0
    if (step.evidence?.kind === 'print') prints += 1
    for (const change of step.evidence?.changes || []) {
      changes.created += Number(change.counts?.created || 0)
      changes.updated += Number(change.counts?.updated || 0)
      changes.deleted += Number(change.counts?.deleted || 0)
    }
  }
  const parts = [
    databases.size ? `读取 ${Array.from(databases).slice(0, 2).join('、')}` : '',
    employees ? `AI 员工 ${employees}` : '',
    prints ? `打单 ${prints}` : '',
    changes.created ? `新增 ${changes.created}` : '',
    changes.updated ? `修改 ${changes.updated}` : '',
    changes.deleted ? `删除 ${changes.deleted}` : '',
  ].filter(Boolean)
  return parts.join(' · ')
}
