import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fetchModRoutesPayloadShared } from './modRoutesSharedFetch'

vi.mock('@/utils/apiBase', () => ({
  apiFetch: vi.fn(),
}))

import { apiFetch } from '@/utils/apiBase'

describe('modRoutesSharedFetch', () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset()
  })

  it('returns routes array on success', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        data: [{ mod_id: 'demo', routes_path: '/mods/demo/frontend/routes.js' }],
      }),
    } as Response)
    const rows = await fetchModRoutesPayloadShared()
    expect(rows).toHaveLength(1)
    expect(rows?.[0].mod_id).toBe('demo')
  })

  it('returns null on HTTP error', async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ok: false } as Response)
    await expect(fetchModRoutesPayloadShared()).resolves.toBeNull()
  })

  it('dedupes concurrent inflight requests', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, data: [] }),
    } as Response)
    const [a, b] = await Promise.all([
      fetchModRoutesPayloadShared(),
      fetchModRoutesPayloadShared(),
    ])
    expect(a).toEqual([])
    expect(b).toEqual([])
    expect(apiFetch).toHaveBeenCalledTimes(1)
  })
})
