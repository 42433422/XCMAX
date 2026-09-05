import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { createEtlProductInvalidation } from '@/utils/etlProductInvalidation'
import { useProductsStore } from '@/stores/products'
import { updateProductReadAccountScope } from '@/utils/productReadAccountScope'
import type { EtlRun } from '@/api/etl'
const getProducts = vi.hoisted(() => vi.fn())
vi.mock('@/api/products', () => ({ default: { getProducts } }))
const fixture = () => ({ id: 'etl-one', target_type: 'products', status: 'completed', summary: { executed: 1 }, receipt: {}, executed_at: '2026-09-05T12:00:00Z' } as EtlRun)
beforeEach(() => {
  setActivePinia(createPinia()); updateProductReadAccountScope({ tenantId: 1, marketUserId: 11 })
  getProducts.mockResolvedValue({ success: true, data: [{ id: 1, price: 88 }] })
})
describe('ETL product invalidation ownership', () => {
  it('does not re-invalidate an unchanged completed snapshot, but does invalidate its rollback', async () => {
    const changes = createEtlProductInvalidation(); const store = useProductsStore(); const run = fixture()
    await changes.readMany(async () => [run]); await store.fetchProducts()
    await changes.read(async () => run)
    expect(store.fresh).toBe(true)
    await changes.read(async () => ({ ...run, rollback_status: 'completed', receipt: { rollback: { rows: 1 } } }))
    expect(store.fresh).toBe(false)
  })
  it.each(['read', 'mutate'] as const)('a late %s response from account A cannot invalidate account B’s fresh product snapshot', async action => {
    const changes = createEtlProductInvalidation(); const store = useProductsStore()
    let resolve!: (run: EtlRun) => void
    const response = new Promise<EtlRun>(yes => { resolve = yes })
    const pending = action === 'read' ? changes.read(() => response) : changes.mutate(fixture(), () => response)
    updateProductReadAccountScope({ tenantId: 2, marketUserId: 22 }); await store.fetchProducts()
    const revision = store.invalidationVersion
    resolve(fixture()); await pending
    expect(store.invalidationVersion).toBe(revision); expect(store.fresh).toBe(true); expect(store.products[0].price).toBe(88)
  })
  it('never promotes a failed operation to business success while retiring possibly stale prices', async () => {
    const changes = createEtlProductInvalidation(); const store = useProductsStore(); await store.fetchProducts()
    await expect(changes.mutate(fixture(), async () => { throw new Error('response lost after commit') })).rejects.toThrow('response lost after commit')
    expect(store.canEditProducts).toBe(false)
  })
  it('does not invalidate products for a file-only target', async () => {
    const changes = createEtlProductInvalidation(); const store = useProductsStore(); await store.fetchProducts()
    await changes.mutate({ ...fixture(), target_type: 'shipment_template' }, async () => fixture())
    expect(store.fresh).toBe(true)
  })
})
