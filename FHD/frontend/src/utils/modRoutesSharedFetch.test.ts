import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fetchModRoutesPayloadShared } from './modRoutesSharedFetch'

const session = vi.hoisted(() => ({ epoch: 0 }))
vi.mock('@/utils/authSessionCache', () => ({
  captureAuthSession: () => {
    const epoch = session.epoch
    return () => session.epoch === epoch
  },
}))

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
    const [a, b] = await Promise.all([fetchModRoutesPayloadShared(), fetchModRoutesPayloadShared()])
    expect(a).toEqual([])
    expect(b).toEqual([])
    expect(apiFetch).toHaveBeenCalledTimes(1)
  })
})


it('never shares or publishes a previous account route response', async () => {
  vi.mocked(apiFetch).mockReset()
  let resolveOld!: (value: Response) => void
  let resolveNew!: (value: Response) => void
  vi.mocked(apiFetch).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    .mockImplementationOnce(() => new Promise(resolve => { resolveNew = resolve }))
  const old = fetchModRoutesPayloadShared()
  session.epoch++
  const next = fetchModRoutesPayloadShared()
  resolveOld({ ok: true, json: async () => ({ success: true, data: [{ mod_id: 'old', routes_path: '' }] }) } as Response)
  await expect(old).resolves.toBeNull()
  expect(fetchModRoutesPayloadShared()).toBe(next)
  resolveNew({ ok: true, json: async () => ({ success: true, data: [{ mod_id: 'new', routes_path: '' }] }) } as Response)
  await expect(next).resolves.toEqual([{ mod_id: 'new', routes_path: '' }])
  expect(apiFetch).toHaveBeenCalledTimes(2)
})


it('discards a response when the account changes while decoding JSON', async () => {
  vi.mocked(apiFetch).mockReset()
  let finishJson!: (value: unknown) => void
  vi.mocked(apiFetch).mockResolvedValue({
    ok: true,
    json: () => new Promise(resolve => { finishJson = resolve }),
  } as unknown as Response)
  const pending = fetchModRoutesPayloadShared()
  await Promise.resolve()
  session.epoch++
  finishJson({ success: true, data: [{ mod_id: 'old-account', routes_path: '' }] })
  await expect(pending).resolves.toBeNull()
})

it('permits recovery after a failed route request without reusing its failure', async () => {
  vi.mocked(apiFetch).mockReset()
  vi.mocked(apiFetch).mockRejectedValueOnce(new Error('temporary network failure'))
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({ success: true, data: [{ mod_id: 'fresh', routes_path: '' }] }),
    } as Response)
  await expect(fetchModRoutesPayloadShared()).resolves.toBeNull()
  await expect(fetchModRoutesPayloadShared()).resolves.toEqual([{ mod_id: 'fresh', routes_path: '' }])
  expect(apiFetch).toHaveBeenCalledTimes(2)
})
