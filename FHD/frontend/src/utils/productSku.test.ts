import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiFetchMock = vi.fn();

vi.mock('@/utils/apiBase', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}));

beforeEach(async () => {
  apiFetchMock.mockReset();
  vi.unstubAllEnvs();
  vi.resetModules();
});

async function loadProductSku() {
  return import('./productSku');
}

describe('productSku', () => {
  it('isEnterpriseEdition detects enterprise sku', async () => {
    const { isEnterpriseEdition } = await loadProductSku();
    expect(isEnterpriseEdition('enterprise')).toBe(true);
    expect(isEnterpriseEdition('generic')).toBe(false);
    expect(isEnterpriseEdition('')).toBe(false);
  });

  it('fetchProductSku returns runtime sku from api', async () => {
    const { fetchProductSku } = await loadProductSku();
    apiFetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({ data: { sku: 'enterprise' } }),
    });
    const sku = await fetchProductSku(true);
    expect(sku).toBe('enterprise');
    expect(apiFetchMock).toHaveBeenCalledWith('/api/runtime/product-sku', { timeoutMs: 8000 });
  });

  it('fetchProductSku falls back to generic on failure', async () => {
    const { fetchProductSku } = await loadProductSku();
    apiFetchMock.mockRejectedValue(new Error('offline'));
    const sku = await fetchProductSku(true);
    expect(sku).toBe('generic');
  });

  it('fetchProductSku uses VITE override in dev', async () => {
    const { fetchProductSku } = await loadProductSku();
    vi.stubEnv('DEV', true);
    vi.stubEnv('VITE_XCAGI_PRODUCT_SKU', 'personal');
    const sku = await fetchProductSku();
    expect(sku).toBe('personal');
    expect(apiFetchMock).not.toHaveBeenCalled();
  });
});
