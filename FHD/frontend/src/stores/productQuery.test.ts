import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const getProducts = vi.fn()
const updateProduct = vi.fn()
const exportUnitProductsXlsx = vi.fn()

vi.mock('@/api/products', () => ({
  productsApi: {
    getProducts: (...a: unknown[]) => getProducts(...a),
    updateProduct: (...a: unknown[]) => updateProduct(...a),
    exportUnitProductsXlsx: (...a: unknown[]) => exportUnitProductsXlsx(...a),
  },
}))

import { useProductQueryStore } from './productQuery'

const sample = [
  { id: 1, name: 'Alpha', model: 'A1', code: 'C1', companyId: 10, companyName: '甲公司' },
  { id: 2, name: 'Beta', model: 'B2', code: 'C2', companyId: 20 },
]

describe('productQuery store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    getProducts.mockReset()
    updateProduct.mockReset()
    exportUnitProductsXlsx.mockReset()
  })

  it('loadCompanies builds unique companies', async () => {
    getProducts.mockResolvedValue({ data: sample })
    const s = useProductQueryStore()
    await s.loadCompanies()
    expect(s.products).toHaveLength(2)
    expect(s.companies.map((c) => c.name)).toContain('甲公司')
    expect(s.companies.find((c) => c.id === 20)?.name).toBe('公司20')
    expect(s.loading).toBe(false)
  })

  it('loadCompanies records error on failure', async () => {
    getProducts.mockRejectedValue(new Error('boom'))
    const s = useProductQueryStore()
    await s.loadCompanies()
    expect(s.error).toBe('boom')
  })

  it('loadProducts filters by company', async () => {
    getProducts.mockResolvedValue({ data: sample })
    const s = useProductQueryStore()
    await s.loadProducts(10)
    expect(s.products).toHaveLength(1)
    expect(s.products[0].id).toBe(1)
  })

  it('loadAllProducts populates companies', async () => {
    getProducts.mockResolvedValue({ data: sample })
    const s = useProductQueryStore()
    await s.loadAllProducts()
    expect(s.companies).toHaveLength(2)
  })

  it('filteredProducts respects search query', async () => {
    getProducts.mockResolvedValue({ data: sample })
    const s = useProductQueryStore()
    await s.loadAllProducts()
    expect(s.filteredProducts).toHaveLength(2)
    s.searchProducts('alpha')
    expect(s.filteredProducts).toHaveLength(1)
    s.searchProducts('c2')
    expect(s.filteredProducts[0].id).toBe(2)
  })

  it('companyProducts filters by id', async () => {
    getProducts.mockResolvedValue({ data: sample })
    const s = useProductQueryStore()
    await s.loadAllProducts()
    expect(s.companyProducts(20)).toHaveLength(1)
  })

  it('selectCompany triggers product load and clears product', async () => {
    getProducts.mockResolvedValue({ data: sample })
    const s = useProductQueryStore()
    s.selectProduct(sample[0])
    s.selectCompany({ id: 10, name: '甲公司' })
    expect(s.selectedCompany?.id).toBe(10)
    expect(s.selectedProduct).toBeNull()
  })

  it('updateProduct merges local row', async () => {
    getProducts.mockResolvedValue({ data: sample })
    updateProduct.mockResolvedValue({})
    const s = useProductQueryStore()
    await s.loadAllProducts()
    await s.updateProduct(1, { name: 'Alpha2' } as never)
    expect(s.products.find((p) => p.id === 1)?.name).toBe('Alpha2')
  })

  it('updateProduct rethrows and records error', async () => {
    updateProduct.mockRejectedValue(new Error('upd fail'))
    const s = useProductQueryStore()
    await expect(s.updateProduct(1, {} as never)).rejects.toThrow('upd fail')
    expect(s.error).toBe('upd fail')
  })

  it('exportProducts passes companyId param', async () => {
    exportUnitProductsXlsx.mockResolvedValue({})
    const s = useProductQueryStore()
    await s.exportProducts(10)
    expect(exportUnitProductsXlsx).toHaveBeenCalledWith({ companyId: 10 })
    await s.exportProducts()
    expect(exportUnitProductsXlsx).toHaveBeenLastCalledWith({})
  })

  it('exportProducts rethrows on failure', async () => {
    exportUnitProductsXlsx.mockRejectedValue(new Error('exp fail'))
    const s = useProductQueryStore()
    await expect(s.exportProducts()).rejects.toThrow('exp fail')
  })

  it('reset clears all state', async () => {
    getProducts.mockResolvedValue({ data: sample })
    const s = useProductQueryStore()
    await s.loadAllProducts()
    s.reset()
    expect(s.products).toHaveLength(0)
    expect(s.companies).toHaveLength(0)
    expect(s.searchQuery).toBe('')
  })
})
