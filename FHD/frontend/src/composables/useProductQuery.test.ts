import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useProductQuery } from '@/composables/useProductQuery'

// Mock the store
const mockStore = {
  loading: false,
  error: null as string | null,
  companies: [{ id: 1, name: 'Company A' }],
  products: [{ id: 1, name: 'Product A', company_id: 1 }],
  selectedCompany: null as any,
  selectedProduct: null as any,
  searchQuery: '',
  filteredProducts: [{ id: 1, name: 'Product A', company_id: 1 }],
  loadCompanies: vi.fn().mockResolvedValue(undefined),
  loadProducts: vi.fn().mockResolvedValue(undefined),
  loadAllProducts: vi.fn().mockResolvedValue(undefined),
  selectCompany: vi.fn(),
  selectProduct: vi.fn(),
  searchProducts: vi.fn(),
  updateProduct: vi.fn().mockResolvedValue(undefined),
  exportProducts: vi.fn().mockResolvedValue(undefined),
  companyProducts: vi.fn().mockReturnValue([]),
  reset: vi.fn(),
}

vi.mock('@/stores/productQuery', () => ({
  useProductQueryStore: () => mockStore,
}))

describe('useProductQuery', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockStore.loading = false
    mockStore.error = null
    mockStore.selectedCompany = null
    mockStore.selectedProduct = null
  })

  it('exposes loading computed', () => {
    const pq = useProductQuery() as any
    expect(pq.loading).toBeDefined()
  })

  it('exposes error computed', () => {
    const pq = useProductQuery() as any
    expect(pq.error).toBeDefined()
  })

  it('exposes companies computed', () => {
    const pq = useProductQuery() as any
    expect(pq.companies).toBeDefined()
  })

  it('exposes products computed', () => {
    const pq = useProductQuery() as any
    expect(pq.products).toBeDefined()
  })

  it('exposes selectedCompany computed', () => {
    const pq = useProductQuery() as any
    expect(pq.selectedCompany).toBeDefined()
  })

  it('exposes selectedProduct computed', () => {
    const pq = useProductQuery() as any
    expect(pq.selectedProduct).toBeDefined()
  })

  it('exposes searchQuery computed', () => {
    const pq = useProductQuery() as any
    expect(pq.searchQuery).toBeDefined()
  })

  it('exposes filteredProducts computed', () => {
    const pq = useProductQuery() as any
    expect(pq.filteredProducts).toBeDefined()
  })

  it('loadCompanies delegates to store', async () => {
    const pq = useProductQuery() as any
    await pq.loadCompanies()
    expect(mockStore.loadCompanies).toHaveBeenCalled()
  })

  it('loadProducts delegates to store with companyId', async () => {
    const pq = useProductQuery() as any
    await pq.loadProducts(1)
    expect(mockStore.loadProducts).toHaveBeenCalledWith(1)
  })

  it('loadAllProducts delegates to store', async () => {
    const pq = useProductQuery() as any
    await pq.loadAllProducts()
    expect(mockStore.loadAllProducts).toHaveBeenCalled()
  })

  it('selectCompany delegates to store', () => {
    const pq = useProductQuery() as any
    const company = { id: 1, name: 'Test' }
    pq.selectCompany(company)
    expect(mockStore.selectCompany).toHaveBeenCalledWith(company)
  })

  it('selectProduct delegates to store', () => {
    const pq = useProductQuery() as any
    const product = { id: 1, name: 'Test Product' }
    pq.selectProduct(product)
    expect(mockStore.selectProduct).toHaveBeenCalledWith(product)
  })

  it('searchProducts delegates to store', () => {
    const pq = useProductQuery() as any
    pq.searchProducts('test query')
    expect(mockStore.searchProducts).toHaveBeenCalledWith('test query')
  })

  it('updateProduct delegates to store', async () => {
    const pq = useProductQuery() as any
    await pq.updateProduct(1, { name: 'Updated' })
    expect(mockStore.updateProduct).toHaveBeenCalledWith(1, { name: 'Updated' })
  })

  it('exportProducts delegates to store', async () => {
    const pq = useProductQuery() as any
    await pq.exportProducts(1)
    expect(mockStore.exportProducts).toHaveBeenCalledWith(1)
  })

  it('exportProducts defaults to null companyId', async () => {
    const pq = useProductQuery() as any
    await pq.exportProducts()
    expect(mockStore.exportProducts).toHaveBeenCalledWith(null)
  })

  it('getCompanyProducts delegates to store', () => {
    const pq = useProductQuery() as any
    pq.getCompanyProducts(1)
    expect(mockStore.companyProducts).toHaveBeenCalledWith(1)
  })

  it('reset delegates to store', () => {
    const pq = useProductQuery() as any
    pq.reset()
    expect(mockStore.reset).toHaveBeenCalled()
  })
})
