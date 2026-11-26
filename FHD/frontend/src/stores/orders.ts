import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import ordersApi from '../api/orders'
import type { Order } from '@/types/order'
import { asRecord } from '@/utils/typeGuards'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'

interface OperationResult {
  success: boolean
  data?: unknown
  message?: string
  stale?: boolean
}

type OrderListResult = { success: true; rows: Order[] } | { success: false; message?: string }

// Keep the host and legacy MOD envelopes at the boundary, not in page state.
// A nested failure or an invalid envelope must never become a successful empty list.
function normalizeOrders(data: unknown, depth = 0): OrderListResult {
  if (depth > 4) return { success: false }
  if (Array.isArray(data)) return { success: true, rows: data as Order[] }
  const row = asRecord(data)
  if (row.success === false) return { success: false, message: typeof row.message === 'string' ? row.message : undefined }
  if (Array.isArray(row.data)) return { success: true, rows: row.data as Order[] }
  if (Array.isArray(row.orders)) return { success: true, rows: row.orders as Order[] }
  if (row.data && typeof row.data === 'object') return normalizeOrders(row.data, depth + 1)
  return { success: false }
}

function matchesOrder(order: Order, number: string): boolean {
  return String(order.order_number ?? '') === number || String(order.id ?? '') === number
}

const staleResult = (): OperationResult => ({ success: false, stale: true })

export const useOrdersStore = defineStore('orders', () => {
  const orders = ref<Order[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const orderCount = computed(() => orders.value.length)

  let readRevision = 0
  let mutating = false
  watch(productReadAccountEpoch, () => {
    ++readRevision
    mutating = false
    orders.value = []
    error.value = null
    loading.value = false
  }, { flush: 'sync' })

  async function readOrders(request: () => Promise<unknown>, fallback: string): Promise<OperationResult> {
    if (mutating) return staleResult()
    const revision = ++readRevision
    const epoch = productReadAccountEpoch.value
    const current = () => revision === readRevision && epoch === productReadAccountEpoch.value
    loading.value = true
    error.value = null
    try {
      const data = await request()
      if (!current()) return staleResult()
      const normalized = normalizeOrders(data)
      if (!normalized.success) {
        error.value = normalized.message || fallback
        return { success: false, message: error.value }
      }
      orders.value = normalized.rows
      return { success: true }
    } catch (e) {
      if (!current()) return staleResult()
      error.value = e instanceof Error ? e.message : fallback
      console.error(fallback, e)
      return { success: false, message: error.value }
    } finally {
      if (current()) loading.value = false
    }
  }

  function fetchOrders(params: Record<string, unknown> = {}): Promise<OperationResult> {
    return readOrders(() => ordersApi.getOrders(params), '加载订单失败')
  }

  function searchOrders(keyword: string): Promise<OperationResult> {
    return readOrders(() => ordersApi.searchOrders(keyword), '搜索订单失败')
  }

  // One mutation owns loading and the authoritative list until its receipt arrives.
  // Reads cannot resurrect pre-write snapshots or clear a newer operation's loading state.
  async function mutate(
    request: () => Promise<{ success: boolean; message?: string; data?: unknown }>,
    fallback: string,
    apply: (data: unknown) => OperationResult,
  ): Promise<OperationResult> {
    if (mutating) return { success: false, message: '正在处理订单，请稍候' }
    const epoch = productReadAccountEpoch.value
    const current = () => epoch === productReadAccountEpoch.value
    ++readRevision
    mutating = true
    loading.value = true
    error.value = null
    try {
      const response = await request()
      if (!current()) return staleResult()
      if (!response?.success) {
        error.value = response?.message || fallback
        return { success: false, message: error.value }
      }
      return apply(response.data)
    } catch (e) {
      if (!current()) return staleResult()
      error.value = e instanceof Error ? e.message : fallback
      return { success: false, message: error.value }
    } finally {
      if (current()) {
        mutating = false
        loading.value = false
      }
    }
  }

  function deleteOrder(orderNumber: string): Promise<OperationResult> {
    return mutate(() => ordersApi.deleteOrder(orderNumber), '删除失败', () => {
      orders.value = orders.value.filter(order => !matchesOrder(order, orderNumber))
      return { success: true }
    })
  }

  function updateOrder(orderNumber: string, payload: Record<string, unknown>): Promise<OperationResult> {
    return mutate(() => ordersApi.updateOrder(orderNumber, payload), '更新失败', data => {
      const updated = asRecord(data) as unknown as Order
      orders.value = orders.value.map(order => matchesOrder(order, orderNumber) ? { ...order, ...updated } : order)
      return { success: true, data: updated }
    })
  }

  function clearAllOrders(): Promise<OperationResult> {
    return mutate(() => ordersApi.clearAllOrders(), '清空失败', () => {
      orders.value = []
      return { success: true }
    })
  }

  return { orders, loading, error, orderCount, fetchOrders, searchOrders, updateOrder, deleteOrder, clearAllOrders }
})
