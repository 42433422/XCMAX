import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({ get: vi.fn() }))
const resolveErpApiPathMock = vi.hoisted(() => vi.fn((path: string) => `/resolved${path}`))

vi.mock('./core', () => ({ api: apiMock, default: apiMock }))
vi.mock('@/utils/erpDomainPaths', () => ({ resolveErpApiPath: resolveErpApiPathMock }))

import shipmentApi from './shipment'

beforeEach(() => {
  apiMock.get.mockReset().mockResolvedValue({ success: true })
  resolveErpApiPathMock.mockClear()
})

describe('shipmentApi', () => {
  it('builds the product-preview query with and without a purchase unit', async () => {
    await shipmentApi.getProductMetaForPreview({ model: 'M-1', unitName: '甲公司' })
    expect(apiMock.get).toHaveBeenLastCalledWith('/api/products/list', {
      keyword: 'M-1',
      model_number: 'M-1',
      page: 1,
      per_page: 20,
      unit: '甲公司',
    })

    await shipmentApi.getProductMetaForPreview({ model: 'M-2' })
    expect(apiMock.get).toHaveBeenLastCalledWith('/api/products/list', {
      keyword: 'M-2',
      model_number: 'M-2',
      page: 1,
      per_page: 20,
    })
  })

  it('falls through failed order-number candidates and accepts the next-number shape', async () => {
    apiMock.get
      .mockRejectedValueOnce(new Error('legacy endpoint unavailable'))
      .mockResolvedValueOnce({ success: false, data: { order_number: 'ignored' } })
      .mockResolvedValueOnce({ success: true, data: { next_number: ' SO-42 ' } })

    await expect(shipmentApi.fetchNextOrderNumber()).resolves.toBe('SO-42')
    expect(apiMock.get).toHaveBeenCalledTimes(3)
  })

  it('encodes the unit and resolves the shipment-record path through the ERP facade', async () => {
    await shipmentApi.getShipmentRecordsForUnit(' 甲 公司 ')

    const rawPath = '/api/shipment/shipment-records/records?unit=%E7%94%B2%20%E5%85%AC%E5%8F%B8'
    expect(resolveErpApiPathMock).toHaveBeenCalledWith(rawPath)
    expect(apiMock.get).toHaveBeenCalledWith(`/resolved${rawPath}`)
  })
})
