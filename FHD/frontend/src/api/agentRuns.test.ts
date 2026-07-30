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

  it('controls a durable agent run', async () => {
    await agentRunsApi.pauseRun('run/1', { requested_by: 'u1' })
    await agentRunsApi.resumeRun('run/1')
    await agentRunsApi.cancelRun('run/1', { requested_by: 'u1' })
    await agentRunsApi.retryRun('run/1')

    expect(apiMock.post).toHaveBeenNthCalledWith(1, '/api/agent/runs/run%2F1/pause', {
      requested_by: 'u1',
    })
    expect(apiMock.post).toHaveBeenNthCalledWith(2, '/api/agent/runs/run%2F1/resume', {})
    expect(apiMock.post).toHaveBeenNthCalledWith(3, '/api/agent/runs/run%2F1/cancel', {
      requested_by: 'u1',
    })
    expect(apiMock.post).toHaveBeenNthCalledWith(4, '/api/agent/runs/run%2F1/retry', {})
  })

  it('reads run detail, list, and events', async () => {
    await agentRunsApi.getRun('run/1')
    await agentRunsApi.listRuns({ user_id: 'u1', limit: 10 })
    await agentRunsApi.listEvents('run/1', { after_event_id: 'evt_1' })
    await agentRunsApi.listRuns()
    await agentRunsApi.listEvents('run/2')
    await agentRunsApi.listToolContracts()

    expect(apiMock.get).toHaveBeenCalledWith('/api/agent/runs/run%2F1')
    expect(apiMock.get).toHaveBeenCalledWith('/api/agent/runs', { user_id: 'u1', limit: 10 })
    expect(apiMock.get).toHaveBeenCalledWith('/api/agent/runs/run%2F1/events', {
      after_event_id: 'evt_1',
    })
    expect(apiMock.get).toHaveBeenCalledWith('/api/agent/runs', {})
    expect(apiMock.get).toHaveBeenCalledWith('/api/agent/runs/run%2F2/events', {})
    expect(apiMock.get).toHaveBeenCalledWith('/api/agent/tools/contracts')
  })
})
