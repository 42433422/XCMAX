import { beforeEach, describe, expect, it, vi } from 'vitest'

const {
  primeCsrfCookieMock,
  readCsrfTokenFromCookieMock,
  shouldAttachCsrfHeaderMock,
  clientShellRequestHeadersMock,
} = vi.hoisted(() => ({
  primeCsrfCookieMock: vi.fn(),
  readCsrfTokenFromCookieMock: vi.fn(),
  shouldAttachCsrfHeaderMock: vi.fn(),
  clientShellRequestHeadersMock: vi.fn(),
}))

vi.mock('@/api/core', () => ({ primeCsrfCookie: primeCsrfCookieMock }))
vi.mock('@/api/marketAccount', () => ({ LS_MARKET_ACCESS_TOKEN: 'xcagi_market_access_token' }))
vi.mock('@/utils/clientShell', () => ({ clientShellRequestHeaders: clientShellRequestHeadersMock }))
vi.mock('@/utils/csrfCookie', () => ({
  readCsrfTokenFromCookie: readCsrfTokenFromCookieMock,
  shouldAttachCsrfHeader: shouldAttachCsrfHeaderMock,
}))

import { authenticatedRequestInit } from './authenticatedRequest'

describe('authenticatedRequestInit', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
    primeCsrfCookieMock.mockResolvedValue(undefined)
    readCsrfTokenFromCookieMock.mockReturnValue('')
    clientShellRequestHeadersMock.mockReturnValue({ 'X-XCMAX-Client-Shell': 'enterprise' })
    shouldAttachCsrfHeaderMock.mockImplementation((method: string, headers: Record<string, string>) => (
      !['GET', 'HEAD', 'OPTIONS'].includes(method.toUpperCase())
      && !Object.keys(headers).some((key) => (
        key.toLowerCase() === 'authorization'
        && headers[key].toLowerCase().startsWith('bearer ')
      ))
    ))
  })

  it('uses the market bearer and included credentials without priming CSRF', async () => {
    localStorage.setItem('xcagi_market_access_token', 'market-token')

    const init = await authenticatedRequestInit('POST', { 'Content-Type': 'application/json' })

    expect(init).toEqual({
      credentials: 'include',
      headers: {
        'X-XCMAX-Client-Shell': 'enterprise',
        'Content-Type': 'application/json',
        Authorization: 'Bearer market-token',
      },
    })
    expect(primeCsrfCookieMock).not.toHaveBeenCalled()
  })

  it('primes a cookie session and attaches the resulting CSRF token', async () => {
    readCsrfTokenFromCookieMock
      .mockReturnValueOnce('')
      .mockReturnValue('csrf-after-prime')

    const init = await authenticatedRequestInit('POST', { 'Content-Type': 'application/json' })

    expect(primeCsrfCookieMock).toHaveBeenCalledOnce()
    expect(init.credentials).toBe('include')
    expect(init.headers['X-CSRF-Token']).toBe('csrf-after-prime')
    expect(init.headers.Authorization).toBeUndefined()
  })

  it('preserves an explicit bearer instead of replacing it with the stored market token', async () => {
    localStorage.setItem('xcagi_market_access_token', 'market-token')

    const init = await authenticatedRequestInit('POST', {
      authorization: 'Bearer explicit-token',
    })

    expect(init.headers.authorization).toBe('Bearer explicit-token')
    expect(init.headers.Authorization).toBeUndefined()
    expect(primeCsrfCookieMock).not.toHaveBeenCalled()
  })
})
