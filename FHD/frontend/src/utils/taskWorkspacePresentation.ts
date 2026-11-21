import type { AgentTaskSummary } from '@/api/agentRuns'
import { taskHasUncertainReceipt } from '@/utils/agentRunExecution'

export function taskStatusOf(task: AgentTaskSummary | null | undefined): string {
  return task && taskHasUncertainReceipt(task) ? 'unknown' : task?.status || 'unknown'
}

export function taskUnreadCount(task: AgentTaskSummary | null | undefined): number {
  if (!task) return 0
  return Math.max(0, Number(task.unread_count ?? (task.attention_state === 'result_unread' ? 1 : 0)) || 0)
}

export function taskNeedsApproval(task: AgentTaskSummary | null | undefined): boolean {
  if (!task || taskHasUncertainReceipt(task)) return false
  return Boolean(task.approval_required || task.attention_state === 'approval_required' || task.status === 'waiting_user')
}

export function taskProgressPercent(task: AgentTaskSummary | null | undefined): number {
  if (!task) return 0
  const value = Number(task.progress?.percent)
  if (Number.isFinite(value)) return Math.max(0, Math.min(100, Math.round(value)))
  return taskStatusOf(task) === 'completed' ? 100 : 0
}

export function taskStatusLabel(status: string | undefined): string {
  return (
    {
      queued: '排队中',
      claimed: '执行中',
      planning: '规划中',
      running: '执行中',
      retrying: '重试中',
      waiting_user: '等待审批',
      waiting_approval: '等待审批',
      waiting_input: '等待补充信息',
      waiting_auth: '等待授权',
      unknown: '结果待核对',
      accepted: '已受理',
      paused: '已暂停',
      blocked: '已阻断',
      completed: '已完成',
      failed: '失败',
      cancelled: '已取消',
      pending: '待执行',
      skipped: '已跳过',
    }[String(status || '')] || String(status || '未知')
  )
}
