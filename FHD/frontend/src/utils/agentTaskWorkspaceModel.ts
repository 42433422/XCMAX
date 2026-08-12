import type {
  AgentArtifact,
  AgentRun,
  AgentRunEvent,
  AgentRunStep,
  AgentTaskSummary,
  AgentToolCall,
} from '@/api/agentRuns'
import type { TaskItem, TaskStatus } from '@/composables/useChatPersistence'
import { asArray, asRecord, asString } from '@/utils/typeGuards'

export interface AgentTaskContext {
  task_id: string
  title: string
  conversation_id: string
  root_run_id: string
  parent_run_id: string
  attempt: number
  workspace_id: string
  workspace_path: string
  isolation: string
}

function timestamp(value: unknown): number {
  const parsed = Date.parse(asString(value))
  return Number.isFinite(parsed) ? parsed : 0
}

function taskContextOf(run: AgentRun): AgentTaskContext {
  const metadata = asRecord(run.metadata)
  const raw = asRecord(metadata.task_context)
  const runtime = asRecord(metadata.runtime_context)
  const conversationId = asString(
    raw.conversation_id || runtime.conversation_id || runtime.session_id,
  ).trim()
  return {
    task_id: asString(raw.task_id || conversationId || run.run_id).trim(),
    title: asString(raw.title || run.message).trim(),
    conversation_id: conversationId,
    root_run_id: asString(raw.root_run_id || run.run_id).trim(),
    parent_run_id: asString(raw.parent_run_id).trim(),
    attempt: Math.max(1, Number(raw.attempt || 1) || 1),
    workspace_id: asString(raw.workspace_id || runtime.workspace_id || runtime.workspace).trim(),
    workspace_path: asString(
      raw.workspace_path || runtime.worktree_path || runtime.workspace_path || runtime.cwd,
    ).trim(),
    isolation: asString(raw.isolation || 'business_workspace').trim(),
  }
}

function displayStatus(raw: string): TaskStatus {
  if (['planning', 'running', 'retrying'].includes(raw)) return 'running'
  if (raw === 'paused') return 'paused'
  if (['waiting_user', 'blocked'].includes(raw)) return 'blocked'
  if (raw === 'completed') return 'success'
  if (raw === 'failed') return 'failed'
  if (raw === 'cancelled') return 'cancelled'
  return 'queued'
}

function stageOf(raw: string): string {
  const labels: Record<string, string> = {
    queued: '排队中',
    planning: '正在生成执行计划',
    running: '执行中',
    retrying: '正在重试',
    waiting_user: '等待审批或用户确认',
    blocked: '等待依赖解除',
    paused: '已暂停，可继续',
    completed: '任务完成',
    failed: '执行失败',
    cancelled: '已中断',
  }
  return labels[raw] || '状态待同步'
}

function latestRun(runs: AgentRun[]): AgentRun {
  const sorted = [...runs].sort((left, right) => {
    const updated = timestamp(right.updated_at) - timestamp(left.updated_at)
    if (updated !== 0) return updated
    return right.run_id.localeCompare(left.run_id)
  })
  const active = sorted.find((run) =>
    ['planning', 'running', 'retrying', 'waiting_user', 'blocked', 'paused', 'queued']
      .includes(asString(run.status)),
  )
  return active || sorted[0]
}

function exactProgress(steps: AgentRunStep[]): number | undefined {
  if (!steps.length) return undefined
  const settled = steps.filter((step) => ['completed', 'failed', 'skipped'].includes(asString(step.status))).length
  return Math.round((settled / steps.length) * 100)
}

function evidenceOf(runs: AgentRun[]) {
  const artifacts = runs.flatMap((run) => asArray<AgentArtifact>(run.artifacts))
  const metadataEvidence = runs.flatMap((run) => {
    const metadata = asRecord(run.metadata)
    const evidence = metadata.delivery_evidence || metadata.delivery
    return Array.isArray(evidence) ? evidence : (evidence ? [evidence] : [])
  })
  return {
    artifacts,
    delivery: metadataEvidence,
    artifact_count: artifacts.length,
    event_count: runs.reduce((count, run) => count + asArray(run.events).length, 0),
    completed_tool_count: runs.reduce(
      (count, run) => count + asArray<AgentToolCall>(run.tool_calls)
        .filter((call) => asString(call.status) === 'completed').length,
      0,
    ),
  }
}

function capabilitiesOf(run: AgentRun) {
  const status = asString(run.status)
  return {
    approve: status === 'waiting_user',
    pause: ['queued', 'planning', 'running', 'retrying', 'waiting_user'].includes(status),
    resume: status === 'paused',
    cancel: ['queued', 'planning', 'running', 'retrying', 'waiting_user', 'paused', 'blocked']
      .includes(status),
    retry: ['failed', 'cancelled', 'blocked'].includes(status)
      && !asRecord(run.metadata).non_retryable,
    evidence: true,
  }
}

