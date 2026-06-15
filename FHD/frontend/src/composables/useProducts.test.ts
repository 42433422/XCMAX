import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref, nextTick } from 'vue'

vi.mock('../api/products', () => ({
  default: {
    getProducts: vi.fn(),
    createProduct: vi.fn(),
    updateProduct: vi.fn(),
    deleteProduct: vi.fn(),
    batchDeleteProducts: vi.fn(),
  },
}))

vi.mock('./useApi', () => ({
  useApi: vi.fn(() => ({
    data: ref(null),
    error: ref(null),
    loading: ref(false),
    execute: vi.fn(),
  })),
  useMutation: vi.fn(),
}))

import { useProducts, useProductDetail } from './useProducts'
import productsApi from '../api/products'

describe('useProducts', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns composable API', () => {
    const products = useProducts()
    expect(Array.isArray(products.products.value)).toBe(true)
    expect(products.loading.value).toBe(false)
    expect(products.error.value).toBeNull()
    expect(products.searchQuery.value).toBe('')
    expect(products.selectedUnit.value).toBe('')
    expect(typeof products.loadProducts).toBe('function')
    expect(typeof products.createProduct).toBe('function')
    expect(typeof products.updateProduct).toBe('function')
    expect(typeof products.deleteProduct).toBe('function')
    expect(typeof products.batchDeleteProducts).toBe('function')
    expect(typeof products.refreshProducts).toBe('function')
  })

  describe('filteredProducts', () => {
    it('returns all products when no search query', () => {
      const products = useProducts()
      products.products.value = [
        { id: 1, name: 'Product A', model_number: 'MA' },
        { id: 2, name: 'Product B', model_number: 'MB' },
      ] as any
      expect(products.filteredProducts.value).toHaveLength(2)
    })

    it('filters by name (case-insensitive)', () => {
      const products = useProducts()
      products.products.value = [
        { id: 1, name: 'Alpha Product', model_number: 'MA' },
        { id: 2, name: 'Beta Item', model_number: 'MB' },
      ] as any
      products.searchQuery.value = 'alpha'
      expect(products.filteredProducts.value).toHaveLength(1)
      expect(products.filteredProducts.value[0].name).toBe('Alpha Product')
    })

    it('filters by model_number (case-insensitive)', () => {
      const products = useProducts()
      products.products.value = [
        { id: 1, name: 'Product A', model_number: 'MA-100' },
        { id: 2, name: 'Product B', model_number: 'MB-200' },
      ] as any
      products.searchQuery.value = 'ma-100'
      expect(products.filteredProducts.value).toHaveLength(1)
    })

    it('returns empty when no match', () => {
      const products = useProducts()
      products.products.value = [
        { id: 1, name: 'Product A', model_number: 'MA' },
      ] as any
      products.searchQuery.value = 'nonexistent'
      expect(products.filteredProducts.value).toHaveLength(0)
    })

    it('handles products without name or model_number', () => {
      const products = useProducts()
      products.products.value = [
        { id: 1 } as any,
      ]
      products.searchQuery.value = 'test'
      expect(products.filteredProducts.value).toHaveLength(0)
    })
  })

  describe('loadProducts', () => {
    it('loads products successfully', async () => {
      vi.mocked(productsApi.getProducts).mockResolvedValueOnce({
        success: true,
        data: [{ id: 1, name: 'P1' }, { id: 2, name: 'P2' }],
      } as any)
      const products = useProducts()
      const result = await products.loadProducts()
      expect(products.products.value).toHaveLength(2)
      expect(products.loading.value).toBe(false)
      expect(result?.success).toBe(true)
    })

    it('sets loading state during request', async () => {
      let resolvePromise: (v: any) => void
      const promise = new Promise((resolve) => { resolvePromise = resolve })
      vi.mocked(productsApi.getProducts).mockReturnValueOnce(promise as any)
      const products = useProducts()
      const loadPromise = products.loadProducts()
      expect(products.loading.value).toBe(true)
      resolvePromise!({ success: true, data: [] })
      await loadPromise
      expect(products.loading.value).toBe(false)
    })

    it('handles API error', async () => {
      vi.mocked(productsApi.getProducts).mockRejectedValueOnce(new Error('Network error'))
      const products = useProducts()
      const result = await products.loadProducts()
      expect(result).toBeNull()
      expect(products.error.value).toBeInstanceOf(Error)
      expect(products.error.value?.message).toBe('Network error')
      expect(products.loading.value).toBe(false)
    })

    it('handles non-Error thrown value', async () => {
      vi.mocked(productsApi.getProducts).mockRejectedValueOnce('string error')
      const products = useProducts()
      await products.loadProducts()
      expect(products.error.value).toBeInstanceOf(Error)
    })

    it('passes selectedUnit and searchQuery to API', async () => {
      vi.mocked(productsApi.getProducts).mockResolvedValueOnce({
        success: true,
        data: [],
      } as any)
      const products = useProducts()
      products.selectedUnit.value = 'unit1'
      products.searchQuery.value = 'query1'
      await products.loadProducts()
      expect(productsApi.getProducts).toHaveBeenCalledWith(
        expect.objectContaining({ unit: 'unit1', search: 'query1' }),
      )
    })

    it('merges params with unit and search', async () => {
      vi.mocked(productsApi.getProducts).mockResolvedValueOnce({
        success: true,
        data: [],
      } as any)
      const products = useProducts()
      await products.loadProducts({ page: 2 })
      expect(productsApi.getProducts).toHaveBeenCalledWith(
        expect.objectContaining({ page: 2 }),
      )
    })

    it('does not update products when result is not successful', async () => {
      vi.mocked(productsApi.getProducts).mockResolvedValueOnce({
        success: false,
        data: null,
      } as any)
      const products = useProducts()
      await products.loadProducts()
      expect(products.products.value).toHaveLength(0)
    })
  })

  describe('createProduct', () => {
    it('creates product and reloads', async () => {
      vi.mocked(productsApi.createProduct).mockResolvedValueOnce({
        success: true,
        data: { id: 1, name: 'New Product' },
      } as any)
      vi.mocked(productsApi.getProducts).mockResolvedValueOnce({
        success: true,
        data: [],
      } as any)
      const products = useProducts()
      const result = await products.createProduct({ name: 'New Product' } as any)
      expect(result).toBeTruthy()
      expect(productsApi.createProduct).toHaveBeenCalledWith({ name: 'New Product' })
      expect(productsApi.getProducts).toHaveBeenCalled()
    })

    it('returns null on failure', async () => {
      vi.mocked(productsApi.createProduct).mockResolvedValueOnce({
        success: false,
        data: null,
      } as any)
      const products = useProducts()
      const result = await products.createProduct({ name: 'Fail' } as any)
      expect(result).toBeNull()
    })

    it('handles error', async () => {
      vi.mocked(productsApi.createProduct).mockRejectedValueOnce(new Error('Create error'))
      const products = useProducts()
      const result = await products.createProduct({ name: 'Error' } as any)
      expect(result).toBeNull()
      expect(products.error.value).toBeInstanceOf(Error)
    })
  })

  describe('updateProduct', () => {
    it('updates product and reloads', async () => {
      vi.mocked(productsApi.updateProduct).mockResolvedValueOnce({
        success: true,
        data: { id: 1, name: 'Updated' },
      } as any)
      vi.mocked(productsApi.getProducts).mockResolvedValueOnce({
        success: true,
        data: [],
      } as any)
      const products = useProducts()
      const result = await products.updateProduct(1, { name: 'Updated' } as any)
      expect(result).toBeTruthy()
    })

    it('returns null on failure', async () => {
      vi.mocked(productsApi.updateProduct).mockResolvedValueOnce({
        success: false,
        data: null,
      } as any)
      const products = useProducts()
      const result = await products.updateProduct(1, {} as any)
      expect(result).toBeNull()
    })

    it('handles error', async () => {
      vi.mocked(productsApi.updateProduct).mockRejectedValueOnce(new Error('Update error'))
      const products = useProducts()
      const result = await products.updateProduct(1, {} as any)
      expect(result).toBeNull()
    })
  })

  describe('deleteProduct', () => {
    it('deletes product and reloads', async () => {
      vi.mocked(productsApi.deleteProduct).mockResolvedValueOnce({ success: true } as any)
      vi.mocked(productsApi.getProducts).mockResolvedValueOnce({
        success: true,
        data: [],
      } as any)
      const products = useProducts()
      const result = await products.deleteProduct(1)
      expect(result).toBeUndefined()
    })

    it('returns null on error', async () => {
      vi.mocked(productsApi.deleteProduct).mockRejectedValueOnce(new Error('Delete error'))
      const products = useProducts()
      const result = await products.deleteProduct(1)
      expect(result).toBeNull()
    })

    it('passes extra data to API', async () => {
      vi.mocked(productsApi.deleteProduct).mockResolvedValueOnce({ success: true } as any)
      vi.mocked(productsApi.getProducts).mockResolvedValueOnce({
        success: true,
        data: [],
      } as any)
      const products = useProducts()
      await products.deleteProduct(1, { reason: 'test' })
      expect(productsApi.deleteProduct).toHaveBeenCalledWith(1, { reason: 'test' })
    })
  })

  describe('batchDeleteProducts', () => {
    it('batch deletes and reloads', async () => {
      vi.mocked(productsApi.batchDeleteProducts).mockResolvedValueOnce({ success: true } as any)
      vi.mocked(productsApi.getProducts).mockResolvedValueOnce({
        success: true,
        data: [],
      } as any)
      const products = useProducts()
      const result = await products.batchDeleteProducts([1, 2, 3])
      expect(result).toBeUndefined()
      expect(productsApi.batchDeleteProducts).toHaveBeenCalledWith([1, 2, 3])
    })

    it('returns null on error', async () => {
      vi.mocked(productsApi.batchDeleteProducts).mockRejectedValueOnce(new Error('Batch error'))
      const products = useProducts()
      const result = await products.batchDeleteProducts([1])
      expect(result).toBeNull()
    })
  })

  describe('refreshProducts', () => {
    it('delegates to loadProducts with empty params', async () => {
      vi.mocked(productsApi.getProducts).mockResolvedValueOnce({
        success: true,
        data: [],
      } as any)
      const products = useProducts()
      await products.refreshProducts()
      expect(productsApi.getProducts).toHaveBeenCalled()
    })
  })
})

describe('useProductDetail', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns composable API', () => {
    const detail = useProductDetail(1)
    expect(detail.product).toBeDefined()
    expect(detail.error).toBeDefined()
    expect(detail.loading).toBeDefined()
    expect(typeof detail.refresh).toBe('function')
  })
})
