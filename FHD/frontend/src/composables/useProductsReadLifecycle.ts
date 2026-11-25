import { onActivated, onBeforeUnmount, onDeactivated, onMounted, watch, type Ref } from 'vue'
import type { useProductsStore } from '@/stores/products'
import type { ProductQueryParams } from '@/types/product'
import customersApi from '@/api/customers'

export function useProductsReadLifecycle(options: {
  store: ReturnType<typeof useProductsStore>
  loadProducts: () => Promise<void>
  loadUnits: () => Promise<void>
  resetScope: () => void
  invalidateEditing: () => void
}): { refreshProducts: () => void } {
  let active = false
  const refreshProducts = () => {
    void options.loadUnits()
    void options.loadProducts()
  }
  function activate(): void {
    if (active) return
    active = true
    options.invalidateEditing()
    options.store.syncReadScope()
    refreshProducts()
  }
  onMounted(activate)
  onActivated(activate)
  onDeactivated(() => { active = false })
  onBeforeUnmount(() => { active = false })
  watch(() => options.store.scopeEpoch, options.resetScope, { flush: 'sync' })
  watch(() => options.store.invalidationVersion, options.invalidateEditing, { flush: 'sync' })
  watch(() => [options.store.invalidationVersion, options.store.mutating], () => {
    if (active && !options.store.mutating && !options.store.fresh) refreshProducts()
  })
  return { refreshProducts }
}

export function createProductListLoader(options: {
  store: ReturnType<typeof useProductsStore>
  query: () => ProductQueryParams
  page: Ref<number>
  hasMore: Ref<boolean>
  requestId: Ref<number>
}) {
  return async (reset = true): Promise<void> => {
    const id = ++options.requestId.value
    if (reset) { options.page.value = 1; options.hasMore.value = false }
    const query = options.query()
    const requestedPage = options.page.value
    const result = await options.store.fetchProducts({ ...query, page: requestedPage }, { append: !reset })
    if (id !== options.requestId.value) return
    if (result?.success) {
      const batchSize = Array.isArray(result.data) ? result.data.length : 0
      const pageSize = Math.max(1, Number(query.per_page) || 100)
      const total = Number(result.total) || 0
      options.hasMore.value = total > 0 ? requestedPage * pageSize < total : batchSize >= pageSize
      options.page.value = requestedPage + 1
    }
  }
}

export function createProductUnitsLoader(store: ReturnType<typeof useProductsStore>, units: Ref<string[]>) {
  return async (): Promise<void> => {
    const scope = store.captureProductsScope()
    try {
      const response = await customersApi.getCustomers({ page: 1, per_page: 1000 })
      if (!store.isProductsScopeCurrent(scope)) return
      if (!response?.success) throw new Error(response?.message || '加载客户/购买单位失败')
      const rows = response.data || []
      units.value = Array.isArray(rows) ? rows.map(row => {
        const name = ('unit_name' in row ? row.unit_name : null) || ('customer_name' in row ? row.customer_name : null) || row.name
        return typeof name === 'string' ? name : ''
      }).filter(Boolean) : []
    } catch (error) {
      if (!store.isProductsScopeCurrent(scope)) return
      console.error('加载产品单位失败:', error)
      units.value = []
    }
  }
}
