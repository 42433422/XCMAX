import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useOrdersStore } from '@/stores/orders'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'

vi.mock('@/api/orders', () => ({
  default: {
    getOrders: vi.fn(),
    searchOrders: vi.fn(),
    deleteOrder: vi.fn(),
    updateOrder: vi.fn(),
    clearAllOrders: vi.fn(),
  },
}))

import ordersApi from '@/api/orders'

describe('useOrdersStore', () => {
  let store: ReturnType<typeof useOrdersStore>

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useOrdersStore()
    vi.clearAllMocks()
  })

  it('initializes with default state', () => {
    expect(store.orders).toEqual([])
    expect(store.loading).toBe(false)
    expect(store.error).toBeNull()
    expect(store.orderCount).toBe(0)
  })

  it('fetchOrders sets orders on success', async () => {
    ;(ordersApi.getOrders as any).mockResolvedValue({
      success: true,
      data: [{ id: 1, order_number: 'ORD-001' }],
    })
    const result = await store.fetchOrders()
    expect(result.success).toBe(true)
    expect(store.orders.length).toBe(1)
    expect(store.loading).toBe(false)
    expect(store.error).toBeNull()
  })

  it('fetchOrders handles API failure response', async () => {
    ;(ordersApi.getOrders as any).mockResolvedValue({
      success: false,
      message: 'Server error',
    })
    const result = await store.fetchOrders()
    expect(result.success).toBe(false)
    expect(store.error).toBe('Server error')
  })

  it('fetchOrders handles exception', async () => {
    ;(ordersApi.getOrders as any).mockRejectedValue(new Error('Network error'))
    const result = await store.fetchOrders()
    expect(result.success).toBe(false)
    expect(store.error).toBe('Network error')
    expect(store.loading).toBe(false)
  })

  it('fetchOrders sets loading during request', async () => {
    let resolvePromise!: (v: any) => void
    ;(ordersApi.getOrders as any).mockImplementation(
      () =>
        new Promise((r) => {
          resolvePromise = r
        }),
    )
    const promise = store.fetchOrders()
    expect(store.loading).toBe(true)
    resolvePromise({ success: true, data: [] })
    await promise
    expect(store.loading).toBe(false)
  })

  it('fetchOrders normalizes data with .data property', async () => {
    ;(ordersApi.getOrders as any).mockResolvedValue({
      data: [{ id: 1 }, { id: 2 }],
    })
    await store.fetchOrders()
    expect(store.orders.length).toBe(2)
  })

  it('fetchOrders normalizes the ERP facade nested response', async () => {
    ;(ordersApi.getOrders as any).mockResolvedValue({
      success: true,
      data: {
        success: true,
        data: [{ id: 9, purchase_unit: '门面客户' }],
      },
    })
    await store.fetchOrders()
    expect(store.orders).toEqual([{ id: 9, purchase_unit: '门面客户' }])
  })

  it('fetchOrders normalizes data with .orders property', async () => {
    ;(ordersApi.getOrders as any).mockResolvedValue({
      orders: [{ id: 3 }],
    })
    await store.fetchOrders()
    expect(store.orders.length).toBe(1)
  })

  it('fetchOrders normalizes array data', async () => {
    ;(ordersApi.getOrders as any).mockResolvedValue([{ id: 4 }])
    await store.fetchOrders()
    expect(store.orders.length).toBe(1)
  })

  it('searchOrders sets orders on success', async () => {
    ;(ordersApi.searchOrders as any).mockResolvedValue({
      success: true,
      data: [{ id: 1, order_number: 'ORD-001' }],
    })
    const result = await store.searchOrders('test')
    expect(result.success).toBe(true)
    expect(store.orders.length).toBe(1)
  })

  it('searchOrders handles failure', async () => {
    ;(ordersApi.searchOrders as any).mockResolvedValue({
      success: false,
      message: 'Not found',
    })
    const result = await store.searchOrders('nonexistent')
    expect(result.success).toBe(false)
    expect(store.error).toBe('Not found')
  })

  it('searchOrders handles exception', async () => {
    ;(ordersApi.searchOrders as any).mockRejectedValue(new Error('Network error'))
    const result = await store.searchOrders('test')
    expect(result.success).toBe(false)
    expect(store.error).toBe('Network error')
  })

  it('deleteOrder removes order from list on success', async () => {
    ;(ordersApi.getOrders as any).mockResolvedValue({
      data: [
        { id: 1, order_number: 'ORD-001' },
        { id: 2, order_number: 'ORD-002' },
      ],
    })
    await store.fetchOrders()
    expect(store.orders.length).toBe(2)
    ;(ordersApi.deleteOrder as any).mockResolvedValue({ success: true })
    const result = await store.deleteOrder('ORD-001')
    expect(result.success).toBe(true)
    expect(store.orders.length).toBe(1)
  })

  it('deleteOrder handles failure', async () => {
    ;(ordersApi.deleteOrder as any).mockResolvedValue({
      success: false,
      message: 'Cannot delete',
    })
    const result = await store.deleteOrder('ORD-001')
    expect(result.success).toBe(false)
    expect(store.error).toBe('Cannot delete')
  })

  it('deleteOrder handles exception', async () => {
    ;(ordersApi.deleteOrder as any).mockRejectedValue(new Error('Server error'))
    const result = await store.deleteOrder('ORD-001')
    expect(result.success).toBe(false)
    expect(store.error).toBe('Server error')
  })

  it('clearAllOrders clears orders on success', async () => {
    ;(ordersApi.getOrders as any).mockResolvedValue({
      data: [{ id: 1 }],
    })
    await store.fetchOrders()
    expect(store.orders.length).toBe(1)
    ;(ordersApi.clearAllOrders as any).mockResolvedValue({ success: true })
    const result = await store.clearAllOrders()
    expect(result.success).toBe(true)
    expect(store.orders).toEqual([])
  })

  it('clearAllOrders handles failure', async () => {
    ;(ordersApi.clearAllOrders as any).mockResolvedValue({
      success: false,
      message: 'Cannot clear',
    })
    const result = await store.clearAllOrders()
    expect(result.success).toBe(false)
    expect(store.error).toBe('Cannot clear')
  })

  it('clearAllOrders handles exception', async () => {
    ;(ordersApi.clearAllOrders as any).mockRejectedValue(new Error('Server error'))
    const result = await store.clearAllOrders()
    expect(result.success).toBe(false)
    expect(store.error).toBe('Server error')
  })

  it('discards an older read when a newer search has completed', async () => {
    let finishOlder!: (value: unknown) => void
    ;(ordersApi.getOrders as any).mockImplementation(() => new Promise((resolve) => { finishOlder = resolve }))
    const older = store.fetchOrders()
    ;(ordersApi.searchOrders as any).mockResolvedValue({ success: true, data: [{ id: 2, order_number: 'NEW' }] })
    expect((await store.searchOrders('NEW')).success).toBe(true)
    finishOlder({ success: true, data: [{ id: 1, order_number: 'OLD' }] })
    expect(await older).toMatchObject({ success: false, stale: true })
    expect(store.orders.map((order) => order.order_number)).toEqual(['NEW'])
    expect(store.loading).toBe(false)
  })

  it('does not restore cleared orders from a response started before deletion', async () => {
    let finishOlder!: (value: unknown) => void
    ;(ordersApi.getOrders as any).mockImplementation(() => new Promise((resolve) => { finishOlder = resolve }))
    const older = store.fetchOrders()
    ;(ordersApi.clearAllOrders as any).mockResolvedValue({ success: true })
    expect((await store.clearAllOrders()).success).toBe(true)
    finishOlder({ success: true, data: [{ id: 1, order_number: 'REMOVED' }] })
    expect(await older).toMatchObject({ stale: true })
    expect(store.orders).toEqual([])
  })

  it('rejects a nested facade failure without replacing the last good list', async () => {
    vi.mocked(ordersApi.getOrders).mockResolvedValue({ success: true, data: [{ id: 1 }] } as never)
    await store.fetchOrders()
    vi.mocked(ordersApi.getOrders).mockResolvedValue({
      success: true, data: { success: false, message: '内层错误', data: [] },
    } as never)
    expect(await store.fetchOrders()).toMatchObject({ success: false, message: '内层错误' })
    expect(store.orders).toEqual([{ id: 1 }])
  })

  it('does not treat malformed response data as an empty successful list', async () => {
    vi.mocked(ordersApi.getOrders).mockResolvedValue({ success: true, data: { unexpected: 1 } } as never)
    expect(await store.fetchOrders()).toMatchObject({ success: false })
    expect(store.error).toBe('加载订单失败')
  })

  it('holds mutation ownership against concurrent reads and mutations', async () => {
    let finish!: (value: { success: boolean }) => void
    vi.mocked(ordersApi.clearAllOrders).mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const clearing = store.clearAllOrders()
    expect(store.loading).toBe(true)
    expect(await store.searchOrders('during-clear')).toMatchObject({ stale: true })
    expect(ordersApi.searchOrders).not.toHaveBeenCalled()
    expect(await store.deleteOrder('ORD-1')).toMatchObject({ success: false })
    expect(ordersApi.deleteOrder).not.toHaveBeenCalled()
    expect(store.loading).toBe(true)
    finish({ success: true })
    expect(await clearing).toMatchObject({ success: true })
    expect(store.loading).toBe(false)
  })

  it('updates the same order identity by order number or numeric ID', async () => {
    vi.mocked(ordersApi.getOrders).mockResolvedValue({ success: true, data: [
      { id: 1, order_number: 'ORD-001', status: 'pending' },
    ] } as never)
    await store.fetchOrders()
    vi.mocked(ordersApi.updateOrder).mockResolvedValue({ success: true, data: { status: 'completed' } } as never)
    expect(await store.updateOrder('ORD-001', {})).toMatchObject({ success: true })
    expect(store.orders[0].status).toBe('completed')
    vi.mocked(ordersApi.deleteOrder).mockResolvedValue({ success: true })
    await store.deleteOrder('1')
    expect(store.orders).toEqual([])
  })

  it('clears old account state and rejects old receipts without affecting a new account mutation', async () => {
    vi.mocked(ordersApi.getOrders).mockResolvedValue({ success: true, data: [{ id: 1 }] } as never)
    await store.fetchOrders()
    let finishOld!: (value: { success: boolean }) => void
    vi.mocked(ordersApi.clearAllOrders).mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve }))
    const old = store.clearAllOrders()
    productReadAccountEpoch.value++
    expect(store.orders).toEqual([])
    expect(store.loading).toBe(false)
    let finishNew!: (value: { success: boolean }) => void
    vi.mocked(ordersApi.clearAllOrders).mockImplementationOnce(() => new Promise(resolve => { finishNew = resolve }))
    const next = store.clearAllOrders()
    finishOld({ success: true })
    expect(await old).toMatchObject({ stale: true })
    expect(store.loading).toBe(true)
    finishNew({ success: true })
    expect(await next).toMatchObject({ success: true })
    expect(store.loading).toBe(false)
  })

  it('orderCount computed returns correct count', async () => {
    ;(ordersApi.getOrders as any).mockResolvedValue({
      data: [{ id: 1 }, { id: 2 }, { id: 3 }],
    })
    await store.fetchOrders()
    expect(store.orderCount).toBe(3)
  })
})
