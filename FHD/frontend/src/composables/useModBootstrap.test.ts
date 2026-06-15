import { describe, expect, it, vi, beforeEach } from 'vitest'
import { useModBootstrap } from './useModBootstrap'

vi.mock('@/utils/apiBase', () => ({
  apiFetch: vi.fn(),
  DEFAULT_MOD_API_TIMEOUT_MS: 30_000,
}))
vi.mock('@/utils/modRoutesSharedFetch', () => ({
  fetchModRoutesPayloadShared: vi.fn().mockResolvedValue([{ mod_id: 'a' }]),
}))

import { apiFetch } from '@/utils/apiBase'

describe('useModBootstrap', () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset()
  })

  it('loads mods on success', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, data: [{ id: 'm1' }] }),
    } as Response)
    const boot = useModBootstrap()
    const r = await boot.fetchModsOnce()
    expect(r.ok).toBe(true)
    expect(boot.mods.value).toHaveLength(1)
    expect(boot.isLoaded.value).toBe(true)
  })

  it('records HTTP error', async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ok: false, status: 500 } as Response)
    const boot = useModBootstrap()
    const r = await boot.fetchModsOnce()
    expect(r.ok).toBe(false)
    expect(boot.loadError.value).toContain('500')
  })

  it('fetches mod routes payload', async () => {
    const boot = useModBootstrap()
    await boot.fetchModRoutes()
    expect(boot.modRoutes.value).toHaveLength(1)
  })
})
