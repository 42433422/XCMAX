import type { AgentRunEvent } from '@/api/agentRuns'
import type { PlannerSseEvent } from '@/utils/chatSseStream'
import { asRecord, asString } from '@/utils/typeGuards'

/** Project durable SDK observations into the existing chat event vocabulary. */
export function runtimeRunChatEvents(event: AgentRunEvent): PlannerSseEvent[] {
  const data = asRecord(event.data)
  const type = asString(event.event_type)
  if (type === 'runtime.model.started' || type === 'runtime.xiaox.turn.started')
    return [{ type: 'model_activity' }]
  if (type === 'runtime.model.completed')
    return [{ type: 'thinking', delta: '模型响应已完成，正在核对执行结果…' }]
  if (type === 'runtime.model.failure' || type === 'runtime.model.failed')
    return [{ type: 'thinking', delta: '模型请求未完成，正在核对原请求状态…' }]
  if (type === 'runtime.goal.verification.started')
    return [{ type: 'thinking', delta: '正在独立核对任务目标与操作回执…' }]
  if (type === 'runtime.goal.verified')
    return [{ type: 'thinking', delta: data.status === 'verified' ? '目标核验已通过。' : '目标核验未通过，请查看原任务回执。' }]
  if (type === 'runtime.xiaox.turn.completed')
    return [{ type: 'thinking', delta: '执行轮次已结束，正在读取原任务回执…' }]
  if (type !== 'runtime.xiaox.item.started' && type !== 'runtime.xiaox.item.completed') return []
  if (asString(data.item_type) !== 'mcpToolCall') return []
  const started = type.endsWith('.started')
  return [{
    type: 'tool_call', phase: started ? 'started' : 'progress',
    node_id: asString(data.item_id), tool_id: asString(data.tool_id), action: asString(data.action),
    label: started ? '正在调用授权工具…' : '工具调用结束，正在核对回执…',
  }]
}