export function groupAgentRunsIntoTasks(runs: AgentRun[]): TaskItem[] {
  const groups = new Map<string, AgentRun[]>()
  asArray<AgentRun>(runs).forEach((run) => {
    if (!asString(run.run_id).trim()) return
    const context = taskContextOf(run)
    const key = context.task_id || run.run_id
    groups.set(key, [...(groups.get(key) || []), run])
  })

  return [...groups.entries()].map(([taskId, groupedRuns]) => {
    const ordered = [...groupedRuns].sort((left, right) =>
      timestamp(left.created_at) - timestamp(right.created_at),
    )
    const current = latestRun(ordered)
    const context = taskContextOf(current)
    const firstContext = taskContextOf(ordered[0])
    const steps = asArray<AgentRunStep>(current.steps)
    const toolCalls = ordered.flatMap((run) => asArray<AgentToolCall>(run.tool_calls))
    const events = ordered.flatMap((run) => asArray<AgentRunEvent>(run.events))
    const evidence = evidenceOf(ordered)
    const status = displayStatus(asString(current.status))
    const title = firstContext.title || context.title || asString(ordered[0].message) || taskId
    const error = status === 'failed' ? asString(current.error || '任务执行失败') : ''
    return {
      id: `agent_task_${taskId}`,
      type: 'agent_task',
      source: 'agent' as const,
      title,
      status,
      progress: exactProgress(steps),
      stage: stageOf(asString(current.status)),
      summary: status === 'success'
        ? `任务已完成 · ${ordered.length} 次运行 · ${toolCalls.length} 次工具调用`
        : `${ordered.length} 次运行 · ${toolCalls.length} 次工具调用`,
      error,
      startedAt: timestamp(ordered[0].created_at) || Date.now(),
      updatedAt: timestamp(current.updated_at) || Date.now(),
      payload: {
        serverBacked: true,
        taskId,
        conversationId: context.conversation_id || firstContext.conversation_id,
        activeRunId: current.run_id,
        rootRunId: context.root_run_id,
        parentRunId: context.parent_run_id,
        attempt: context.attempt,
        workspaceId: context.workspace_id || firstContext.workspace_id,
        workspacePath: context.workspace_path || firstContext.workspace_path,
        workspaceIsolation: context.isolation || firstContext.isolation,
        runIds: ordered.map((run) => run.run_id),
        runCount: ordered.length,
        steps,
        toolCalls,
        agentEvents: events,
        artifacts: evidence.artifacts,
        deliveryEvidence: evidence.delivery,
        artifactCount: evidence.artifact_count,
        eventCount: evidence.event_count,
        completedToolCount: evidence.completed_tool_count,
        finalOutput: current.final_output || {},
        capabilities: capabilitiesOf(current),
        rawRunStatus: current.status,
      },
    }
  }).sort((left, right) => right.updatedAt - left.updatedAt)
}

export function taskSummariesToTaskItems(tasks: AgentTaskSummary[]): TaskItem[] {
  return asArray<AgentTaskSummary>(tasks).map((summary) => {
    const runs = asArray<AgentRun>(summary.runs)
    const activeRun = summary.active_run
    const base = groupAgentRunsIntoTasks(runs.length ? runs : (activeRun ? [activeRun] : []))[0]
    const rawStatus = asString(summary.status || activeRun?.status || 'queued')
    const controlCommand = summary.control_command
    const pendingControl = controlCommand?.status === 'requested'
      ? controlCommand.action
      : ''
    const taskStage = pendingControl === 'pause'
      ? '正在请求暂停'
      : pendingControl === 'cancel'
        ? '正在请求取消'
        : stageOf(rawStatus)
    const updatedAt = timestamp(summary.updated_at || activeRun?.updated_at) || Date.now()
    if (!base) {
      return {
        id: `agent_task_${summary.task_id}`,
        type: 'agent_task',
        source: 'agent' as const,
        title: asString(summary.title || summary.task_id),
        status: displayStatus(rawStatus),
        stage: taskStage,
        summary: `${Number(summary.run_count || 0)} 次运行`,
        startedAt: timestamp(summary.created_at) || updatedAt,
        updatedAt,
        payload: {
          serverBacked: true,
          taskId: summary.task_id,
          activeRunId: summary.active_run_id,
          runCount: Number(summary.run_count || 0),
          attentionState: summary.attention_state || '',
          controlCommand,
          capabilities: summary.capabilities || {},
          rawRunStatus: rawStatus,
        },
      }
    }
    return {
      ...base,
      id: `agent_task_${summary.task_id}`,
      title: asString(summary.title || base.title),
      status: displayStatus(rawStatus),
      stage: taskStage,
      updatedAt,
      payload: {
        ...(base.payload || {}),
        serverBacked: true,
        taskId: summary.task_id,
        activeRunId: summary.active_run_id || activeRun?.run_id,
        runCount: Number(summary.run_count || runs.length),
        attentionState: summary.attention_state || '',
        controlCommand,
        capabilities: summary.capabilities || asRecord(base.payload).capabilities || {},
        rawRunStatus: rawStatus,
      },
    }
  }).sort((left, right) => right.updatedAt - left.updatedAt)
}

export function activeRunIdOfTask(task: TaskItem): string {
  return asString(asRecord(task.payload).activeRunId).trim()
}

export function conversationIdOfTask(task: TaskItem): string {
  return asString(asRecord(task.payload).conversationId).trim()
}
