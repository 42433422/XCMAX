import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAgentStore } from '../../stores/agent'
import { useAuthStore } from '../../stores/auth'
import { useButlerOrchestrator } from './useButlerOrchestrator'

const mocks = vi.hoisted(() => ({ start: vi.fn(), read: vi.fn(), go: vi.fn() }))

vi.mock('vue-router', () => ({
  useRoute: () => ({ name: 'mod-authoring', params: { modId: 'original-mod' } }),
  useRouter: () => ({ go: mocks.go }),
}))
vi.mock('../../api', () => ({
  api: { butlerOrchestrateStart: mocks.start, workbenchGetSession: mocks.read },
}))

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

function invalidate(kind: 'account' | 'clear' | 'stop') {
  if (kind === 'account') useAuthStore().user = { id: 22, username: 'B', is_admin: false }
  else if (kind === 'clear') useAgentStore().clearMessages()
  else useAgentStore().stopRequest()
}

describe('orchestration account and conversation ownership', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
    vi.clearAllMocks()
    useAuthStore().user = { id: 11, username: 'A', is_admin: false }
    mocks.start.mockResolvedValue({ session_id: 'A-session', status: 'running' })
    mocks.read.mockResolvedValue({ status: 'done', steps: [] })
  })
  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
  })

  it.each(['account', 'clear', 'stop'] as const)('late POST after %s cannot publish or poll the old session', async (kind) => {
    const reply = deferred<{ session_id: string; status: string }>()
    mocks.start.mockReturnValueOnce(reply.promise)
    const store = useAgentStore()
    const pending = useButlerOrchestrator().start('private A brief', 'original-scope')
    invalidate(kind)
    reply.resolve({ session_id: 'A-session', status: 'running' })
    const result = await pending
    await vi.advanceTimersByTimeAsync(0)
    expect(result.ok).toBe(false)
    expect(result.sessionId).toBe('A-session')
    expect(result.error).toContain('尚未确认')
    expect(mocks.start).toHaveBeenCalledExactlyOnceWith({
      target_type: 'mod', target_id: 'original-mod', brief: 'private A brief', scope: 'original-scope',
    })
    expect(mocks.read).not.toHaveBeenCalled()
    expect(store.orchestrationSession).toBeNull()
    expect(store.mode).toBe('idle')
  })

  it.each(['account', 'clear', 'stop'] as const)('late poll after %s cannot overwrite another session or poll again', async (kind) => {
    const reply = deferred<{ status: string; steps: []; artifact: { mod_id: string } }>()
    mocks.read.mockReturnValueOnce(reply.promise)
    const store = useAgentStore()
    await useButlerOrchestrator().start('private A brief')
    expect(mocks.read).toHaveBeenCalledExactlyOnceWith('A-session')
    invalidate(kind)
    store.orchestrationSession = { sessionId: 'new-session', status: 'running', steps: [] }
    store.setMode('thinking')
    reply.resolve({ status: 'running', steps: [], artifact: { mod_id: 'A-private-artifact' } })
    await vi.advanceTimersByTimeAsync(1200)
    expect(mocks.read).toHaveBeenCalledTimes(1)
    expect(store.orchestrationSession).toEqual({ sessionId: 'new-session', status: 'running', steps: [] })
    expect(store.mode).toBe('thinking')
    expect(mocks.go).not.toHaveBeenCalled()
  })

  it('does not issue another poll after the conversation changes during the retry delay', async () => {
    mocks.read.mockResolvedValueOnce({ status: 'running', steps: [] })
    const store = useAgentStore()
    await useButlerOrchestrator().start('private A brief')
    await vi.advanceTimersByTimeAsync(0)
    expect(store.orchestrationSession?.sessionId).toBe('A-session')
    store.clearMessages()
    await vi.advanceTimersByTimeAsync(1200)
    expect(mocks.read).toHaveBeenCalledTimes(1)
    expect(mocks.start).toHaveBeenCalledTimes(1)
  })

  it('keeps the original session and monotonic steps for the current owner', async () => {
    mocks.read
      .mockResolvedValueOnce({ status: 'running', steps: [{ id: 'build', label: 'Build', status: 'done', message: 'built' }] })
      .mockResolvedValueOnce({ status: 'done', steps: [{ id: 'build', label: 'Build', status: 'pending', message: 'old' }], artifact: { mod_id: 'new-mod' } })
    const store = useAgentStore()
    expect(await useButlerOrchestrator().start('build it')).toEqual({ ok: true })
    await vi.advanceTimersByTimeAsync(1200)
    expect(mocks.start).toHaveBeenCalledTimes(1)
    expect(mocks.read.mock.calls).toEqual([['A-session'], ['A-session']])
    expect(store.orchestrationSession).toMatchObject({
      sessionId: 'A-session', status: 'done', artifact: { mod_id: 'new-mod' }, steps: [{ id: 'build', status: 'done' }],
    })
    expect(store.mode).toBe('idle')
  })
})
