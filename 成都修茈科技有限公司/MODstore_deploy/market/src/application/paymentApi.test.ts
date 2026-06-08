import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  listEntitlements,
  listPlans,
  queryOrder,
  walletBalance,
  walletTransactions,
} from './paymentApi'
import { requestJson } from '../infrastructure/http/client'

vi.mock('../infrastructure/http/client', () => ({
  requestJson: vi.fn(),
}))

const requestJsonMock = vi.mocked(requestJson)

describe('paymentApi', () => {
  beforeEach(() => {
    requestJsonMock.mockReset()
    requestJsonMock.mockResolvedValue({})
  })

  it('requests plan and entitlement endpoints', async () => {
    await listPlans()
    await listEntitlements()

    expect(requestJsonMock).toHaveBeenNthCalledWith(1, '/api/payment/plans')
    expect(requestJsonMock).toHaveBeenNthCalledWith(2, '/api/payment/entitlements')
  })

  it('encodes order ids when querying orders', async () => {
    await queryOrder('order/with space')

    expect(requestJsonMock).toHaveBeenCalledWith('/api/payment/query/order%2Fwith%20space')
  })

  it('requests wallet balance and transactions with defaults', async () => {
    await walletBalance()
    await walletTransactions()

    expect(requestJsonMock).toHaveBeenNthCalledWith(1, '/api/wallet/balance')
    expect(requestJsonMock).toHaveBeenNthCalledWith(
      2,
      '/api/wallet/transactions?limit=50&offset=0',
    )
  })

  it('passes explicit wallet transaction pagination', async () => {
    await walletTransactions(10, 20)

    expect(requestJsonMock).toHaveBeenCalledWith('/api/wallet/transactions?limit=10&offset=20')
  })
})
