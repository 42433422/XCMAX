import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  normalizePastedAuthorization,
  formatMarketServiceError,
  degradedMarketAccountOverview,
  syncMarketAccount,
  fetchMarketAccountOverview,
  fetchMarketLlmCatalog,
  fetchSessionMarketHandoff,
  persistMarketTokensFromHandoff,
  applyMarketTokensAfterFhdLogin,
  loginMarketAccount,
  registerMarketAccount,
  directMarketCheckout,
  LS_MARKET_ACCESS_TOKEN,
  LS_MARKET_REFRESH_TOKEN,
  LS_MARKET_USER_JSON,
} from './marketAccount'

vi.mock('@/utils/apiBase', () => ({
  apiFetch: vi.fn(),
}))

import { apiFetch } from '@/utils/apiBase'

const mockApiFetch = vi.mocked(apiFetch)

describe('marketAccount – normalizePastedAuthorization', () => {
  it('strips "Authorization: " prefix (case-insensitive)', () => {
    expect(normalizePastedAuthorization('Authorization: Bearer abc')).toBe('Bearer abc')
    expect(normalizePastedAuthorization('authorization: Bearer abc')).toBe('Bearer abc')
  })

  it('trims whitespace', () => {
    expect(normalizePastedAuthorization('  token123  ')).toBe('token123')
  })

  it('returns empty for empty input', () => {
    expect(normalizePastedAuthorization('')).toBe('')
    expect(normalizePastedAuthorization('   ')).toBe('')
  })

  it('passes through token without prefix', () => {
    expect(normalizePastedAuthorization('Bearer xyz')).toBe('Bearer xyz')
  })
})

describe('marketAccount – formatMarketServiceError', () => {
  it('maps 500 with generic message to Chinese hint', () => {
    const msg = formatMarketServiceError(500, 'Internal Server Error', 'http://example.com')
    expect(msg).toContain('500')
    expect(msg).toContain('XCAGI_MARKET_BASE_URL')
  })

  it('maps 500 with specific message', () => {
    const msg = formatMarketServiceError(500, 'Database connection failed', 'http://example.com')
    expect(msg).toContain('Database connection failed')
  })

  it('maps 401 to bind hint', () => {
    const msg = formatMarketServiceError(401, 'Unauthorized')
    expect(msg).toContain('市场账号')
  })

  it('maps 429 to rate limit hint', () => {
    const msg = formatMarketServiceError(429, 'Too many requests')
    expect(msg).toContain('频繁')
  })

  it('includes default market URL hint when no base provided', () => {
    const msg = formatMarketServiceError(500, '', '')
    expect(msg).toContain('XCAGI_MARKET_BASE_URL')
  })

  it('returns raw message for other status codes', () => {
    const msg = formatMarketServiceError(400, 'Bad request')
    expect(msg).toBe('Bad request')
  })

  it('returns HTTP status for unknown errors without message', () => {
    const msg = formatMarketServiceError(418, '')
    expect(msg).toContain('418')
  })
})

describe('marketAccount – degradedMarketAccountOverview', () => {
  it('returns degraded shape with correct fields', () => {
    const overview = degradedMarketAccountOverview('sync failed', 'http://m')
    expect(overview.degraded).toBe(true)
    expect(overview.market_unreachable).toBe(true)
    expect(overview.sync_warning).toBe('sync failed')
    expect(overview.market_base_url).toBe('http://m')
    expect(overview.user).toEqual({})
    expect(overview.wallet).toBeDefined()
    expect(overview.membership).toBeDefined()
    expect(overview.quotas).toEqual([])
    expect(overview.llm).toBeDefined()
  })
})

