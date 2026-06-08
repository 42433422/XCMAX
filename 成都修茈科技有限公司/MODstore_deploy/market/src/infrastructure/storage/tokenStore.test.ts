import { describe, expect, it } from 'vitest'
import {
  ACCESS_TOKEN_KEY,
  REFRESH_TOKEN_KEY,
  clearAuthTokens,
  getAccessToken,
  getRefreshToken,
  setAuthTokens,
} from './tokenStore'

describe('tokenStore', () => {
  it('stores and clears access and refresh tokens', () => {
    setAuthTokens({ access_token: 'access-1', refresh_token: 'refresh-1' })

    expect(getAccessToken()).toBe('access-1')
    expect(getRefreshToken()).toBe('refresh-1')
    expect(localStorage.getItem(ACCESS_TOKEN_KEY)).toBe('access-1')
    expect(localStorage.getItem(REFRESH_TOKEN_KEY)).toBe('refresh-1')

    clearAuthTokens()

    expect(getAccessToken()).toBe('')
    expect(getRefreshToken()).toBe('')
  })

  it('ignores missing token fields', () => {
    setAuthTokens(null)
    setAuthTokens({})

    expect(getAccessToken()).toBe('')
    expect(getRefreshToken()).toBe('')
  })

  it('only sets access_token when refresh_token is missing', () => {
    clearAuthTokens()
    setAuthTokens({ access_token: 'only-access' })
    expect(getAccessToken()).toBe('only-access')
    expect(getRefreshToken()).toBe('')
  })

  it('only sets refresh_token when access_token is missing', () => {
    clearAuthTokens()
    setAuthTokens({ refresh_token: 'only-refresh' })
    expect(getAccessToken()).toBe('')
    expect(getRefreshToken()).toBe('only-refresh')
  })

  it('does not set empty string tokens', () => {
    clearAuthTokens()
    localStorage.setItem(ACCESS_TOKEN_KEY, 'existing')
    setAuthTokens({ access_token: '', refresh_token: '' })
    expect(getAccessToken()).toBe('existing')
  })

  it('does not set undefined tokens', () => {
    clearAuthTokens()
    setAuthTokens({ access_token: undefined as any, refresh_token: undefined as any })
    expect(getAccessToken()).toBe('')
    expect(getRefreshToken()).toBe('')
  })

  it('getAccessToken returns empty string when no token', () => {
    clearAuthTokens()
    expect(getAccessToken()).toBe('')
  })

  it('getRefreshToken returns empty string when no token', () => {
    clearAuthTokens()
    expect(getRefreshToken()).toBe('')
  })
})
