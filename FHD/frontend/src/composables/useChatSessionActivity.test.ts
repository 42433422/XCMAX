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
