import { describe, expect, it, vi, beforeEach } from 'vitest'
import * as authApi from './authApi'
import { requestJson } from '../infrastructure/http/client'
import { setAuthTokens } from '../infrastructure/storage/tokenStore'

vi.mock('../infrastructure/http/client', () => ({
  requestJson: vi.fn(),
}))

vi.mock('../infrastructure/storage/tokenStore', () => ({
  setAuthTokens: vi.fn(),
}))

describe('authApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('login calls requestJson with POST and sets tokens', async () => {
    const tokens = { access_token: 'at', refresh_token: 'rt' }
    vi.mocked(requestJson).mockResolvedValue(tokens)
    const result = await authApi.login('user', 'pass')
    expect(requestJson).toHaveBeenCalledWith('/api/auth/login', expect.objectContaining({ method: 'POST' }))
    expect(setAuthTokens).toHaveBeenCalledWith(tokens)
    expect(result).toEqual(tokens)
  })

  it('me calls requestJson with GET', async () => {
    vi.mocked(requestJson).mockResolvedValue({ id: 1, username: 'test' })
    const result = await authApi.me()
    expect(requestJson).toHaveBeenCalledWith('/api/auth/me')
    expect(result).toEqual({ id: 1, username: 'test' })
  })
})
