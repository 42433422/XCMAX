import { describe, it, expect } from 'vitest'
import {
  safeRedirectFromLocation,
  normalizeLoginRedirect,
  buildLoginLocation,
} from './startupRedirect'

describe('startupRedirect', () => {
  it('returns full path for non-login routes', () => {
    expect(
      safeRedirectFromLocation({ pathname: '/chat', search: '?tab=1', hash: '#x' })
    ).toBe('/chat?tab=1#x')
  })

  it('unwraps nested login redirect chains', () => {
    const nested = encodeURIComponent('/login?redirect=' + encodeURIComponent('/dashboard'))
    expect(
      safeRedirectFromLocation({
        pathname: '/login',
        search: `?redirect=${nested}`,
      })
    ).toBe('/dashboard')
  })

  it('falls back to / for invalid nested login redirects', () => {
    expect(
      safeRedirectFromLocation({ pathname: '/login', search: '?redirect=%2Flogin' })
    ).toBe('/')
  })

  it('normalizes unsafe redirect targets', () => {
    expect(normalizeLoginRedirect('//evil')).toBe('/')
    expect(normalizeLoginRedirect('/login')).toBe('/')
    expect(normalizeLoginRedirect('/mods')).toBe('/mods')
  })

  it('builds login route with sanitized redirect', () => {
    expect(
      buildLoginLocation({ pathname: '/chat', search: '', hash: '' })
    ).toEqual({ name: 'login', query: { redirect: '/chat' } })
  })
})
