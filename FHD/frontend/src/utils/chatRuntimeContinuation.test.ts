import { describe, expect, it } from 'vitest'
import { isRuntimeQueued, pendingRuntimeRunId, restoreRuntimeContinuation } from './chatRuntimeContinuation'
import type { ChatPlannerPayload } from '@/types/chat'
import type { UiChatMessage } from '@/types/chat-ui'

describe('queued runtime continuation', () => {
  it('keeps the run pointer so events can be followed', () => {
    const continuation = restoreRuntimeContinuation({ runId: 'run-1', status: 'queued', sessionId: 's1' })
    expect(continuation).toEqual({ runId: 'run-1', status: 'queued', sessionId: 's1' })
  })

  it('never treats a queued run as a user-input wait to resubmit', () => {
    const messages = [{
      role: 'ai',
      content: '任务已受理，正在等待后台执行。',
      time: '',
      runtimeContinuation: { runId: 'run-1', status: 'queued', sessionId: 's1' },
    }] as UiChatMessage[]
    expect(pendingRuntimeRunId(messages, 's1')).toBeUndefined()
  })

  it('recognizes the queued execution state from the payload envelope', () => {
    const payload = {
      runtime: 'xiaox',
      execution_state: 'queued',
      data: { execution_state: 'queued' },
    } as unknown as ChatPlannerPayload
    expect(isRuntimeQueued(payload)).toBe(true)
  })
})
