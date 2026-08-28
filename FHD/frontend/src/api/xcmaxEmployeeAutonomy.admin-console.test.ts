import { beforeEach, describe, expect, it, vi } from 'vitest'

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

vi.mock('@/api/core', () => ({ default: mockApi }))

import { xcmaxEmployeeAutonomyApi } from '../../../admin-console/src/api/xcmaxEmployeeAutonomy'

describe('admin employee autonomy API', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('uses the backend batch review contract', async () => {
    mockApi.post.mockResolvedValue({ ok: true })

    await xcmaxEmployeeAutonomyApi.batchReview({
      ids: [11, 12],
      action: 'approve',
      dispatch_now: true,
    })

    expect(mockApi.post).toHaveBeenCalledWith(
      '/api/xcmax/market-proxy/admin/employee-autonomy/suggestions/batch-review',
      { ids: [11, 12], action: 'approve', dispatch_now: true },
    )
  })

  it('loads execution coverage through the authenticated market proxy', async () => {
    mockApi.get.mockResolvedValue({ ok: true })

    await xcmaxEmployeeAutonomyApi.executionCoverage({ window_hours: 24 })

    expect(mockApi.get).toHaveBeenCalledWith(
      '/api/xcmax/market-proxy/admin/employee-autonomy/execution-coverage',
      { window_hours: 24 },
    )
  })

  it('loads scheduler runtime and falls back only on a missing proxy route', async () => {
    mockApi.get
      .mockRejectedValueOnce(Object.assign(new Error('not found'), { status: 404 }))
      .mockResolvedValueOnce({ ok: true })

    await xcmaxEmployeeAutonomyApi.runtime()

    expect(mockApi.get).toHaveBeenNthCalledWith(1, '/api/xcmax/market-proxy/scheduler/runtime')
    expect(mockApi.get).toHaveBeenNthCalledWith(2, '/api/scheduler/runtime')
  })
})
