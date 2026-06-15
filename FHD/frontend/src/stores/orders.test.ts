import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useOrdersStore } from '@/stores/orders'

vi.mock('@/api/orders', () => ({
  default: {
    getOrders: vi.fn(),
    searchOrders: vi.fn(),
    deleteOrder: vi.fn(),
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
    ;(ordersApi.getOrders as any).mockImplementation(() => new Promise(r => { resolvePromise = r }))
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

  it('orderCount computed returns correct count', async () => {
    ;(ordersApi.getOrders as any).mockResolvedValue({
      data: [{ id: 1 }, { id: 2 }, { id: 3 }],
    })
    await store.fetchOrders()
    expect(store.orderCount).toBe(3)
  })
})
