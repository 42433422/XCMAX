import { describe, it, expect, vi, beforeEach } from 'vitest'
import { approvalApi } from './approval'

vi.mock('./core', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))

import { api } from './core'

describe('approvalApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('getPendingApprovals wraps array response', async () => {
    vi.mocked(api.get).mockResolvedValue({ success: true, data: [{ id: 1 }] })
    const res = await approvalApi.getPendingApprovals(42)
    expect(res.success).toBe(true)
    expect(res.data.requests).toHaveLength(1)
  })

  it('getPendingApprovals handles api error', async () => {
    vi.mocked(api.get).mockRejectedValue(new Error('network'))
    const res = await approvalApi.getPendingApprovals(1)
    expect(res.success).toBe(false)
    expect(res.data.requests).toEqual([])
  })

  it('getMyRequests wraps list', async () => {
    vi.mocked(api.get).mockResolvedValue({ success: true, data: [] })
    const res = await approvalApi.getMyRequests(7)
    expect(res.data.requests).toEqual([])
  })

  it('getRequestDetails returns data on success', async () => {
    vi.mocked(api.get).mockResolvedValue({ success: true, data: { id: 9 } })
    const res = await approvalApi.getRequestDetails(9)
    expect(res).toEqual({ success: true, data: { id: 9 } })
  })

  it('approve posts with opinion', async () => {
    vi.mocked(api.post).mockResolvedValue({ success: true })
    const res = await approvalApi.approve(1, 2, '同意')
    expect(api.post).toHaveBeenCalled()
    expect(res.success).toBe(true)
  })

  it('reject posts with reason', async () => {
    vi.mocked(api.post).mockResolvedValue({ success: true })
    await approvalApi.reject(1, 2, '不同意')
    expect(api.post).toHaveBeenCalled()
  })

  it('getPendingApprovals handles invalid response', async () => {
    vi.mocked(api.get).mockResolvedValue(null)
    const res = await approvalApi.getPendingApprovals(1)
    expect(res.success).toBe(false)
  })
})
