import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, buildCheckoutSignData, generateSignature, paymentSecretKey, setTokens } from './api'

function response(body: unknown = {}, init: ResponseInit = {}): Response {
  return new Response(typeof body === 'string' ? body : JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
}

describe('buildCheckoutSignData', () => {
  it('对整数金额输出无小数点形式（与后端签名约定一致）', () => {
    const data = buildCheckoutSignData(
      {
        item_id: 12,
        plan_id: 'pro_monthly',
        subject: '订阅',
        total_amount: 100,
        wallet_recharge: false,
      },
      'req_abc',
      1700000000,
    )
    expect(data.total_amount).toBe('100')
    expect(data.item_id).toBe('12')
    expect(data.plan_id).toBe('pro_monthly')
    expect(data.timestamp).toBe('1700000000')
    expect(data.wallet_recharge).toBe('false')
  })

  it('对小数金额裁剪尾随 0', () => {
    const data = buildCheckoutSignData({ item_id: 0, total_amount: 12.3, wallet_recharge: true }, 'req_x', 1700000000.7)
    expect(data.total_amount).toBe('12.3')
    expect(data.timestamp).toBe('1700000000')
    expect(data.wallet_recharge).toBe('true')
  })

  it('非法/缺失字段降级为空串与 0', () => {
    const data = buildCheckoutSignData({}, '', '0')
    expect(data.item_id).toBe('0')
    expect(data.plan_id).toBe('')
    expect(data.subject).toBe('')
    expect(data.total_amount).toBe('0')
    expect(data.wallet_recharge).toBe('false')
    expect(data.request_id).toBe('')
  })

  it('subject / plan_id 自动 trim', () => {
    const data = buildCheckoutSignData({ plan_id: '  pro  ', subject: '  hi  ', total_amount: 1, wallet_recharge: false }, 'r', 1)
    expect(data.plan_id).toBe('pro')
    expect(data.subject).toBe('hi')
  })
})

describe('generateSignature', () => {
  it('对相同入参产出稳定签名（SHA-256，按 key 排序）', async () => {
    const payload = {
      a: '1',
      b: '2',
      c: 'abc',
    }
    const a = await generateSignature(payload, 'secret')
    const b = await generateSignature(payload, 'secret')
    expect(a).toBe(b)
    expect(a).toHaveLength(64)
    expect(/^[0-9a-f]+$/.test(a)).toBe(true)
  })

  it('不同 secret 输出不同签名', async () => {
    const payload = { a: '1' }
    const s1 = await generateSignature(payload, 'k1')
    const s2 = await generateSignature(payload, 'k2')
    expect(s1).not.toBe(s2)
  })

  it('字段顺序无关（按 key 字典序签名）', async () => {
    const p1 = { b: '2', a: '1' }
    const p2 = { a: '1', b: '2' }
    expect(await generateSignature(p1, 'k')).toBe(await generateSignature(p2, 'k'))
  })
})

describe('paymentSecretKey', () => {
  it('前端不持有任何支付签名密钥', () => {
    expect(paymentSecretKey()).toBe('')
  })
})

describe('api request contracts', () => {
  beforeEach(() => {
    localStorage.clear()
    document.cookie = 'csrf_token=; Max-Age=0; path=/'
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => response({ ok: true, data: [] })),
    )
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('covers every public endpoint and preserves its HTTP contract', async () => {
    setTokens('access-token', 'refresh-token')
    document.cookie = 'csrf_token=csrf%20value; path=/'

    const calls: Array<() => Promise<unknown>> = [
      () => api.register('user', 'password', 'user@example.com', '123456'),
      () => api.login('user', 'password'),
      () => api.me(),
      () => api.refreshToken('refresh'),
      () => api.sendVerificationCode('user@example.com'),
      () => api.sendRegisterVerificationCode('user@example.com'),
      () => api.loginWithCode('user@example.com', '123456'),
      () => api.balance(),
      () => api.recharge(10, 'test'),
      () => api.transactions(5, 2),
      () => api.catalog('query', 'workflow', 5, 2, 'retail', 'enterprise'),
      () => api.catalog(),
      () => api.catalogFacets(),
      () => api.catalogDetail(7),
      () => api.buyItem(7),
      () => api.myStore(5, 2),
      () => api.adminStatus(),
      () => api.adminUpload(new FormData()),
      () => api.adminListCatalog(5, 2),
      () => api.adminDeleteCatalog(7),
      () => api.adminListUsers(5, 2),
      () => api.adminSetUserAdmin(7, true),
      () => api.adminListWallets(5, 2),
      () => api.adminListTransactions(5, 2),
      () => api.paymentPlans(),
      () => api.paymentCheckout({ plan_id: 'starter', total_amount: 10 }),
      () => api.paymentQuery('order-1'),
      () => api.paymentOrders('paid', 5, 2),
      () => api.paymentOrders(),
      () => api.paymentDiagnostics(),
      () => api.paymentEntitlements(),
      () => api.listMods(),
      () => api.createMod('demo', 'Demo'),
      () => api.modAiScaffold('build a MOD'),
      () => api.modAiScaffold('build', 'demo', false),
      () => api.push(['demo']),
      () => api.push(null),
      () => api.pull(['demo']),
      () => api.pull(undefined),
      () => api.getMod('demo/id'),
      () => api.putModManifest('demo/id', { name: 'Demo' }),
      () => api.getModFile('demo/id', 'src/main.py'),
      () => api.putModFile('demo/id', 'src/main.py', 'pass'),
      () => api.getModAuthoringSummary('demo/id'),
      () => api.getModBlueprintRoutes('demo/id'),
      () => api.getAuthoringExtensionSurface(),
      () => api.getAuthoringExtensionSurface(true),
    ]

    for (const call of calls) await call()

    const fetchMock = vi.mocked(fetch)
    expect(fetchMock).toHaveBeenCalledTimes(calls.length)
    const writes = fetchMock.mock.calls.filter(([, init]) => init?.method !== 'GET' && init?.method !== undefined)
    expect(writes.length).toBeGreaterThan(10)
    for (const [, init] of writes) {
      const headers = init?.headers as Record<string, string>
      expect(headers.Authorization).toBe('Bearer access-token')
      expect(headers['X-CSRF-Token']).toBe('csrf value')
    }
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('q=query'))).toBe(true)
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('merge_host=true'))).toBe(true)
  })

  it('imports and downloads files with and without authentication', async () => {
    const createObjectURL = vi.fn(() => 'blob:test')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    vi.mocked(fetch).mockImplementation(async (input) => {
      if (String(input).includes('/download')) return response(new Blob(['zip']))
      return response({ id: 'demo' })
    })

    await api.importZIP(new File(['zip'], 'demo.zip'), false)
    await api.downloadItem(1)
    setTokens('access-token')
    await api.importZIP(new File(['zip'], 'demo.zip'))
    await api.downloadItem(2)

    expect(click).toHaveBeenCalledTimes(2)
    expect(createObjectURL).toHaveBeenCalledTimes(2)
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:test')
  })

  it.each([
    [{ detail: [{ msg: 'first' }, { code: 'second' }] }, 'first; {"code":"second"}'],
    [{ detail: 'plain failure' }, 'plain failure'],
    [{ detail: { reason: 'object failure' } }, '{"reason":"object failure"}'],
    [{}, 'Bad Request'],
  ])('normalizes API error payload %#', async (body, expected) => {
    vi.mocked(fetch).mockResolvedValueOnce(response(body, { status: 400, statusText: 'Bad Request' }))
    await expect(api.me()).rejects.toThrow(expected)
  })

  it('keeps non-JSON server errors readable', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      response('gateway failure', {
        status: 502,
        statusText: 'Bad Gateway',
        headers: { 'Content-Type': 'text/plain' },
      }),
    )
    await expect(api.me()).rejects.toThrow('gateway failure')
  })

  it('refreshes an expired session once and retries the original request', async () => {
    setTokens('old-access', 'refresh-token')
    vi.mocked(fetch)
      .mockResolvedValueOnce(response({}, { status: 401 }))
      .mockResolvedValueOnce(response({ data: { access_token: 'new-access', refresh_token: 'new-refresh' } }))
      .mockResolvedValueOnce(response({ id: 1 }))

    await expect(api.me()).resolves.toEqual({ id: 1 })
    expect(localStorage.getItem('modstore_token')).toBe('new-access')
    expect(localStorage.getItem('modstore_refresh_token')).toBe('new-refresh')
  })

  it.each([
    [response({}, { status: 401 }), 'refresh failed: 401'],
    [response({}, { status: 200 }), 'no access_token in refresh response'],
  ])('clears credentials when refresh cannot recover %#', async (refreshResponse) => {
    setTokens('old-access', 'refresh-token')
    vi.mocked(fetch)
      .mockResolvedValueOnce(response({}, { status: 401 }))
      .mockResolvedValueOnce(refreshResponse)
    await expect(api.me()).rejects.toThrow('会话已过期，请重新登录')
    expect(localStorage.getItem('modstore_token')).toBeNull()
    expect(localStorage.getItem('modstore_refresh_token')).toBeNull()
  })

  it('rejects failed imports and downloads', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(response({ detail: 'bad archive' }, { status: 400 }))
      .mockResolvedValueOnce(response('download failed', { status: 404 }))
    await expect(api.importZIP(new File(['bad'], 'bad.zip'))).rejects.toThrow('bad archive')
    await expect(api.downloadItem(404)).rejects.toThrow('download failed')
  })

  it('drops expired JWTs but keeps opaque and malformed tokens', async () => {
    const encode = (value: unknown) => btoa(JSON.stringify(value)).replace(/=/g, '')
    const expired = `a.${encode({ exp: 1 })}.c`
    localStorage.setItem('modstore_token', expired)
    await api.me()
    expect(localStorage.getItem('modstore_token')).toBeNull()

    for (const token of ['opaque', 'a.not-json.c', `a.${encode({ sub: 'user' })}.c`]) {
      localStorage.setItem('modstore_token', token)
      await api.me()
      const headers = vi.mocked(fetch).mock.calls.at(-1)?.[1]?.headers as Record<string, string>
      expect(headers.Authorization).toBe(`Bearer ${token}`)
    }
  })
})
