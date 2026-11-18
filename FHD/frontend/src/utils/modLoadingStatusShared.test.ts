import { beforeEach, describe, expect, it, vi } from 'vitest'

const { apiFetch } = vi.hoisted(() => ({ apiFetch: vi.fn() }))
vi.mock('@/utils/apiBase', () => ({ apiFetch }))

beforeEach(() => { vi.resetModules(); apiFetch.mockReset() })

describe('shared mod loading status', () => {
  it('shares simultaneous startup requests and refreshes after completion', async () => {
    const { fetchModLoadingStatusShared } = await import('./modLoadingStatusShared')
    let finish!: (value: unknown) => void
    apiFetch.mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    const first = fetchModLoadingStatusShared()
    expect(fetchModLoadingStatusShared()).toBe(first)
    expect(apiFetch).toHaveBeenCalledTimes(1)
    expect(apiFetch).toHaveBeenCalledWith('/api/mods/loading-status', { timeoutMs: 12000 })
    finish({ ok: true, json: async () => ({ success: true, data: { phase: 'loading' } }) })
    await expect(first).resolves.toEqual({ phase: 'loading' })
    apiFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ success: true, data: { phase: 'ready' } }) })
    await expect(fetchModLoadingStatusShared()).resolves.toEqual({ phase: 'ready' })
    expect(apiFetch).toHaveBeenCalledTimes(2)
  })

  it.each([
    { ok: false, json: vi.fn() },
    { ok: true, json: async () => ({ success: false, data: {} }) },
    { ok: true, json: async () => ({ success: true }) },
    { ok: true, json: async () => null },
    { ok: true, json: async () => { throw new Error('invalid JSON') } },
  ])('returns no status on an unsuccessful response and allows retry %#', async response => {
    const { fetchModLoadingStatusShared } = await import('./modLoadingStatusShared')
    apiFetch.mockResolvedValueOnce(response)
    await expect(fetchModLoadingStatusShared()).resolves.toBeNull()
    apiFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ success: true, data: { ready: true } }) })
    await expect(fetchModLoadingStatusShared()).resolves.toEqual({ ready: true })
  })

  it('clears a rejected in-flight request so a later call can recover', async () => {
    const { fetchModLoadingStatusShared } = await import('./modLoadingStatusShared')
    apiFetch.mockRejectedValueOnce(new Error('timeout'))
    await expect(fetchModLoadingStatusShared()).resolves.toBeNull()
    apiFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ success: true, data: {} }) })
    await expect(fetchModLoadingStatusShared()).resolves.toEqual({})
  })
})
