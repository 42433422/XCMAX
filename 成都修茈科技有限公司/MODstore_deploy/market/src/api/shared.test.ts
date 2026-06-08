import { describe, expect, it, vi } from 'vitest'
import { setTokensFromAuthResponse, catalogWriteHeaders, authHeaders, authRequest } from './shared'

vi.mock('../infrastructure/http/client', () => ({
  requestJson: vi.fn(() => Promise.resolve({})),
  fetchZipBlob: vi.fn(),
  requestBlob: vi.fn(),
}))

vi.mock('../infrastructure/storage/tokenStore', () => ({
  getAccessToken: vi.fn(() => 'test-token'),
  setAuthTokens: vi.fn(),
}))

import { getAccessToken, setAuthTokens } from '../infrastructure/storage/tokenStore'
import { requestJson } from '../infrastructure/http/client'

describe('shared API helpers', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('setTokensFromAuthResponse calls setAuthTokens', () => {
    const res = { access_token: 'a', refresh_token: 'r' }
    setTokensFromAuthResponse(res)
    expect(setAuthTokens).toHaveBeenCalledWith(res)
  })

  it('setTokensFromAuthResponse handles null', () => {
    setTokensFromAuthResponse(null)
    expect(setAuthTokens).toHaveBeenCalledWith(null)
  })

  it('setTokensFromAuthResponse handles undefined', () => {
    setTokensFromAuthResponse(undefined)
    expect(setAuthTokens).toHaveBeenCalledWith(undefined)
  })

  it('authHeaders returns Authorization header when token exists', () => {
    vi.mocked(getAccessToken).mockReturnValue('my-token')
    const headers = authHeaders()
    expect(headers).toEqual({ Authorization: 'Bearer my-token' })
  })

  it('authHeaders returns undefined when no token', () => {
    vi.mocked(getAccessToken).mockReturnValue(null)
    const headers = authHeaders()
    expect(headers).toBeUndefined()
  })

  it('catalogWriteHeaders returns header when env var set', () => {
    vi.stubEnv('VITE_MODSTORE_CATALOG_UPLOAD_TOKEN', 'tok123')
    const headers = catalogWriteHeaders()
    expect(headers).toEqual({ Authorization: 'Bearer tok123' })
    vi.unstubAllEnvs()
  })

  it('catalogWriteHeaders returns undefined when env var empty', () => {
    vi.stubEnv('VITE_MODSTORE_CATALOG_UPLOAD_TOKEN', '')
    const headers = catalogWriteHeaders()
    expect(headers).toBeUndefined()
    vi.unstubAllEnvs()
  })

  it('authRequest delegates to requestJson', async () => {
    await authRequest('/api/test', { method: 'POST' })
    expect(requestJson).toHaveBeenCalledWith('/api/test', { method: 'POST' })
  })

  it('authRequest delegates with default init', async () => {
    await authRequest('/api/test')
    expect(requestJson).toHaveBeenCalledWith('/api/test', {})
  })
})
