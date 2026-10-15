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

  it.each([
    ['  ', undefined, { page: 1, per_page: 20 }],
    ['paint', 'u1', { page: 1, per_page: 20, keyword: 'paint', unit: 'u1' }],
  ] as const)('searchProducts preserves params for %s', async (query, unit, expected) => {
    await productsApi.searchProducts(query, unit)
    expect(apiMock.get).toHaveBeenLastCalledWith(expect.stringContaining('/products/list'), expected)
  })

  it.each([[[' a ', '', 'b'], ['a', 'b'], 3], [{ units: ['x', 'y'] }, ['x', 'y'], 2], [null, [], 0]])('normalizes product units %j', async (data, expected, count) => {
    apiMock.get.mockResolvedValueOnce({ data })
    expect(await productsApi.getProductUnits()).toMatchObject({ data: expected, count })
  })
})
