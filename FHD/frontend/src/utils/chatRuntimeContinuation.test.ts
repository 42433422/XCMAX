import { describe, expect, it } from 'vitest'
import { isRuntimeQueued, isRuntimeWaiting, pendingRuntimeRunId, restoreRuntimeContinuation, runtimeContinuationFromPayload } from './chatRuntimeContinuation'
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

describe.each(['codex', 'xiaox'])('runtime label %s', (runtime) => {
  it.each(['root', 'envelope'])('preserves the waiting parent from the %s label', (placement) => {
    const payload: ChatPlannerPayload = {
      ...(placement === 'root' ? { runtime } : {}),
      data: { ...(placement === 'envelope' ? { runtime } : {}), execution_state: 'waiting_user' },
      runtime_context_update: { agent_runtime_run_id: 'run_codex_original', conversation_id: 's1' },
    }
    const continuation = runtimeContinuationFromPayload(payload)
    expect(continuation).toEqual({ runId: 'run_codex_original', status: 'waiting_user', sessionId: 's1' })
    expect(isRuntimeWaiting(payload)).toBe(true)
    const messages = [{ role: 'ai', content: 'waiting', time: '', runtimeContinuation: continuation }] as UiChatMessage[]
    expect(pendingRuntimeRunId(messages, 's1')).toBe('run_codex_original')
    expect(pendingRuntimeRunId(messages, 's2')).toBeUndefined()
  })

  it('follows queued work without admitting a continuation', () => {
    const payload: ChatPlannerPayload = {
      data: { runtime, execution_state: 'queued' },
      runtime_context_update: { agent_runtime_run_id: 'run_codex_original', conversation_id: 's1' },
    }
    expect(isRuntimeQueued(payload)).toBe(true)
    expect(isRuntimeWaiting(payload)).toBe(false)
    const continuation = runtimeContinuationFromPayload(payload)
    expect(continuation?.runId).toBe('run_codex_original')
    expect(pendingRuntimeRunId([{ role: 'ai', content: 'queued', time: '', runtimeContinuation: continuation }] as UiChatMessage[], 's1')).toBeUndefined()
  })
})

it('does not interpret an unrelated runtime as a fixed-runtime continuation', () => {
  const payload: ChatPlannerPayload = {
    runtime: 'other', execution_state: 'waiting_user',
    runtime_context_update: { agent_runtime_run_id: 'run-1', conversation_id: 's1' },
  }
  expect(runtimeContinuationFromPayload(payload)).toBeUndefined()
  expect(isRuntimeWaiting(payload)).toBe(false)
})
