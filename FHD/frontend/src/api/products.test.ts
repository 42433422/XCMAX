import { describe, it, expect, vi, beforeEach } from 'vitest'

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), download: vi.fn() }))
vi.mock('./core', () => ({ api: apiMock, default: apiMock }))

import productsApi from './products'

beforeEach(() => {
  for (const fn of Object.values(apiMock)) fn.mockReset().mockResolvedValue({ success: true })
})

describe('productsApi', () => {
  it('covers crud + export endpoints', async () => {
    await productsApi.getProducts({ page: 1 })
    await productsApi.getProduct(1)
    await productsApi.createProduct({ name: 'a' } as never)
    await productsApi.updateProduct(1, { name: 'b' } as never)
    await productsApi.deleteProduct(1)
    await productsApi.batchDeleteProducts([1, 2])
    await productsApi.exportUnitProductsXlsx({ unit: 'u' })
    await productsApi.exportUnitProductsDocx({ unit: 'u' })
    await productsApi.getProductNames()
    await productsApi.searchProductNames('kw')
    await productsApi.batchAddProducts([{ name: 'a' } as never])
    expect(apiMock.get).toHaveBeenCalled()
    expect(apiMock.post).toHaveBeenCalled()
    expect(apiMock.download).toHaveBeenCalledTimes(2)
  })

  it('searchProducts builds params conditionally', async () => {
    await productsApi.searchProducts('  ', undefined)
    expect(apiMock.get).toHaveBeenLastCalledWith(expect.stringContaining('/products/list'), { page: 1, per_page: 20 })
    await productsApi.searchProducts('paint', 'u1')
    expect(apiMock.get).toHaveBeenLastCalledWith(expect.any(String), { page: 1, per_page: 20, keyword: 'paint', unit: 'u1' })
  })

  it('getProductUnits handles array, nested, and empty shapes', async () => {
    apiMock.get.mockResolvedValueOnce({ data: [' a ', '', 'b'] })
    expect((await productsApi.getProductUnits()).data).toEqual(['a', 'b'])
    apiMock.get.mockResolvedValueOnce({ data: { units: ['x', 'y'] } })
    expect((await productsApi.getProductUnits()).data).toEqual(['x', 'y'])
    apiMock.get.mockResolvedValueOnce({ data: null })
    expect((await productsApi.getProductUnits()).count).toBe(0)
  })
})
