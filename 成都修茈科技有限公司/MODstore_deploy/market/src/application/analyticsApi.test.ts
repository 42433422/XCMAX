import { describe, expect, it, vi, beforeEach } from 'vitest'
import { dashboard } from './analyticsApi'
import { requestJson } from '../infrastructure/http/client'

vi.mock('../infrastructure/http/client', () => ({
  requestJson: vi.fn(),
}))

describe('analyticsApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('dashboard calls requestJson', async () => {
    vi.mocked(requestJson).mockResolvedValue({ metrics: {} })
    const result = await dashboard()
    expect(requestJson).toHaveBeenCalledWith('/api/analytics/dashboard')
    expect(result).toEqual({ metrics: {} })
  })
})
