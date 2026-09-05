import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiFetch } from '@/utils/apiBase'
import { createMarketBrowserHandoff } from './marketAccount'
vi.mock('@/utils/apiBase', () => ({ apiFetch: vi.fn() }))

beforeEach(() => vi.clearAllMocks())
describe('createMarketBrowserHandoff', () => {
  it('sends only target and purpose in a POST, preserving the selected plan', async () => {
    const data = { code: 'a'.repeat(43), target: '/plans?plan=vip', purpose: 'plans', expires_in: 60 }
    vi.mocked(apiFetch).mockResolvedValue({ ok: true, json: async () => ({ success: true, data }) } as Response)
    expect(await createMarketBrowserHandoff('/plans?plan=vip', 'plans')).toEqual(data)
    expect(apiFetch).toHaveBeenCalledWith(
      '/api/market/browser-handoff',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ target: '/plans?plan=vip', purpose: 'plans' }) }),
    )
  })
  it('does not silently fall back to a reusable token after an expired session', async () => {
    vi.mocked(apiFetch).mockResolvedValue({ ok: false, status: 401 } as Response)
    await expect(createMarketBrowserHandoff('/wallet', 'wallet')).rejects.toThrow('重新登录')
    expect(apiFetch).toHaveBeenCalledTimes(1)
  })
})
