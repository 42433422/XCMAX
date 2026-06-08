import { describe, expect, it, vi, beforeEach } from 'vitest'
import { auth } from './auth'
import { req, authRequest, setTokensFromAuthResponse } from './shared'

vi.mock('./shared', () => ({
  req: vi.fn(),
  authRequest: vi.fn(),
  setTokensFromAuthResponse: vi.fn(),
}))

beforeEach(() => {
  vi.clearAllMocks()
})

describe('auth api', () => {

  it('register calls authRequest and setTokensFromAuthResponse', async () => {
    vi.mocked(authRequest).mockResolvedValue({ access_token: 'at', user: { id: 1 } })
    await auth.register('u', 'p', 'e@e.com', '1234')
    expect(authRequest).toHaveBeenCalledWith('/api/auth/register', expect.objectContaining({ method: 'POST' }))
    expect(setTokensFromAuthResponse).toHaveBeenCalled()
  })

  it('register omits verificationCode when empty', async () => {
    vi.mocked(authRequest).mockResolvedValue({ access_token: 'at' })
    await auth.register('u', 'p', 'e@e.com')
    const call = vi.mocked(authRequest).mock.calls[0] as any[]
    const body = JSON.parse(call[1].body as string)
    expect(body.verification_code).toBe('')
  })

  it('login calls authRequest and setTokensFromAuthResponse', async () => {
    vi.mocked(authRequest).mockResolvedValue({ access_token: 'at' })
    await auth.login('u', 'p')
    expect(authRequest).toHaveBeenCalledWith('/api/auth/login', expect.objectContaining({ method: 'POST' }))
    expect(setTokensFromAuthResponse).toHaveBeenCalled()
  })

  it('loginWithCode calls authRequest and setTokensFromAuthResponse', async () => {
    vi.mocked(authRequest).mockResolvedValue({ access_token: 'at' })
    await auth.loginWithCode('e@e.com', '123456')
    expect(authRequest).toHaveBeenCalledWith('/api/auth/login-with-code', expect.objectContaining({ method: 'POST' }))
    expect(setTokensFromAuthResponse).toHaveBeenCalled()
  })

  it('loginWithPhoneCode calls authRequest and setTokensFromAuthResponse', async () => {
    vi.mocked(authRequest).mockResolvedValue({ access_token: 'at' })
    await auth.loginWithPhoneCode('13800000000', '654321')
    expect(authRequest).toHaveBeenCalledWith('/api/auth/login-with-phone-code', expect.objectContaining({ method: 'POST' }))
    expect(setTokensFromAuthResponse).toHaveBeenCalled()
  })

  it('me calls req with /api/auth/me', async () => {
    vi.mocked(req).mockResolvedValue({ id: 1, username: 'admin' })
    const res = await auth.me()
    expect(req).toHaveBeenCalledWith('/api/auth/me')
    expect(res).toEqual({ id: 1, username: 'admin' })
  })

  it('sendPhoneCode calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await auth.sendPhoneCode('13800000000')
    expect(req).toHaveBeenCalledWith('/api/auth/send-phone-code', expect.objectContaining({ method: 'POST' }))
  })

  it('accountBootstrap calls req', async () => {
    vi.mocked(req).mockResolvedValue({})
    await auth.accountBootstrap()
    expect(req).toHaveBeenCalledWith('/api/account/bootstrap')
  })

  it('sendVerificationCode calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await auth.sendVerificationCode('e@e.com')
    expect(req).toHaveBeenCalledWith('/api/auth/send-code', expect.objectContaining({ method: 'POST' }))
  })

  it('sendRegisterVerificationCode calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await auth.sendRegisterVerificationCode('e@e.com')
    expect(req).toHaveBeenCalledWith('/api/auth/send-register-code', expect.objectContaining({ method: 'POST' }))
  })

  it('sendResetPasswordCode calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await auth.sendResetPasswordCode('e@e.com')
    expect(req).toHaveBeenCalledWith('/api/auth/send-reset-password-code', expect.objectContaining({ method: 'POST' }))
  })

  it('resetPassword calls req with POST and correct body', async () => {
    vi.mocked(req).mockResolvedValue({})
    await auth.resetPassword('e@e.com', 'code123', 'newPass')
    expect(req).toHaveBeenCalledWith('/api/auth/reset-password', expect.objectContaining({ method: 'POST' }))
    const call = vi.mocked(req).mock.calls[0] as any[]
    const body = JSON.parse(call[1].body as string)
    expect(body.email).toBe('e@e.com')
    expect(body.new_password).toBe('newPass')
  })

  it('submitLandingContact fills defaults for optional fields', async () => {
    vi.mocked(req).mockResolvedValue({})
    await auth.submitLandingContact({ name: 'n', email: 'e@e.com' })
    const call = vi.mocked(req).mock.calls[0] as any[]
    const body = JSON.parse(call[1].body as string)
    expect(body.phone).toBe('')
    expect(body.company).toBe('')
    expect(body.message).toBe('')
    expect(body.source).toBe('home')
  })

  it('submitLandingContact uses provided optional fields', async () => {
    vi.mocked(req).mockResolvedValue({})
    await auth.submitLandingContact({ name: 'n', email: 'e@e.com', phone: '1', company: 'c', message: 'm', source: 'landing' })
    const call = vi.mocked(req).mock.calls[0] as any[]
    const body = JSON.parse(call[1].body as string)
    expect(body.phone).toBe('1')
    expect(body.source).toBe('landing')
  })

  it('updateProfile calls req with PUT', async () => {
    vi.mocked(req).mockResolvedValue({})
    await auth.updateProfile('newName')
    expect(req).toHaveBeenCalledWith('/api/auth/profile', expect.objectContaining({ method: 'PUT' }))
  })

  it('changePassword calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await auth.changePassword('old', 'new')
    expect(req).toHaveBeenCalledWith('/api/auth/change-password', expect.objectContaining({ method: 'POST' }))
  })
})
