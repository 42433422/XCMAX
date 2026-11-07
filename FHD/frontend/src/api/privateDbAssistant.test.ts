import { describe, it, expect, vi, beforeEach } from 'vitest'

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('./core', () => ({ api: apiMock, default: apiMock }))

const MOD_ID = 'private-db-read-assistant'
const BASE = `/api/mod/${MOD_ID}`
const AVAILABLE_MODS = { success: true, data: [{ id: MOD_ID, enabled: true }] }
const SUCCESS = { success: true, data: { ok: 1 } }

async function freshApi() {
  vi.resetModules()
  const mod = await import('./privateDbAssistant')
  return mod.default
}

beforeEach(() => {
  apiMock.get.mockReset().mockImplementation(async (url: string) => url === '/api/mods/' ? AVAILABLE_MODS : SUCCESS)
  apiMock.post.mockReset().mockResolvedValue(SUCCESS)
})

describe('privateDbAssistantApi when mod available', () => {
  it('routes GET calls through when mod enabled', async () => {
    const api = await freshApi()
    expect(await api.status()).toEqual(SUCCESS)
    await api.listSources()
    await api.searchContacts('s/1', 'a & b')
    await api.getContext('s/1', 'u/5')
    expect(apiMock.get.mock.calls.filter(([url]) => url !== '/api/mods/')).toEqual([
      [`${BASE}/status`],
      [`${BASE}/sources`],
      [`${BASE}/contacts/search?source_id=s%2F1&q=a%20%26%20b`],
      [`${BASE}/contacts/u%2F5/context?source_id=s%2F1`],
    ])
  })

  it('routes POST calls through when mod enabled', async () => {
    const api = await freshApi()
    await api.selectSource('s1')
    await api.refreshSource('s1', 'all')
    await api.sendMessage('s1', 'tom', 'hi')
    expect(apiMock.post.mock.calls).toEqual([
      [`${BASE}/sources/select`, { source_id: 's1' }],
      [`${BASE}/sources/refresh`, { source_id: 's1', refresh_type: 'all' }],
      [`${BASE}/send`, { source_id: 's1', contact_name: 'tom', message: 'hi' }],
    ])
  })
})

describe('privateDbAssistantApi availability changes and recovery', () => {
  it.each([
    ['missing', []],
    ['disabled', [{ id: MOD_ID, enabled: false }]],
  ])('rechecks a previously %s Mod without reloading', async (_state, mods) => {
    apiMock.get.mockResolvedValueOnce({ success: true, data: mods })
    const api = await freshApi()
    const r = await api.status()
    expect(r.success).toBe(false)
    expect(r.message).toContain('未安装')
    expect(apiMock.get).not.toHaveBeenCalledWith(`${BASE}/status`)
    expect(await api.status()).toEqual(SUCCESS)
  })

  it('rechecks account-visible Mods after a successful request', async () => {
    const api = await freshApi()
    expect(await api.status()).toEqual(SUCCESS)
    expect(apiMock.get).toHaveBeenCalledWith('/api/mods/', {}, { cache: 'no-store' })
    apiMock.get.mockResolvedValueOnce({ success: true, data: [] })
    expect((await api.listSources()).success).toBe(false)
    expect(apiMock.get).not.toHaveBeenCalledWith(`${BASE}/sources`)
    expect(await api.listSources()).toEqual(SUCCESS)
  })

  it('preserves availability errors and retries on the next call', async () => {
    const error = new Error('Mod catalog temporarily offline')
    apiMock.get.mockRejectedValueOnce(error)
    const api = await freshApi()
    await expect(api.listSources()).rejects.toBe(error)
    expect(await api.listSources()).toEqual(SUCCESS)
  })

  it('reports a failed catalog response without declaring the Mod absent', async () => {
    apiMock.get.mockResolvedValueOnce({ success: false, message: 'Mod catalog unavailable' })
    const api = await freshApi()
    await expect(api.status()).rejects.toThrow('Mod catalog unavailable')
    expect(await api.status()).toEqual(SUCCESS)
  })

  it.each(['GET', 'POST'])('preserves a business %s error and allows retry', async (method) => {
    const error = Object.assign(new Error('Source temporarily offline'), { status: 503 })
    if (method === 'GET') apiMock.get.mockResolvedValueOnce(AVAILABLE_MODS).mockRejectedValueOnce(error)
    else apiMock.post.mockRejectedValueOnce(error)
    const api = await freshApi()
    const request = () => method === 'GET' ? api.status() : api.selectSource('s1')
    await expect(request()).rejects.toBe(error)
    expect(await request()).toEqual(SUCCESS)
  })
})
