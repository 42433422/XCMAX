import { describe, it, expect, vi } from 'vitest'

vi.mock('@/utils/modelPaymentPaths', () => ({
  resolveModelPaymentApiPath: (p: string) => p,
}))

vi.mock('./core', () => ({
  api: {
    get: vi.fn().mockResolvedValue({ success: true }),
    post: vi.fn().mockResolvedValue({ success: true }),
  },
}))

import { modelPaymentApi } from './modelPayment'
import { api } from './core'

describe('modelPaymentApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('getPlans calls api.get', async () => {
    await modelPaymentApi.getPlans()
    expect(api.get).toHaveBeenCalledWith('/api/model-payment/plans', undefined)
  })

  it('checkout calls api.post with plan_id', async () => {
    await modelPaymentApi.checkout('plan-1')
    expect(api.post).toHaveBeenCalledWith('/api/model-payment/checkout', { plan_id: 'plan-1' })
  })

  it('getEntitlements calls api.get', async () => {
    await modelPaymentApi.getEntitlements()
    expect(api.get).toHaveBeenCalledWith('/api/model-payment/entitlements')
  })
})
