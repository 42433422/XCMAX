import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useWorkbenchStore } from '../stores/workbench'
import { useAgentLoop } from './useAgentLoop'

vi.mock('../infrastructure/storage/tokenStore', () => ({
  getAccessToken: vi.fn(() => 'agent-token'),
}))

function sseResponse(events: Array<Record<string, unknown> | string>, options: ResponseInit = {}) {
  const body = events.map((event) => (typeof event === 'string' ? event : `data: ${JSON.stringify(event)}`)).join('\n') + '\n'
  return new Response(body, { status: 200, ...options })
}

describe('useAgentLoop', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  it('consumes every employee draft stage and finishes with a manifest', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        sseResponse([
          { event: 'review_reply', message: 'ignored structural event' },
          { event: 'clarification_question', message: 'question' },
          { event: 'stage_start', stage: 'parse_intent' },
          { event: 'stage_progress', stage: 'design_v2', message: 'working' },
          { event: 'stage_done', stage: 'assemble', data: { ok: true } },
          { event: 'stage_error', stage: 'suggest_skills', error: 'optional failure' },
          { event: 'pipeline_done', manifest: { id: 'employee-a' } },
          'data: malformed-json',
        ]),
      ),
    )
    const loop = useAgentLoop()
    const result = await loop.runEmployeeDraft('build employee', {
      provider: 'deepseek',
      model: 'chat',
      suggestedId: 'employee-a',
    })
    const store = useWorkbenchStore()
    const run = store.agentRuns.find((candidate) => candidate.id === result.runId)
    expect(run?.status).toBe('done')
    expect(run?.events.length).toBeGreaterThanOrEqual(4)
    expect(result.runId).toBeTruthy()
    result.abort()
  })

  it('records pipeline errors and unexpected stream endings', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(sseResponse([{ event: 'pipeline_error', error: 'bad pipeline' }]))
      .mockResolvedValueOnce(sseResponse([{ event: 'stage_start', stage: 'unknown_stage' }]))
    vi.stubGlobal('fetch', fetchMock)
    const loop = useAgentLoop()
    await loop.runEmployeeDraft('bad')
    expect(useWorkbenchStore().agentRuns[0]?.status).toBe('error')
    await loop.runEmployeeDraft('ends early')
    expect(useWorkbenchStore().employeeDraftStatus.fatalError).toBe('流意外结束')
  })

  it('maps script workflow progress, completion and error events', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        sseResponse([
          { event: 'context', message: 'context' },
          { type: 'plan', message: 'plan' },
          { event: 'done', result: { ok: true } },
        ]),
      ),
    )
    const loop = useAgentLoop()
    await loop.runScriptWorkflow({ description: 'script task' })
    expect(useWorkbenchStore().agentRuns[0]?.status).toBe('done')

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => sseResponse([{ event: 'error', error: 'boom' }])),
    )
    await loop.runScriptWorkflow({ brief: 'bad script' })
    expect(useWorkbenchStore().agentRuns[0]?.status).toBe('error')
  })

  it('surfaces HTTP JSON errors, missing bodies and network failures', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: 'denied' }), {
          status: 403,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce({ ok: true, status: 200, body: null })
      .mockRejectedValueOnce(new Error('offline'))
    vi.stubGlobal('fetch', fetchMock)
    const loop = useAgentLoop()
    await loop.runEmployeeDraft('denied')
    expect(useWorkbenchStore().employeeDraftStatus.fatalError).toBe('denied')
    await loop.runScriptWorkflow({ description: 'no body' })
    expect(useWorkbenchStore().agentRuns[0]?.status).toBe('error')
    await loop.runScriptWorkflow({ description: 'offline' })
    expect(useWorkbenchStore().agentRuns[0]?.events.at(-1)?.stage).toBe('network')
  })
})
