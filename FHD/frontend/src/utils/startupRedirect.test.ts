import { describe, it, expect } from 'vitest'
import { safeRedirectFromLocation, normalizeLoginRedirect, buildLoginLocation } from './startupRedirect'

describe('startupRedirect', () => {
  it('returns full path for non-login routes', () => {
    expect(safeRedirectFromLocation({ pathname: '/chat', search: '?tab=1', hash: '#x' })).toBe('/chat?tab=1#x')
  })

  it('unwraps nested login redirect chains', () => {
    const nested = encodeURIComponent('/login?redirect=' + encodeURIComponent('/dashboard'))
    expect(
      safeRedirectFromLocation({
        pathname: '/login',
        search: `?redirect=${nested}`,
      }),
    ).toBe('/dashboard')
  })

  it('falls back to / for invalid nested login redirects', () => {
    expect(safeRedirectFromLocation({ pathname: '/login', search: '?redirect=%2Flogin' })).toBe('/')
  })

  it('normalizes unsafe redirect targets', () => {
    expect(normalizeLoginRedirect('//evil')).toBe('/')
    expect(normalizeLoginRedirect('/login')).toBe('/')
    expect(normalizeLoginRedirect('/mods')).toBe('/mods')
  })

  it('builds login route with sanitized redirect', () => {
    expect(buildLoginLocation({ pathname: '/chat', search: '', hash: '' })).toEqual({
      name: 'login',
      query: { redirect: '/chat' },
    })
  })
})

describe('admin SPA mount redirects', () => {
  it.each(['/admin/xcmax-admin', '/admin/customer-service-tickets/41'])(
    'strips one complete mount prefix from %s', (pathname) => {
      const result = buildLoginLocation({ pathname }, '/admin/')
      expect(result.query.redirect).toBe(pathname.slice('/admin'.length))
    },
  )

  it('unwraps existing base-prefixed login redirects', () => {
    expect(buildLoginLocation({ pathname: '/admin/login', search: '?redirect=%2Fadmin%2Fcustomer-service-tickets%2F41' }, '/admin/').query.redirect)
      .toBe('/customer-service-tickets/41')
  })

  it('does not strip a lookalike prefix or alter root-host routes', () => {
    expect(normalizeLoginRedirect('/administrator/settings', '/admin/')).toBe('/administrator/settings')
    expect(normalizeLoginRedirect('/admin/settings', '/')).toBe('/admin/settings')
  })

  it.each(['/admin//evil.example', '/admin/\\evil.example', '/admin/login', '/admin/login?redirect=/admin/login'])('rejects unsafe or recursive target %s after stripping the mount', (target) => {
    expect(normalizeLoginRedirect(target, '/admin/')).toBe('/')
  })
})
