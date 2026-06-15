import { describe, it, expect, vi, beforeEach } from 'vitest'

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('./core', () => ({ api: apiMock, default: apiMock }))

const MOD_ID = 'private-db-read-assistant'

async function freshApi() {
  vi.resetModules()
  const mod = await import('./privateDbAssistant')
  return mod.default
}

function modsAvailable() {
  apiMock.get.mockResolvedValueOnce({ success: true, data: { mod_id: MOD_ID } })
}

beforeEach(() => {
  apiMock.get.mockReset()
  apiMock.post.mockReset()
})

describe('privateDbAssistantApi when mod available', () => {
  it('routes GET calls through when mod enabled', async () => {
    modsAvailable()
    apiMock.get.mockResolvedValue({ success: true, data: { ok: 1 } })
    const api = await freshApi()
    const r = await api.status()
    expect(r.success).toBe(true)
    await api.listSources()
    await api.searchContacts('s1', 'q')
    await api.getContext('s1', 5)
    expect(apiMock.get).toHaveBeenCalled()
  })

  it('routes POST calls through when mod enabled', async () => {
    modsAvailable()
    apiMock.get.mockResolvedValue({ success: true, data: [] })
    apiMock.post.mockResolvedValue({ success: true })
    const api = await freshApi()
    await api.selectSource('s1')
    await api.refreshSource('s1', 'all')
    await api.sendMessage('s1', 'tom', 'hi')
    expect(apiMock.post).toHaveBeenCalledTimes(3)
  })
})

describe('privateDbAssistantApi when mod unavailable', () => {
  it('returns MOD_UNAVAILABLE when compat status probe fails', async () => {
    apiMock.get.mockResolvedValueOnce({ success: false })
    const api = await freshApi()
    const r = await api.status()
    expect(r.success).toBe(false)
    expect(r.message).toContain('未安装')
  })

  it('returns MOD_UNAVAILABLE when availability probe throws', async () => {
    apiMock.get.mockRejectedValueOnce(new Error('probe boom'))
    const api = await freshApi()
    const r = await api.listSources()
    expect(r.success).toBe(false)
  })

  it('returns MOD_UNAVAILABLE when actual GET throws after available', async () => {
    modsAvailable()
    apiMock.get.mockRejectedValueOnce(new Error('boom'))
    const api = await freshApi()
    const r = await api.status()
    expect(r.success).toBe(false)
  })

  it('returns MOD_UNAVAILABLE when actual POST throws after available', async () => {
    modsAvailable()
    apiMock.post.mockRejectedValueOnce(new Error('boom'))
    const api = await freshApi()
    const r = await api.selectSource('s1')
    expect(r.success).toBe(false)
  })
})
