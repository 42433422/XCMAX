import { defineStore } from 'pinia'
import { ref, computed, watch, type Ref } from 'vue'
import productsApi from '../api/products'
import type { Product, ProductCreateDTO, ProductUpdateDTO, ProductQueryParams } from '@/types/product'
import { resolveTenantStorageScopeFromRuntime } from '@/utils/tenantStorageScope'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { getApiBase } from '@/utils/apiBase'
import { resolveErpApiBase } from '@/utils/erpDomainPaths'
import { useModsStore } from './mods'

interface OperationResult {
  success: boolean
  data?: unknown
  message?: string
  total?: number
  stale?: boolean
}
export interface ProductReadScope { key: string; epoch: number }

export const useProductsStore = defineStore('products', () => {
  const products = ref<Product[]>([]) as Ref<Product[]>
  const loading = ref(false)
  const mutating = ref(false)
  const error = ref<string | null>(null)
  const units = ref<unknown[]>([])
  const fresh = ref(false)
  const invalidationVersion = ref(0)
  const scopeEpoch = ref(0)
  let activeRead = 0
  let readSequence = 0
  let lastQuery: ProductQueryParams = {}
  const mods = useModsStore()
  function currentScopeKey(): string {
    return JSON.stringify([productReadAccountEpoch.value, resolveTenantStorageScopeFromRuntime(true),
      getApiBase(), mods.activeModId, resolveErpApiBase()])
  }
  let scopeKey = currentScopeKey()
  const productCount = computed(() => products.value.length)
  const canEditProducts = computed(() => fresh.value && !loading.value && !mutating.value)

  function retireReads(): void {
    readSequence++
    activeRead = 0
    fresh.value = false
    loading.value = false
  }
  function syncReadScope(): void {
    const key = currentScopeKey()
    if (key === scopeKey) return
    scopeKey = key
    retireReads()
    products.value = []; units.value = []; error.value = null; lastQuery = {}
    mutating.value = false
    scopeEpoch.value++
    invalidationVersion.value++
  }
  watch(currentScopeKey, syncReadScope, { flush: 'sync' })
  function captureProductsScope(): ProductReadScope {
    syncReadScope()
    return { key: scopeKey, epoch: scopeEpoch.value }
  }
  function isProductsScopeCurrent(scope: ProductReadScope): boolean {
    return scope.key === currentScopeKey() && scope.key === scopeKey && scope.epoch === scopeEpoch.value
  }
  function invalidateProducts(scope = captureProductsScope()): boolean {
    if (!isProductsScopeCurrent(scope)) return false
    retireReads()
    invalidationVersion.value++
    return true
  }
  const staleResult = (): OperationResult => ({ success: false, stale: true })

  async function fetchProducts(params: ProductQueryParams = {}, options: { append?: boolean } = {}): Promise<OperationResult> {
    const scope = captureProductsScope()
    const sequence = ++readSequence
    activeRead = sequence
    lastQuery = { ...params }
    loading.value = true; fresh.value = false; error.value = null
    const current = () => isProductsScopeCurrent(scope) && sequence === readSequence
    try {
      const data = await productsApi.getProducts(params)
      if (!current()) return staleResult()
      if (data.success) {
        products.value = options.append ? [...products.value, ...(data.data || [])] : data.data || []
        fresh.value = true
        return { success: true, data: data.data, total: data.total || 0 }
      }
      error.value = data.message || '加载产品失败'
      return { success: false, message: error.value }
    } catch (e) {
      if (!current()) return staleResult()
      error.value = e instanceof Error ? e.message : '加载产品失败'
      return { success: false, message: error.value }
    } finally {
      if (current()) { activeRead = 0; loading.value = mutating.value }
    }
  }

  async function mutate(
    request: () => Promise<{ success: boolean; message?: string }>,
    failure: string,
    onSuccess: () => Promise<void> | void,
  ): Promise<OperationResult> {
    const scope = captureProductsScope()
    if (mutating.value) return { success: false, message: '正在保存产品，请稍候' }
    retireReads()
    mutating.value = true; loading.value = true; error.value = null
    try {
      const data = await request()
      if (!isProductsScopeCurrent(scope)) return staleResult()
      // A completed request may have changed data even when its response reports a partial failure.
      invalidateProducts(scope)
      if (data.success) {
        await onSuccess()
        return isProductsScopeCurrent(scope) ? { success: true } : staleResult()
      }
      error.value = data.message || failure
      return { success: false, message: error.value }
    } catch (e) {
      if (!isProductsScopeCurrent(scope)) return staleResult()
      invalidateProducts(scope)
      error.value = e instanceof Error ? e.message : failure
      return { success: false, message: error.value }
    } finally {
      if (isProductsScopeCurrent(scope)) { mutating.value = false; loading.value = activeRead !== 0 }
    }
  }
  async function reloadLastQuery(): Promise<void> { await fetchProducts(lastQuery) }
  function createProduct(data: ProductCreateDTO): Promise<OperationResult> {
    return mutate(() => productsApi.createProduct(data), '创建产品失败', reloadLastQuery)
  }
  function updateProduct(id: number, data: ProductUpdateDTO): Promise<OperationResult> {
    return mutate(() => productsApi.updateProduct(id, data), '更新产品失败', reloadLastQuery)
  }
  function deleteProduct(id: number): Promise<OperationResult> {
    return mutate(() => productsApi.deleteProduct(id), '删除产品失败', () => { products.value = products.value.filter(p => p.id !== id) })
  }
  function batchDelete(ids: (number | string)[]): Promise<OperationResult> {
    return mutate(() => productsApi.batchDeleteProducts(ids), '批量删除失败', () => { products.value = products.value.filter(p => !ids.includes(p.id)) })
  }
  return {
    products, loading, mutating, error, units, productCount, fresh, canEditProducts, invalidationVersion, scopeEpoch,
    fetchProducts, createProduct, updateProduct, deleteProduct, batchDelete,
    captureProductsScope, isProductsScopeCurrent, invalidateProducts, syncReadScope,
  }
})
