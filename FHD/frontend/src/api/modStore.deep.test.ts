import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fetchMarketCatalog, installHostFoundation } from './modStore'

vi.mock('@/utils/apiBase', () => ({
  apiFetch: vi.fn(),
  DEFAULT_MOD_API_TIMEOUT_MS: 30000,
}))
vi.mock('@/utils/platformShellApi', () => ({
  clearDeliverableStatusCache: vi.fn(),
}))

import { apiFetch } from '@/utils/apiBase'

describe('modStore api deep', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('fetchMarketCatalog parses catalog response', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        data: { items: [{ id: 'm1', name: 'Mod' }], total: 1, collection: 'market' },
      }),
    } as Response)
    const res = await fetchMarketCatalog({ limit: 10 })
    expect(apiFetch).toHaveBeenCalled()
    expect(res.items).toBeDefined()
  })

  it('installHostFoundation posts install request', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, message: 'ok', data: { id: 'f', name: 'F', version: '1' } }),
    } as Response)
    const res = await installHostFoundation('generic')
    expect(apiFetch).toHaveBeenCalled()
    expect(res.success).toBe(true)
  })
})
