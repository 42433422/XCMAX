import { describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { createProductListLoader } from './useProductsReadLifecycle'

describe('ERP product list paging', () => {
  it('loads each server page once and stops when the declared total is reached', async () => {
    const page = ref(1)
    const hasMore = ref(false)
    const requestId = ref(0)
    const fetchProducts = vi.fn().mockImplementation(async ({ page: requestedPage }) => ({
      success: true,
      total: 225,
      data: Array.from({ length: requestedPage < 3 ? 100 : 25 }, (_, i) => ({ id: (requestedPage - 1) * 100 + i })),
    }))
    const loader = createProductListLoader({
      store: { fetchProducts } as never,
      page, hasMore, requestId,
      query: () => ({ per_page: 100 }),
    })
    await loader()
    expect(fetchProducts).toHaveBeenLastCalledWith({ per_page: 100, page: 1 }, { append: false })
    expect(hasMore.value).toBe(true)
    await loader(false)
    expect(fetchProducts).toHaveBeenLastCalledWith({ per_page: 100, page: 2 }, { append: true })
    expect(hasMore.value).toBe(true)
    await loader(false)
    expect(fetchProducts).toHaveBeenLastCalledWith({ per_page: 100, page: 3 }, { append: true })
    expect(hasMore.value).toBe(false)
    expect(page.value).toBe(4)
  })

  it('does not advance pagination after an unsuccessful business read', async () => {
    const page = ref(1)
    const hasMore = ref(false)
    const requestId = ref(0)
    const fetchProducts = vi.fn().mockResolvedValue({ success: false, message: '权限撤销' })
    const loader = createProductListLoader({
      store: { fetchProducts } as never,
      page, hasMore, requestId,
      query: () => ({ per_page: 100 }),
    })
    await loader()
    expect(page.value).toBe(1)
    expect(hasMore.value).toBe(false)
  })
  it('prevents overlapping append and stops at the final page', async () => {
    const page = ref(1), hasMore = ref(false), requestId = ref(0)
    let finish!: (value: unknown) => void
    const fetchProducts = vi.fn()
      .mockResolvedValueOnce({ success: true, total: 2, data: [{ id: 1 }] })
      .mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const loader = createProductListLoader({ store: { fetchProducts } as never, page, hasMore, requestId, query: () => ({ per_page: 1 }) })
    await loader()
    const pending = loader(false)
    await loader(false)
    expect(fetchProducts).toHaveBeenCalledTimes(2)
    finish({ success: true, total: 2, data: [{ id: 2 }] })
    await pending
    expect(page.value).toBe(3)
    expect(hasMore.value).toBe(false)
    await loader(false)
    expect(fetchProducts).toHaveBeenCalledTimes(2)
  })

})
