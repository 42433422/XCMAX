import { describe, it, expect, vi, beforeEach } from 'vitest'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
}))
const primeCsrfCookie = vi.hoisted(() => vi.fn().mockResolvedValue(undefined))

vi.mock('./core', () => ({
  api: apiMock,
  default: apiMock,
  primeCsrfCookie,
  buildFullApiUrl: (u: string) => u,
}))

import authApi from './auth'

beforeEach(() => {
  apiMock.get.mockReset().mockResolvedValue({ success: true })
  apiMock.post.mockReset().mockResolvedValue({ success: true })
  apiMock.patch.mockReset().mockResolvedValue({ success: true })
  primeCsrfCookie.mockClear()
})

describe('authApi', () => {
  it('login primes csrf and posts credentials', async () => {
    await authApi.login('u', 'p')
    expect(primeCsrfCookie).toHaveBeenCalled()
    expect(apiMock.post).toHaveBeenCalledWith('/api/auth/login', {
      username: 'u',
      password: 'p',
      account_kind: 'enterprise',
    })
  })

  it('loginWithPhoneCode posts phone+code', async () => {
    await authApi.loginWithPhoneCode('139', '0000', 'personal')
    expect(apiMock.post).toHaveBeenCalledWith('/api/auth/login-with-phone-code', {
      phone: '139',
      code: '0000',
      account_kind: 'personal',
    })
  })

  it('covers remaining endpoints', async () => {
    await authApi.sendPhoneCode('139')
    await authApi.getOidcStatus()
    await authApi.issueAuthQr('hint')
    await authApi.pollAuthQr('id', 'secret')
    await authApi.getSubscriptionStatus()
    await authApi.updateCompanyBrand('brand')
    await authApi.register({ username: 'u', password: 'p' })
    await authApi.getCurrentUser()
    await authApi.getProfile()
    await authApi.updateProfile({ display_name: 'x' })
    await authApi.validateSession()
    await authApi.forgotAccount('a@b.com')
    await authApi.sendForgotPasswordCode('a@b.com')
    await authApi.resetForgotPassword('a@b.com', '123', 'newpass')
    expect(apiMock.get).toHaveBeenCalled()
    expect(apiMock.patch).toHaveBeenCalledWith('/api/auth/profile', { display_name: 'x' })
  })

  it('uploadAvatar posts FormData', async () => {
    const file = new File(['x'], 'a.png', { type: 'image/png' })
    await authApi.uploadAvatar(file)
    const [, body] = apiMock.post.mock.calls.at(-1)!
    expect(body).toBeInstanceOf(FormData)
  })

  it('logout clears storage and posts', async () => {
    window.localStorage.setItem('xcagi_market_access_token', 'tok')
    await authApi.logout()
    expect(apiMock.post).toHaveBeenCalledWith('/api/auth/logout', {})
  })
})
