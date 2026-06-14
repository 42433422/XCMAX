import { describe, it, expect, vi, beforeEach } from 'vitest'

const { apiMock, ApiError } = vi.hoisted(() => {
  class ApiError extends Error {
    status: number
    constructor(message: string, status: number) {
      super(message)
      this.status = status
    }
  }
  return {
    apiMock: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn(), download: vi.fn() },
    ApiError,
  }
})

vi.mock('./core', () => ({ api: apiMock, default: apiMock, ApiError }))

import ordersApi from './orders'

beforeEach(() => {
  for (const fn of Object.values(apiMock)) fn.mockReset().mockResolvedValue({ success: true })
})

describe('ordersApi', () => {
  it('covers endpoints', async () => {
    await ordersApi.getOrders({ page: 1 })
    await ordersApi.getOrder('SO 1')
    await ordersApi.getLatestOrders()
    await ordersApi.searchOrders('q')
    await ordersApi.searchOrders('')
    await ordersApi.deleteOrder('SO 1')
    await ordersApi.clearAllOrders()
    await ordersApi.getShipmentRecords('unit')
    await ordersApi.createShipmentRecord({ a: 1 })
    await ordersApi.updateShipmentRecord({ a: 1 })
    await ordersApi.deleteShipmentRecord({ a: 1 })
    await ordersApi.exportShipmentRecords('unit')
    expect(apiMock.get).toHaveBeenCalled()
    expect(apiMock.download).toHaveBeenCalled()
    expect(apiMock.patch).toHaveBeenCalled()
  })

  it('getOrder encodes order number', async () => {
    await ordersApi.getOrder('A/B')
    expect(apiMock.get).toHaveBeenLastCalledWith(expect.stringContaining('A%2FB'))
  })

  it('getShipmentRecordUnits returns primary result', async () => {
    apiMock.get.mockResolvedValueOnce({ success: true, data: [1] })
    const r = await ordersApi.getShipmentRecordUnits()
    expect(r.data).toEqual([1])
  })

  it('getShipmentRecordUnits falls back on 404', async () => {
    apiMock.get.mockRejectedValueOnce(new ApiError('nf', 404))
    apiMock.get.mockResolvedValueOnce({ success: true, data: ['unit'] })
    const r = await ordersApi.getShipmentRecordUnits()
    expect(r.data).toEqual(['unit'])
    expect(apiMock.get).toHaveBeenLastCalledWith(expect.stringContaining('purchase_units'))
  })

  it('getShipmentRecordUnits rethrows non-404', async () => {
    apiMock.get.mockRejectedValueOnce(new ApiError('boom', 500))
    await expect(ordersApi.getShipmentRecordUnits()).rejects.toThrow('boom')
  })
})