describe('marketAccount – syncMarketAccount', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('throws on failure response', async () => {
    mockApiFetch.mockResolvedValueOnce({
      json: async () => ({ success: false, message: 'bad' }),
    } as Response)
    await expect(syncMarketAccount('tok')).rejects.toThrow('bad')
  })

  it('returns data on success', async () => {
    mockApiFetch.mockResolvedValueOnce({
      json: async () => ({
        success: true,
        data: { user: { username: 'u' }, market_base_url: 'http://m' },
      }),
    } as Response)
    const data = await syncMarketAccount('Bearer x')
    expect(data.user.username).toBe('u')
  })

  it('sends authorization header', async () => {
    mockApiFetch.mockResolvedValueOnce({
      json: async () => ({
        success: true,
        data: { user: {}, market_base_url: '' },
      }),
    } as Response)
    await syncMarketAccount('Bearer test-token')
    const callOpts = mockApiFetch.mock.calls[0][1] as Record<string, unknown>
    const headers = callOpts.headers as Record<string, string>
    expect(headers.Authorization).toBe('Bearer test-token')
  })
})

describe('marketAccount – fetchMarketAccountOverview', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns data on success', async () => {
    mockApiFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        success: true,
        data: { user: { username: 'u' }, market_base_url: 'http://m', wallet: {}, membership: null },
      }),
    } as Response)
    const data = await fetchMarketAccountOverview('tok')
    expect(data.user.username).toBe('u')
  })

  it('returns degraded data on server error', async () => {
    mockApiFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      json: async () => ({ success: false, message: 'Server error' }),
    } as Response)
    const data = await fetchMarketAccountOverview('tok')
    expect(data.degraded).toBe(true)
  })

  it('throws on 401', async () => {
    mockApiFetch.mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: async () => ({ success: false, message: 'Unauthorized' }),
    } as Response)
    await expect(fetchMarketAccountOverview('tok')).rejects.toThrow()
  })

  it('handles degraded data with sync_warning', async () => {
    mockApiFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        success: true,
        data: { user: {}, market_base_url: 'http://m', degraded: true, sync_warning: 'Timeout' },
      }),
    } as Response)
    const data = await fetchMarketAccountOverview('tok')
    expect(data.degraded).toBe(true)
    expect(data.sync_warning).toContain('Timeout')
  })
})

describe('marketAccount – fetchMarketLlmCatalog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns data on success', async () => {
    mockApiFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        success: true,
        data: { providers: [{ provider: 'openai' }], preferences: {} },
      }),
    } as Response)
    const data = await fetchMarketLlmCatalog('tok')
    expect(data.providers).toHaveLength(1)
  })

  it('returns degraded on server error', async () => {
    mockApiFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      json: async () => ({ success: false, message: 'Error' }),
    } as Response)
    const data = await fetchMarketLlmCatalog('tok')
    expect(data.providers).toEqual([])
  })

  it('throws on 401', async () => {
    mockApiFetch.mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: async () => ({ success: false, message: 'Unauthorized' }),
    } as Response)
    await expect(fetchMarketLlmCatalog('tok')).rejects.toThrow()
  })

  it('passes refresh parameter', async () => {
    mockApiFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ success: true, data: { providers: [] } }),
    } as Response)
    await fetchMarketLlmCatalog('tok', true)
    const url = mockApiFetch.mock.calls[0][0] as string
    expect(url).toContain('refresh=true')
  })
})

describe('marketAccount – fetchSessionMarketHandoff', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns null on failure', async () => {
    mockApiFetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ success: false }),
    } as Response)
    const result = await fetchSessionMarketHandoff()
    expect(result).toBeNull()
  })

  it('returns auth result on success', async () => {
    mockApiFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        success: true,
        data: { market_access_token: 'tok123', market_base_url: 'http://m' },
      }),
    } as Response)
    const result = await fetchSessionMarketHandoff()
    expect(result?.token).toBe('tok123')
    expect(result?.market_base_url).toBe('http://m')
  })

  it('persists refresh token to localStorage', async () => {
    localStorage.clear()
    mockApiFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        success: true,
        data: { market_access_token: 'tok', market_refresh_token: 'refresh_tok', market_base_url: '' },
      }),
    } as Response)
    await fetchSessionMarketHandoff()
    expect(localStorage.getItem(LS_MARKET_REFRESH_TOKEN)).toBe('refresh_tok')
  })
})

