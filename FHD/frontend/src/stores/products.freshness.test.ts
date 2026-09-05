import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useProductsStore } from './products'
import { updateProductReadAccountScope } from '@/utils/productReadAccountScope'
import { useModsStore } from './mods'

const api = vi.hoisted(() => ({ getProducts: vi.fn(), updateProduct: vi.fn() }))
vi.mock('../api/products', () => ({ default: api }))
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (error: Error) => void; const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
const result = (price: number) => ({ success: true, data: [{ id: 1, name: '产品', price }], total: 1 })
beforeEach(() => { setActivePinia(createPinia()); vi.clearAllMocks(); updateProductReadAccountScope({ tenantId: 1, marketUserId: 11 }) })

describe('product read ownership', () => {
  it('retired reads cannot return stale data for the view to write back or overwrite the latest price', async () => {
    const old = deferred<ReturnType<typeof result>>()
    api.getProducts.mockReturnValueOnce(old.promise).mockResolvedValueOnce(result(109))
    const store = useProductsStore()
    const first = store.fetchProducts()
    store.invalidateProducts()
    await store.fetchProducts()
    old.resolve(result(99))
    expect(await first).toEqual({ success: false, stale: true })
    expect(store.products[0].price).toBe(109)
    expect(store.canEditProducts).toBe(true)
  })

  it('a late failure does not replace a newer request error or stop its loading indicator', async () => {
    const old = deferred<ReturnType<typeof result>>(); const latest = deferred<ReturnType<typeof result>>()
    api.getProducts.mockReturnValueOnce(old.promise).mockReturnValueOnce(latest.promise)
    const store = useProductsStore(); const first = store.fetchProducts(); const second = store.fetchProducts()
    old.reject(new Error('old failure'))
    await first
    expect(store.loading).toBe(true); expect(store.error).toBeNull()
    latest.reject(new Error('current failure')); await second
    expect(store.error).toBe('current failure'); expect(store.loading).toBe(false); expect(store.canEditProducts).toBe(false)
  })

  it.each(['resolve', 'reject'] as const)('A → B → A retires the first A request even when it later %s', async mode => {
    const old = deferred<ReturnType<typeof result>>()
    api.getProducts.mockResolvedValueOnce(result(99)).mockReturnValueOnce(old.promise).mockResolvedValueOnce(result(109))
    const store = useProductsStore(); await store.fetchProducts(); const pending = store.fetchProducts()
    const originalScope = store.captureProductsScope()
    updateProductReadAccountScope({ tenantId: 2, marketUserId: 22 })
    expect(store.products).toEqual([]); expect(store.error).toBeNull(); expect(store.fresh).toBe(false)
    updateProductReadAccountScope({ tenantId: 1, marketUserId: 11 })
    await store.fetchProducts()
    if (mode === 'resolve') old.resolve(result(99)); else old.reject(new Error('old A error'))
    expect(await pending).toEqual({ success: false, stale: true })
    expect(store.invalidateProducts(originalScope)).toBe(false)
    expect(store.products[0].price).toBe(109); expect(store.error).toBeNull(); expect(store.fresh).toBe(true)
  })

  it('changing the ERP source clears rows and rejects the previous source response', async () => {
    const old = deferred<ReturnType<typeof result>>()
    api.getProducts.mockReturnValueOnce(old.promise).mockResolvedValueOnce(result(88))
    const store = useProductsStore(); const pending = store.fetchProducts()
    useModsStore().setActiveModId('taiyangniao-pro')
    expect(store.products).toEqual([])
    await store.fetchProducts()
    old.resolve(result(99)); await pending
    expect(store.products[0].price).toBe(88)
  })

  it('successful editing retires older reads and refetches the same filter before allowing another edit', async () => {
    const old = deferred<ReturnType<typeof result>>()
    api.getProducts.mockReturnValueOnce(old.promise).mockResolvedValueOnce(result(109))
    api.updateProduct.mockResolvedValue({ success: true })
    const store = useProductsStore(); const pending = store.fetchProducts({ keyword: 'PM90', unit: '客户甲' })
    expect(await store.updateProduct(1, { price: 109 })).toEqual({ success: true })
    old.resolve(result(99)); await pending
    expect(api.getProducts).toHaveBeenLastCalledWith({ keyword: 'PM90', unit: '客户甲' })
    expect(store.products[0].price).toBe(109); expect(store.canEditProducts).toBe(true)
  })

  it('a successful edit with a failed read remains successful business work but cannot be edited from a stale row', async () => {
    api.getProducts.mockResolvedValueOnce(result(99)).mockRejectedValueOnce(new Error('read unavailable'))
    api.updateProduct.mockResolvedValue({ success: true })
    const store = useProductsStore(); await store.fetchProducts()
    expect(await store.updateProduct(1, { price: 109 })).toEqual({ success: true })
    expect(store.products[0].price).toBe(99); expect(store.error).toBe('read unavailable'); expect(store.canEditProducts).toBe(false)
  })
})
