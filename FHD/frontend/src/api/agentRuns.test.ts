import { describe, expect, it, vi, beforeEach } from 'vitest'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}))

vi.mock('./core', () => ({
  api: apiMock,
}))

import agentRunsApi from './agentRuns'

describe('agentRunsApi', () => {
  beforeEach(() => {
    apiMock.get.mockReset().mockResolvedValue({ success: true })
    apiMock.post.mockReset().mockResolvedValue({ success: true })
  })

  it('creates an agent run', async () => {
    await agentRunsApi.createRun({
      message: '查产品',
      user_id: 'u1',
      runtime_context: { source: 'test' },
    })

    expect(apiMock.post).toHaveBeenCalledWith('/api/agent/runs', {
      message: '查产品',
      user_id: 'u1',
      runtime_context: { source: 'test' },
    })
  })

  it('continues an agent run', async () => {
    await agentRunsApi.continueRun('run/1', {
      approved_by: 'u1',
      step_id: 'step_1',
      runtime_context: { source: 'test' },
    })

    expect(apiMock.post).toHaveBeenCalledWith('/api/agent/runs/run%2F1/continue', {
      approved_by: 'u1',
      step_id: 'step_1',
      runtime_context: { source: 'test' },
    })
  })

  it('reads run detail, list, and events', async () => {
    await agentRunsApi.getRun('run/1')
    await agentRunsApi.listRuns({ user_id: 'u1', limit: 10 })
    await agentRunsApi.listEvents('run/1', { after_event_id: 'evt_1' })

    expect(apiMock.get).toHaveBeenCalledWith('/api/agent/runs/run%2F1')
    expect(apiMock.get).toHaveBeenCalledWith('/api/agent/runs', { user_id: 'u1', limit: 10 })
    expect(apiMock.get).toHaveBeenCalledWith('/api/agent/runs/run%2F1/events', {
      after_event_id: 'evt_1',
    })
  })
})
