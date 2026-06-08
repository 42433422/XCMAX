import { describe, expect, it, vi, beforeEach } from 'vitest'
import { sandboxApi } from './sandboxApi'
import { requestJson } from '../infrastructure/http/client'

vi.mock('../infrastructure/http/client', () => ({
  requestJson: vi.fn(),
}))

describe('sandboxApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('connectHost calls requestJson with POST', async () => {
    vi.mocked(requestJson).mockResolvedValue({ ok: true })
    await sandboxApi.connectHost('http://localhost:8765')
    expect(requestJson).toHaveBeenCalledWith('/api/sandbox/connect', expect.objectContaining({ method: 'POST' }))
  })

  it('pushAndTest calls requestJson with POST', async () => {
    vi.mocked(requestJson).mockResolvedValue({ ok: true })
    await sandboxApi.pushAndTest('http://localhost:8765', 'mod1')
    expect(requestJson).toHaveBeenCalledWith('/api/sandbox/push-and-test', expect.objectContaining({ method: 'POST' }))
  })

  it('getHostStatus calls requestJson with GET', async () => {
    vi.mocked(requestJson).mockResolvedValue({ connected: true })
    await sandboxApi.getHostStatus()
    expect(requestJson).toHaveBeenCalledWith('/api/sandbox/host-status')
  })
})
