import { describe, expect, it } from 'vitest'
import type { AgentRunEvent } from '@/api/agentRuns'
import { runtimeRunChatEvents } from './runtimeRunChatEvents'

function event(event_type: string, data: Record<string, unknown> = {}): AgentRunEvent {
  return { event_id: event_type, run_id: 'run-1', event_type, data }
}

describe('durable runtime events in chat', () => {
  it('shows model activity and safe progress without exposing unverified draft text', () => {
    expect(runtimeRunChatEvents(event('runtime.model.started'))).toEqual([{ type: 'model_activity' }])
    expect(runtimeRunChatEvents(event('runtime.xiaox.item.completed', {
      item_type: 'agentMessage', text: 'unverified draft',
    }))).toEqual([])
  })

  it('keeps tool completion pending until a business receipt is verified', () => {
    expect(runtimeRunChatEvents(event('runtime.xiaox.item.started', {
      item_type: 'mcpToolCall', item_id: 'call-1', tool_id: 'excel_analysis', action: 'read',
    }))).toMatchObject([{ type: 'tool_call', phase: 'started', node_id: 'call-1' }])
    expect(runtimeRunChatEvents(event('runtime.xiaox.item.completed', {
      item_type: 'mcpToolCall', item_id: 'call-1', status: 'completed',
    }))).toMatchObject([{ type: 'tool_call', phase: 'progress', node_id: 'call-1' }])
  })

  it('uses the runtime goal status when reporting verification', () => {
    expect(runtimeRunChatEvents(event('runtime.goal.verified', { status: 'verified' })))
      .toEqual([{ type: 'thinking', delta: '目标核验已通过。' }])
    expect(runtimeRunChatEvents(event('runtime.goal.verified', { status: 'needs_work' })))
      .toEqual([{ type: 'thinking', delta: '目标核验未通过，请查看原任务回执。' }])
  })
})
