import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiFetchMock = vi.fn()

vi.mock('@/utils/apiBase', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}))

beforeEach(async () => {
  apiFetchMock.mockReset()
  vi.unstubAllEnvs()
  vi.resetModules()
})

async function loadProductSku() {
  return import('./productSku')
}

describe('productSku', () => {
  it('isEnterpriseEdition detects enterprise sku', async () => {
    const { isEnterpriseEdition } = await loadProductSku()
    expect(isEnterpriseEdition('enterprise')).toBe(true)
    expect(isEnterpriseEdition('generic')).toBe(false)
    expect(isEnterpriseEdition('')).toBe(false)
  })

  it('fetchProductSku returns runtime sku from api', async () => {
    const { fetchProductSku } = await loadProductSku()
    apiFetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({ data: { sku: 'enterprise' } }),
    })
    const sku = await fetchProductSku(true)
    expect(sku).toBe('enterprise')
    expect(apiFetchMock).toHaveBeenCalledWith('/api/runtime/product-sku', { timeoutMs: 8000 })
  })

  it('fetchProductSku falls back to generic on failure', async () => {
    const { fetchProductSku } = await loadProductSku()
    apiFetchMock.mockRejectedValue(new Error('offline'))
    const sku = await fetchProductSku(true)
    expect(sku).toBe('generic')
  })

  it('retries a runtime SKU route that is temporarily unavailable during startup', async () => {
    const { fetchProductSku } = await loadProductSku()
    apiFetchMock
      .mockResolvedValueOnce({ ok: false, status: 404 })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ data: { sku: 'enterprise' } }) })

    await expect(fetchProductSku(true)).resolves.toBe('enterprise')
    expect(apiFetchMock).toHaveBeenCalledTimes(2)
  })

  it('does not cache the generic fallback after the runtime SKU route remains unavailable', async () => {
    const { fetchProductSku } = await loadProductSku()
    apiFetchMock.mockResolvedValue({ ok: false, status: 404 })

    await expect(fetchProductSku()).resolves.toBe('generic')
    expect(apiFetchMock).toHaveBeenCalledTimes(3)

    apiFetchMock.mockResolvedValue({ ok: true, json: async () => ({ data: { sku: 'enterprise' } }) })
    await expect(fetchProductSku()).resolves.toBe('enterprise')
    expect(apiFetchMock).toHaveBeenCalledTimes(4)
  })

  it('fetchProductSku uses VITE override in dev', async () => {
    const { fetchProductSku } = await loadProductSku()
    vi.stubEnv('DEV', true)
    vi.stubEnv('VITE_XCAGI_PRODUCT_SKU', 'personal')
    const sku = await fetchProductSku()
    expect(sku).toBe('personal')
    expect(apiFetchMock).not.toHaveBeenCalled()
  })
})
