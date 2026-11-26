import { ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import agentRunsApi from '@/api/agentRuns'
import { recordProductFastPathTask, useChatSessionActivity } from './useChatSessionActivity'

vi.mock('@/api/agentRuns', () => ({
  default: { observeTool: vi.fn().mockResolvedValue({ success: true }) },
}))

describe('useChatSessionActivity', () => {
  it('keeps concurrent task activity isolated by conversation', () => {
    const activeSessionId = ref('task-a')
    const activity = useChatSessionActivity(activeSessionId)
    const taskA = activity.forSession('task-a')
    const taskB = activity.forSession('task-b')

    taskA.setLoading(true)
    taskA.setStreaming(true)
    taskB.setLoading(true)
    expect(activity.statuses.value).toEqual({ 'task-a': 'streaming', 'task-b': 'submitted' })
    expect(activity.isLoading.value).toBe(true)
    expect(activity.isStreamingReply.value).toBe(true)

    activeSessionId.value = 'task-b'
    expect(activity.isLoading.value).toBe(true)
    expect(activity.isStreamingReply.value).toBe(false)
    activity.cancelSession('task-a')
    expect(activity.isLoading.value).toBe(true)
    expect(activity.statuses.value).toEqual({ 'task-a': 'stopped', 'task-b': 'submitted' })

    taskB.setStatus('waiting')
    taskB.setLoading(false)
    expect(activity.isLoading.value).toBe(false)
    expect(activity.statuses.value['task-b']).toBe('waiting')
  })

  it('keeps a manual stop on its own turn until a new round starts', () => {
    const sessionId = ref('chat-a')
    const identity = ref('account-a')
    const activity = useChatSessionActivity(sessionId, () => identity.value)
    const round = activity.beginRound('chat-a', 'turn-a')
    round.setLoading(true)

    expect(activity.cancelSession('chat-a', { showStopNotice: true })).toBe(true)
    expect(activity.stoppedTurnId.value).toBe('turn-a')
    expect(round.signal.aborted).toBe(true)
    sessionId.value = 'chat-b'
    expect(activity.stoppedTurnId.value).toBeUndefined()
    sessionId.value = 'chat-a'
    identity.value = 'account-b'
    expect(activity.stoppedTurnId.value).toBeUndefined()
    identity.value = 'account-a'
    const next = activity.beginRound('chat-a', 'turn-b')
    expect(activity.stoppedTurnId.value).toBeUndefined()
    next.setLoading(true)
    activity.cancelSession()
    expect(activity.stoppedTurnId.value).toBeUndefined()
  })

  it('records product fast paths under the original task identity', async () => {
    await recordProductFastPathTask('task-a', '查询 5003', '5003', [{ model_number: '5003' }], 1, '命中 1 条')
    expect(agentRunsApi.observeTool).toHaveBeenCalledWith(
      expect.objectContaining({
        message: '查询 5003',
        tool_id: 'products',
        action: 'query',
        output: { success: true, returned: 1, total: 1 },
        runtime_context: expect.objectContaining({
          task_id: 'task-a',
          conversation_id: 'task-a',
        }),
      }),
    )
  })
})
