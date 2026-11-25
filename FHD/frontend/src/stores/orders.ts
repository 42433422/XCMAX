import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import ordersApi from '../api/orders'
import type { Order } from '@/types/order'
import { asRecord } from '@/utils/typeGuards'

interface OperationResult {
  success: boolean
  data?: unknown
  message?: string
  stale?: boolean
}

export const useOrdersStore = defineStore('orders', () => {
  const orders = ref<Order[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  const orderCount = computed(() => orders.value.length)

  function normalizeOrders(data: unknown, depth = 0): Order[] {
    if (depth > 4) return []
    if (Array.isArray(data)) return data as Order[]
    const row = asRecord(data)
    if (Array.isArray(row.data)) return row.data as Order[]
    if (Array.isArray(row.orders)) return row.orders as Order[]
    // The ERP Mod facade retains its envelope around the host response:
    // { success, data: { success, data: [...] } }.  Normalize both the host
    // and facade contracts so the desktop page does not render an empty table
    // while the same record is already present in the database.
    if (row.data && typeof row.data === 'object') {
      return normalizeOrders(row.data, depth + 1)
    }
    return []
  }

  // The latest read alone may update state; slow filter responses are never authoritative.
  let readRevision = 0
  async function readOrders(request: () => Promise<unknown>, fallback: string): Promise<OperationResult> {
    const revision = ++readRevision
    loading.value = true
    error.value = null
    try {
      const data = await request()
      if (revision !== readRevision) return { success: false, stale: true }
      const response = asRecord(data)
      if (response.success === false) {
        error.value = String(response.message || fallback)
        return { success: false, message: error.value }
      }
      orders.value = normalizeOrders(data)
      return { success: true }
    } catch (e) {
      if (revision !== readRevision) return { success: false, stale: true }
      error.value = e instanceof Error ? e.message : fallback
      console.error(fallback, e)
      return { success: false, message: error.value }
    } finally {
      if (revision === readRevision) loading.value = false
    }
  }

  function fetchOrders(params: Record<string, unknown> = {}): Promise<OperationResult> {
    return readOrders(() => ordersApi.getOrders(params), '加载订单失败')
  }

  function searchOrders(keyword: string): Promise<OperationResult> {
    return readOrders(() => ordersApi.searchOrders(keyword), '搜索订单失败')
  }

  async function deleteOrder(orderNumber: string): Promise<OperationResult> {
    ++readRevision // a business mutation invalidates older reads
    loading.value = true
    error.value = null
    try {
      const data = await ordersApi.deleteOrder(orderNumber)
      if (!data?.success) {
        error.value = data?.message || '删除失败'
        return { success: false, message: error.value }
      }
      orders.value = orders.value.filter((o) => (o.order_number || o.id) !== orderNumber)
      return { success: true }
    } catch (e) {
      error.value = e instanceof Error ? e.message : '删除失败'
      console.error('删除订单失败:', e)
      return { success: false, message: error.value }
    } finally {
      loading.value = false
    }
  }

  async function updateOrder(orderNumber: string, payload: Record<string, unknown>): Promise<OperationResult> {
    ++readRevision // a business mutation invalidates older reads
    loading.value = true
    error.value = null
    try {
      const data = await ordersApi.updateOrder(orderNumber, payload)
      if (!data?.success) {
        error.value = data?.message || '更新失败'
        return { success: false, message: error.value }
      }
      const updated = asRecord(data.data) as unknown as Order
      orders.value = orders.value.map((order) =>
        String(order.id || order.order_number) === String(orderNumber) ? { ...order, ...updated } : order,
      )
      return { success: true, data: updated }
    } catch (e) {
      error.value = e instanceof Error ? e.message : '更新失败'
      return { success: false, message: error.value }
    } finally {
      loading.value = false
    }
  }

  async function clearAllOrders(): Promise<OperationResult> {
    ++readRevision // a business mutation invalidates older reads
    loading.value = true
    error.value = null
    try {
      const data = await ordersApi.clearAllOrders()
      if (!data?.success) {
        error.value = data?.message || '清空失败'
        return { success: false, message: error.value }
      }
      orders.value = []
      return { success: true }
    } catch (e) {
      error.value = e instanceof Error ? e.message : '清空失败'
      console.error('清空订单失败:', e)
      return { success: false, message: error.value }
    } finally {
      loading.value = false
    }
  }

  return {
    orders,
    loading,
    error,
    orderCount,
    fetchOrders,
    searchOrders,
    updateOrder,
    deleteOrder,
    clearAllOrders,
  }
})
