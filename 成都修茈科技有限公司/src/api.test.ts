import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, setAuthTokens, clearAuthTokens, ACCESS_TOKEN_KEY, REFRESH_TOKEN_KEY } from './api'

function jsonResponse(body: unknown, init: { status?: number } = {}): Response {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('payment checkout — 签名在服务端完成（无前端密钥）', () => {
  beforeEach(() => {
    localStorage.clear()
    document.cookie = ''
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('先调用 /api/payment/sign-checkout 获取服务端签名，再带签名调用 /checkout', async () => {
    const calls: Array<{ url: string; body: unknown }> = []
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      const body = init?.body ? JSON.parse(String(init.body)) : null
      calls.push({ url: String(url), body })
      if (String(url).endsWith('/api/payment/sign-checkout')) {
        return jsonResponse({
          plan_id: 'pro_monthly',
          item_id: 12,
          total_amount: 100,
          subject: '订阅',
          wallet_recharge: false,
          request_id: 'srv_req_1',
          timestamp: 1700000000,
          signature: 'server_computed_sig',
        })
      }
      return jsonResponse({ ok: true, type: 'page', redirect_url: 'https://pay' })
    })
    vi.stubGlobal('fetch', fetchMock)

    await api.paymentCheckout({
      item_id: 12,
      plan_id: 'pro_monthly',
      subject: '订阅',
      total_amount: 100,
      wallet_recharge: false,
    })

    expect(calls[0].url).toContain('/api/payment/sign-checkout')
    expect(calls[1].url).toContain('/api/payment/checkout')
    // checkout 使用的是服务端返回的 request_id/timestamp/signature
    const checkoutBody = calls[1].body as Record<string, unknown>
    expect(checkoutBody.request_id).toBe('srv_req_1')
    expect(checkoutBody.timestamp).toBe(1700000000)
    expect(checkoutBody.signature).toBe('server_computed_sig')
  })

  it('源码中不含任何支付密钥或可预测默认密钥', async () => {
    const [fs, path] = await Promise.all([import('fs'), import('path')])
    const src = fs.readFileSync(path.resolve(process.cwd(), 'src/api.ts'), 'utf8')
    expect(src).not.toContain('default_secret_key')
    expect(src).not.toContain('paymentSecretKey')
    expect(src).not.toMatch(/VITE_PAYMENT_SECRET/)
  })
})

describe('CSRF — 写请求附带 X-CSRF-Token（无 Bearer 时）', () => {
  beforeEach(() => {
    localStorage.clear()
    document.cookie = 'csrf_token=tok123'
  })
  afterEach(() => {
    vi.restoreAllMocks()
    document.cookie = 'csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT'
  })

  it('未登录的写请求带上与 cookie 一致的 X-CSRF-Token，且 credentials=include', async () => {
    let captured: RequestInit | undefined
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      captured = init
      return jsonResponse({ ok: true })
    })
    vi.stubGlobal('fetch', fetchMock)

    await api.recharge(10) // POST 无 token
    const headers = captured?.headers as Record<string, string>
    expect(headers['X-CSRF-Token']).toBe('tok123')
    expect(captured?.credentials).toBe('include')
  })

  it('带 Bearer 的写请求不附 CSRF（后端对 Bearer 豁免）', async () => {
    localStorage.setItem(ACCESS_TOKEN_KEY, 'access_abc')
    let captured: RequestInit | undefined
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      captured = init
      return jsonResponse({ ok: true })
    })
    vi.stubGlobal('fetch', fetchMock)

    await api.recharge(10)
    const headers = captured?.headers as Record<string, string>
    expect(headers['Authorization']).toBe('Bearer access_abc')
    expect(headers['X-CSRF-Token']).toBeUndefined()
  })
})

describe('access token 刷新 — 401 时用 refresh token 静默重试一次', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => vi.restoreAllMocks())

  it('401 后调用 /api/auth/refresh 并用新 token 重试原请求', async () => {
    localStorage.setItem(ACCESS_TOKEN_KEY, 'expired')
    localStorage.setItem(REFRESH_TOKEN_KEY, 'refresh_xyz')
    const urls: string[] = []
    let balanceHits = 0
    const fetchMock = vi.fn(async (url: string) => {
      urls.push(String(url))
      if (String(url).endsWith('/api/auth/refresh')) {
        return jsonResponse({ access_token: 'fresh', refresh_token: 'refresh_2' })
      }
      if (String(url).endsWith('/api/wallet/balance')) {
        balanceHits += 1
        if (balanceHits === 1) return jsonResponse({ detail: 'unauthorized' }, { status: 401 })
        return jsonResponse({ balance: 42 })
      }
      return jsonResponse({})
    })
    vi.stubGlobal('fetch', fetchMock)

    const res = (await api.balance()) as { balance: number }
    expect(res.balance).toBe(42)
    expect(urls.some((u) => u.endsWith('/api/auth/refresh'))).toBe(true)
    expect(balanceHits).toBe(2)
    expect(localStorage.getItem(ACCESS_TOKEN_KEY)).toBe('fresh')
  })

  it('无 refresh token 时不重试，直接抛错', async () => {
    localStorage.setItem(ACCESS_TOKEN_KEY, 'expired')
    const fetchMock = vi.fn(async () => jsonResponse({ detail: 'unauthorized' }, { status: 401 }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(api.balance()).rejects.toThrow()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})

describe('setAuthTokens — 双令牌存储与兼容旧 token 字段', () => {
  beforeEach(() => localStorage.clear())

  it('存储 access_token + refresh_token', () => {
    setAuthTokens({ access_token: 'a', refresh_token: 'r' })
    expect(localStorage.getItem(ACCESS_TOKEN_KEY)).toBe('a')
    expect(localStorage.getItem(REFRESH_TOKEN_KEY)).toBe('r')
  })

  it('兼容旧后端的 token 字段', () => {
    setAuthTokens({ token: 'legacy' })
    expect(localStorage.getItem(ACCESS_TOKEN_KEY)).toBe('legacy')
  })

  it('clearAuthTokens 清空两枚令牌', () => {
    setAuthTokens({ access_token: 'a', refresh_token: 'r' })
    clearAuthTokens()
    expect(localStorage.getItem(ACCESS_TOKEN_KEY)).toBeNull()
    expect(localStorage.getItem(REFRESH_TOKEN_KEY)).toBeNull()
  })
})
