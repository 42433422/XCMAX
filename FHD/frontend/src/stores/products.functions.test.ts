/**
 * products store 函数覆盖率补齐测试
 * 目标：覆盖所有未测分支（updateProduct、各函数失败路径、异常路径、边界值）
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useProductsStore } from './products'

const mockGetProducts = vi.fn()
const mockCreateProduct = vi.fn()
const mockUpdateProduct = vi.fn()
const mockDeleteProduct = vi.fn()
const mockBatchDelete = vi.fn()

vi.mock('../api/products', () => ({
  default: {
    getProducts: (...args: unknown[]) => mockGetProducts(...args),
    createProduct: (...args: unknown[]) => mockCreateProduct(...args),
    updateProduct: (...args: unknown[]) => mockUpdateProduct(...args),
    deleteProduct: (...args: unknown[]) => mockDeleteProduct(...args),
    batchDeleteProducts: (...args: unknown[]) => mockBatchDelete(...args),
  },
}))

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

describe('products store – fetchProducts 边界与异常', () => {
  it('data.data 为 null 时 products 设为空数组', async () => {
    mockGetProducts.mockResolvedValue({ success: true, data: null, total: 0 })
    const store = useProductsStore()
    const result = await store.fetchProducts()
    expect(result.success).toBe(true)
    expect(store.products).toEqual([])
    expect(result.data).toBeNull()
  })

  it('data.data 为 undefined 时 products 设为空数组', async () => {
    mockGetProducts.mockResolvedValue({ success: true, total: 0 })
    const store = useProductsStore()
    const result = await store.fetchProducts()
    expect(result.success).toBe(true)
    expect(store.products).toEqual([])
  })

  it('success=false 且 message 为空时 error 使用默认消息', async () => {
    mockGetProducts.mockResolvedValue({ success: false })
    const store = useProductsStore()
    const result = await store.fetchProducts()
    expect(result.success).toBe(false)
    expect(store.error).toBe('加载产品失败')
  })

  it('抛出非 Error 对象时 error 使用默认消息', async () => {
    mockGetProducts.mockRejectedValue('string error')
    const store = useProductsStore()
    const result = await store.fetchProducts()
    expect(result.success).toBe(false)
    expect(store.error).toBe('加载产品失败')
  })

  it('total 为 0 时返回 total=0', async () => {
    mockGetProducts.mockResolvedValue({ success: true, data: [], total: 0 })
    const store = useProductsStore()
    const result = await store.fetchProducts()
    expect(result.total).toBe(0)
  })

  it('loading 在请求完成后重置为 false', async () => {
    mockGetProducts.mockResolvedValue({ success: true, data: [], total: 0 })
    const store = useProductsStore()
    expect(store.loading).toBe(false)
    const promise = store.fetchProducts()
    expect(store.loading).toBe(true)
    await promise
    expect(store.loading).toBe(false)
  })
})

describe('products store – createProduct 边界与异常', () => {
  it('success=false 且 message 为空时 error 使用默认消息', async () => {
    mockCreateProduct.mockResolvedValue({ success: false })
    const store = useProductsStore()
    const result = await store.createProduct({ name: 'N' } as never)
    expect(result.success).toBe(false)
    expect(store.error).toBe('创建产品失败')
  })

  it('抛出 Error 时 error 使用 error.message', async () => {
    mockCreateProduct.mockRejectedValue(new Error('create error'))
    const store = useProductsStore()
    const result = await store.createProduct({ name: 'N' } as never)
    expect(result.success).toBe(false)
    expect(store.error).toBe('create error')
  })

  it('抛出非 Error 对象时 error 使用默认消息', async () => {
    mockCreateProduct.mockRejectedValue(42)
    const store = useProductsStore()
    const result = await store.createProduct({ name: 'N' } as never)
    expect(result.success).toBe(false)
    expect(store.error).toBe('创建产品失败')
  })

  it('成功后调用 fetchProducts 刷新列表', async () => {
    mockCreateProduct.mockResolvedValue({ success: true })
    mockGetProducts.mockResolvedValue({ success: true, data: [{ id: 1 }], total: 1 })
    const store = useProductsStore()
    await store.createProduct({ name: 'N' } as never)
    expect(mockGetProducts).toHaveBeenCalled()
  })

  it('loading 在请求完成后重置为 false', async () => {
    mockCreateProduct.mockResolvedValue({ success: true })
    mockGetProducts.mockResolvedValue({ success: true, data: [], total: 0 })
    const store = useProductsStore()
    await store.createProduct({ name: 'N' } as never)
    expect(store.loading).toBe(false)
  })
})

describe('products store – updateProduct 全路径覆盖', () => {
  it('成功时返回 success=true 并刷新列表', async () => {
    mockUpdateProduct.mockResolvedValue({ success: true })
    mockGetProducts.mockResolvedValue({ success: true, data: [{ id: 1 }], total: 1 })
    const store = useProductsStore()
    const result = await store.updateProduct(1, { name: 'updated' } as never)
    expect(result.success).toBe(true)
    expect(mockGetProducts).toHaveBeenCalled()
  })

  it('success=false 且 message 为空时 error 使用默认消息', async () => {
    mockUpdateProduct.mockResolvedValue({ success: false })
    const store = useProductsStore()
    const result = await store.updateProduct(1, { name: 'updated' } as never)
    expect(result.success).toBe(false)
    expect(store.error).toBe('更新产品失败')
  })

  it('success=false 且有 message 时 error 使用 message', async () => {
    mockUpdateProduct.mockResolvedValue({ success: false, message: 'validation failed' })
    const store = useProductsStore()
    const result = await store.updateProduct(1, { name: 'updated' } as never)
    expect(result.success).toBe(false)
    expect(store.error).toBe('validation failed')
  })

  it('抛出 Error 时 error 使用 error.message', async () => {
    mockUpdateProduct.mockRejectedValue(new Error('update error'))
    const store = useProductsStore()
    const result = await store.updateProduct(1, { name: 'updated' } as never)
    expect(result.success).toBe(false)
    expect(store.error).toBe('update error')
  })

  it('抛出非 Error 对象时 error 使用默认消息', async () => {
    mockUpdateProduct.mockRejectedValue(null)
    const store = useProductsStore()
    const result = await store.updateProduct(1, { name: 'updated' } as never)
    expect(result.success).toBe(false)
    expect(store.error).toBe('更新产品失败')
  })

  it('loading 在请求完成后重置为 false', async () => {
    mockUpdateProduct.mockResolvedValue({ success: true })
    mockGetProducts.mockResolvedValue({ success: true, data: [], total: 0 })
    const store = useProductsStore()
    await store.updateProduct(1, { name: 'updated' } as never)
    expect(store.loading).toBe(false)
  })
})

describe('products store – deleteProduct 边界与异常', () => {
  it('success=false 且 message 为空时 error 使用默认消息', async () => {
    mockDeleteProduct.mockResolvedValue({ success: false })
    const store = useProductsStore()
    const result = await store.deleteProduct(5)
    expect(result.success).toBe(false)
    expect(store.error).toBe('删除产品失败')
  })

  it('success=false 且有 message 时 error 使用 message', async () => {
    mockDeleteProduct.mockResolvedValue({ success: false, message: 'not found' })
    const store = useProductsStore()
    const result = await store.deleteProduct(5)
    expect(result.success).toBe(false)
    expect(store.error).toBe('not found')
  })

  it('抛出 Error 时 error 使用 error.message', async () => {
    mockDeleteProduct.mockRejectedValue(new Error('delete error'))
    const store = useProductsStore()
    const result = await store.deleteProduct(5)
    expect(result.success).toBe(false)
    expect(store.error).toBe('delete error')
  })

  it('抛出非 Error 对象时 error 使用默认消息', async () => {
    mockDeleteProduct.mockRejectedValue(undefined)
    const store = useProductsStore()
    const result = await store.deleteProduct(5)
    expect(result.success).toBe(false)
    expect(store.error).toBe('删除产品失败')
  })

  it('成功时从本地列表中移除该产品', async () => {
    mockDeleteProduct.mockResolvedValue({ success: true })
    const store = useProductsStore()
    store.products = [
      { id: 1, name: 'A' } as never,
      { id: 5, name: 'B' } as never,
      { id: 10, name: 'C' } as never,
    ]
    await store.deleteProduct(5)
    expect(store.products.map((p) => p.id)).toEqual([1, 10])
  })

  it('删除不存在的 id 时列表不变', async () => {
    mockDeleteProduct.mockResolvedValue({ success: true })
    const store = useProductsStore()
    store.products = [{ id: 1, name: 'A' } as never]
    await store.deleteProduct(999)
    expect(store.products).toHaveLength(1)
  })

  it('loading 在请求完成后重置为 false', async () => {
    mockDeleteProduct.mockResolvedValue({ success: true })
    const store = useProductsStore()
    await store.deleteProduct(5)
    expect(store.loading).toBe(false)
  })
})

describe('products store – batchDelete 边界与异常', () => {
  it('success=false 且 message 为空时 error 使用默认消息', async () => {
    mockBatchDelete.mockResolvedValue({ success: false })
    const store = useProductsStore()
    const result = await store.batchDelete([1, 2])
    expect(result.success).toBe(false)
    expect(store.error).toBe('批量删除失败')
  })

  it('success=false 且有 message 时 error 使用 message', async () => {
    mockBatchDelete.mockResolvedValue({ success: false, message: 'permission denied' })
    const store = useProductsStore()
    const result = await store.batchDelete([1, 2])
    expect(result.success).toBe(false)
    expect(store.error).toBe('permission denied')
  })

  it('抛出 Error 时 error 使用 error.message', async () => {
    mockBatchDelete.mockRejectedValue(new Error('batch error'))
    const store = useProductsStore()
    const result = await store.batchDelete([1, 2])
    expect(result.success).toBe(false)
    expect(store.error).toBe('batch error')
  })

  it('抛出非 Error 对象时 error 使用默认消息', async () => {
    mockBatchDelete.mockRejectedValue('fail')
    const store = useProductsStore()
    const result = await store.batchDelete([1, 2])
    expect(result.success).toBe(false)
    expect(store.error).toBe('批量删除失败')
  })

  it('成功时从本地列表中移除多个产品', async () => {
    mockBatchDelete.mockResolvedValue({ success: true })
    const store = useProductsStore()
    store.products = [
      { id: 1, name: 'A' } as never,
      { id: 2, name: 'B' } as never,
      { id: 3, name: 'C' } as never,
    ]
    await store.batchDelete([1, 3])
    expect(store.products.map((p) => p.id)).toEqual([2])
  })

  it('空 ids 数组时成功且列表不变', async () => {
    mockBatchDelete.mockResolvedValue({ success: true })
    const store = useProductsStore()
    store.products = [{ id: 1, name: 'A' } as never]
    const result = await store.batchDelete([])
    expect(result.success).toBe(true)
    expect(store.products).toHaveLength(1)
  })

  it('字符串 id 也能正确过滤', async () => {
    mockBatchDelete.mockResolvedValue({ success: true })
    const store = useProductsStore()
    store.products = [
      { id: 'abc', name: 'A' } as never,
      { id: 'def', name: 'B' } as never,
    ]
    await store.batchDelete(['abc'])
    expect(store.products.map((p) => p.id)).toEqual(['def'])
  })

  it('loading 在请求完成后重置为 false', async () => {
    mockBatchDelete.mockResolvedValue({ success: true })
    const store = useProductsStore()
    await store.batchDelete([1])
    expect(store.loading).toBe(false)
  })
})

describe('products store – productCount computed', () => {
  it('初始值为 0', () => {
    const store = useProductsStore()
    expect(store.productCount).toBe(0)
  })

  it('随 products 列表长度变化', () => {
    const store = useProductsStore()
    store.products = [{ id: 1 } as never, { id: 2 } as never, { id: 3 } as never]
    expect(store.productCount).toBe(3)
  })
})

describe('products store – 初始状态', () => {
  it('初始 error 为 null', () => {
    const store = useProductsStore()
    expect(store.error).toBeNull()
  })

  it('初始 units 为空数组', () => {
    const store = useProductsStore()
    expect(store.units).toEqual([])
  })
})