describe('marketAccount – persistMarketTokensFromHandoff', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('persists tokens to localStorage', () => {
    persistMarketTokensFromHandoff({ token: 'access_tok', market_base_url: '', refresh_token: 'refresh_tok' })
    expect(localStorage.getItem(LS_MARKET_ACCESS_TOKEN)).toBe('access_tok')
    expect(localStorage.getItem(LS_MARKET_REFRESH_TOKEN)).toBe('refresh_tok')
  })

  it('does nothing when handoff is null', () => {
    persistMarketTokensFromHandoff(null)
    expect(localStorage.getItem(LS_MARKET_ACCESS_TOKEN)).toBeNull()
  })

  it('does nothing when token is empty', () => {
    persistMarketTokensFromHandoff({ token: '', market_base_url: '' })
    expect(localStorage.getItem(LS_MARKET_ACCESS_TOKEN)).toBeNull()
  })
})

describe('marketAccount – applyMarketTokensAfterFhdLogin', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('persists tokens from raw response data', async () => {
    await applyMarketTokensAfterFhdLogin({
      data: { market_access_token: 'from_data', market_refresh_token: 'refresh_data' },
    })
    expect(localStorage.getItem(LS_MARKET_ACCESS_TOKEN)).toBe('from_data')
  })

  it('persists tokens from top-level response', async () => {
    await applyMarketTokensAfterFhdLogin({
      market_access_token: 'from_top',
    })
    expect(localStorage.getItem(LS_MARKET_ACCESS_TOKEN)).toBe('from_top')
  })

  it('falls back to session handoff when no token in response', async () => {
    mockApiFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        success: true,
        data: { market_access_token: 'handoff_tok', market_base_url: '' },
      }),
    } as Response)
    await applyMarketTokensAfterFhdLogin({ success: true })
    expect(localStorage.getItem(LS_MARKET_ACCESS_TOKEN)).toBe('handoff_tok')
  })
})

describe('marketAccount – loginMarketAccount', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns auth result on success', async () => {
    mockApiFetch.mockResolvedValueOnce({
      json: async () => ({
        success: true,
        data: { token: 'login_tok', market_base_url: 'http://m' },
      }),
    } as Response)
    const result = await loginMarketAccount('user', 'pass')
    expect(result.token).toBe('login_tok')
  })

  it('throws on failure', async () => {
    mockApiFetch.mockResolvedValueOnce({
      json: async () => ({ success: false, message: 'Invalid credentials' }),
    } as Response)
    await expect(loginMarketAccount('user', 'wrong')).rejects.toThrow('Invalid credentials')
  })
})

describe('marketAccount – registerMarketAccount', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns auth result on success', async () => {
    mockApiFetch.mockResolvedValueOnce({
      json: async () => ({
        success: true,
        data: { token: 'reg_tok', market_base_url: 'http://m' },
      }),
    } as Response)
    const result = await registerMarketAccount('user', 'pass', 'e@e.com')
    expect(result.token).toBe('reg_tok')
  })

  it('throws on failure', async () => {
    mockApiFetch.mockResolvedValueOnce({
      json: async () => ({ success: false, detail: 'Email taken' }),
    } as Response)
    await expect(registerMarketAccount('user', 'pass', 'e@e.com')).rejects.toThrow('Email taken')
  })
})

describe('marketAccount – directMarketCheckout', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns checkout data on success', async () => {
    mockApiFetch.mockResolvedValueOnce({
      status: 200,
      json: async () => ({
        success: true,
        data: { ok: true, type: 'redirect', redirect_url: 'http://pay', order_id: '123' },
      }),
    } as Response)
    const result = await directMarketCheckout({ username: 'u', total_amount: 100 })
    expect(result.ok).toBe(true)
    expect(result.redirect_url).toBe('http://pay')
  })

  it('throws on failure', async () => {
    mockApiFetch.mockResolvedValueOnce({
      status: 400,
      json: async () => ({ success: false, message: 'Insufficient balance' }),
    } as Response)
    await expect(directMarketCheckout({})).rejects.toThrow('Insufficient balance')
  })
})

describe('marketAccount – exports', () => {
  it('exports correct localStorage keys', () => {
    expect(LS_MARKET_ACCESS_TOKEN).toContain('market_access_token')
    expect(LS_MARKET_REFRESH_TOKEN).toContain('market_refresh_token')
    expect(LS_MARKET_USER_JSON).toContain('market_user_json')
  })
})
