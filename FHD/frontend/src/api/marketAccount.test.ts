import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  normalizePastedAuthorization,
  formatMarketServiceError,
  degradedMarketAccountOverview,
  syncMarketAccount,
  LS_MARKET_ACCESS_TOKEN,
} from './marketAccount'

vi.mock('@/utils/apiBase', () => ({
  apiFetch: vi.fn(),
}))

import { apiFetch } from '@/utils/apiBase'

describe('marketAccount', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('exports localStorage keys', () => {
    expect(LS_MARKET_ACCESS_TOKEN).toContain('market')
  })

  it('normalizePastedAuthorization strips Authorization prefix', () => {
    expect(normalizePastedAuthorization('Authorization: Bearer abc')).toBe('Bearer abc')
    expect(normalizePastedAuthorization('  token123  ')).toBe('token123')
    expect(normalizePastedAuthorization('')).toBe('')
  })

  it('formatMarketServiceError maps 500 to Chinese hint', () => {
    const msg = formatMarketServiceError(500, 'Internal Server Error', 'http://example.com')
    expect(msg).toContain('市场服务')
    expect(msg).toContain('500')
  })

  it('formatMarketServiceError maps 401 to bind hint', () => {
    const msg = formatMarketServiceError(401, 'Unauthorized')
    expect(msg).toContain('市场')
  })

  it('degradedMarketAccountOverview returns degraded shape', () => {
    const overview = degradedMarketAccountOverview('sync failed', 'http://m')
    expect(overview.degraded).toBe(true)
    expect(overview.sync_warning).toBe('sync failed')
    expect(overview.market_base_url).toBe('http://m')
  })

  it('syncMarketAccount throws on failure response', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      json: async () => ({ success: false, message: 'bad' }),
    } as Response)
    await expect(syncMarketAccount('tok')).rejects.toThrow('bad')
  })

  it('syncMarketAccount returns data on success', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      json: async () => ({
        success: true,
        data: { user: { username: 'u' }, market_base_url: 'http://m' },
      }),
    } as Response)
    const data = await syncMarketAccount('Bearer x')
    expect(data.user.username).toBe('u')
  })
})
