import type { AgentRunEvent } from '@/api/agentRuns'
import type { PlannerSseEvent } from '@/utils/chatSseStream'
import { asRecord, asString } from '@/utils/typeGuards'
import { runtimeToolResultStatus, toolActivityLabel } from '@/utils/toolLabels'

/** Project durable SDK observations into the existing chat event vocabulary. */
export function runtimeRunChatEvents(event: AgentRunEvent): PlannerSseEvent[] {
  const data = asRecord(event.data)
  const type = asString(event.event_type)
  if (type === 'runtime.model.started' && data.purpose === 'verification')
    return [{ type: 'thinking', delta: '正在独立核验结果…' }]
  if (type === 'runtime.model.started' || type === 'runtime.xiaox.turn.started')
    return [{ type: 'model_activity' }]
  if (type === 'runtime.model.completed')
    return [{ type: 'thinking', delta: '模型响应已完成，正在核对执行结果…' }]
  if (type === 'runtime.model.failure' || type === 'runtime.model.failed')
    return [{ type: 'thinking', delta: data.failure_kind === 'model_schema_rejected'
      ? '所选模型拒绝了核验格式，核验已停止。'
      : data.failure_kind === 'upstream_rate_limited'
        ? '上游模型限流（HTTP 429），原请求计量待核对。'
      : data.failure_kind === 'model_response_incomplete' && data.purpose === 'verification'
        ? '核验输出未完整结束，原回执已保留。'
        : data.outcome === 'unknown' ? '模型请求回执待核对。' : '模型请求未完成。' }]
  if (type === 'runtime.progress.stalled')
    return [{ type: 'thinking', delta: '尚无新的业务执行证据，正在调整执行策略…' }]
  if (type === 'runtime.output.quarantined')
    return [{ type: 'thinking', delta: '非交付输出已隔离，正在继续原任务…' }]
  if (type === 'runtime.recovery.strategy_changed') {
    const labels: Record<string, string> = { tool_constraint: '正在按原目标约束工具选择…', context_repair: '正在修复原任务上下文…', compatible_route: '正在核对原授权备用模型…' }
    return [{ type: 'thinking', delta: labels[asString(data.strategy)] || '正在恢复原任务执行…' }]
  }
  if (type === 'runtime.recovery.phase_handoff')
    return [{ type: 'thinking', delta: '小C正在交接执行进度，准备补齐剩余任务…' }]
  if (type === 'runtime.goal.verification.started')
    return [{ type: 'thinking', delta: '正在独立核对任务目标与操作回执…' }]
  if (type === 'runtime.goal.verified')
    return [{ type: 'thinking', delta: data.status === 'verified' ? '目标核验已通过。' : '目标核验未通过，请查看原任务回执。' }]
  if (type === 'runtime.xiaox.turn.completed')
    return [{ type: 'thinking', delta: '执行轮次已结束，正在读取原任务回执…' }]
  if (type !== 'runtime.xiaox.item.started' && type !== 'runtime.xiaox.item.completed') return []
  if (type.endsWith('.completed') && data.item_type === 'reasoning' && asString(data.public_summary))
    return [{ type: 'thinking', delta: asString(data.public_summary) }]
  if (asString(data.item_type) !== 'mcpToolCall') return []
  const started = type.endsWith('.started')
  const toolId = asString(data.tool_id)
  const action = asString(data.action)
  const status = started ? 'running' : runtimeToolResultStatus(toolId, action, data.status)
  const finished = status === 'success' || status === 'failed'
  return [{
    type: 'tool_call', phase: started ? 'started' : finished ? 'finished' : 'progress',
    ...(finished ? { success: status === 'success' } : {}),
    node_id: asString(data.item_id), tool_id: toolId, action,
    label: toolActivityLabel(toolId, action, status)
      || (started ? '正在调用授权工具…' : status === 'failed' ? '工具调用失败' : '工具调用结束，正在核对回执…'),
  }]
}
