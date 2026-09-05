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
    const result = await options.store.fetchProducts({ ...options.query(), page: options.page.value }, { append: !reset })
    if (id !== options.requestId.value) return
    if (result?.success) { options.hasMore.value = false; options.page.value++ }
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
