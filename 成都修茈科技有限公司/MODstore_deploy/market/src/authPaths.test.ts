import { describe, expect, it } from 'vitest'
import { safeRedirectPath, pickRedirectFromRoute, DEFAULT_POST_AUTH } from './authPaths'

describe('safeRedirectPath', () => {
  it('returns default for non-string input', () => {
    expect(safeRedirectPath(null)).toBe('/workbench/home')
    expect(safeRedirectPath(undefined)).toBe('/workbench/home')
    expect(safeRedirectPath(42)).toBe('/workbench/home')
  })

  it('returns default for non-absolute paths', () => {
    expect(safeRedirectPath('relative/path')).toBe('/workbench/home')
  })

  it('returns default for double-slash paths', () => {
    expect(safeRedirectPath('//evil.com')).toBe('/workbench/home')
  })

  it('strips /market/ prefix', () => {
    expect(safeRedirectPath('/market/wallet')).toBe('/wallet')
  })

  it('converts /market to /', () => {
    expect(safeRedirectPath('/market')).toBe('/')
  })

  it('returns default for /', () => {
    expect(safeRedirectPath('/')).toBe('/workbench/home')
  })

  it('returns default for /index.html', () => {
    expect(safeRedirectPath('/index.html')).toBe('/workbench/home')
  })

  it('returns default for /login paths', () => {
    expect(safeRedirectPath('/login')).toBe('/workbench/home')
    expect(safeRedirectPath('/login-email')).toBe('/workbench/home')
  })

  it('returns default for SEO landing pages', () => {
    expect(safeRedirectPath('/about.html')).toBe('/workbench/home')
    expect(safeRedirectPath('/contact.html')).toBe('/workbench/home')
  })

  it('allows valid internal paths', () => {
    expect(safeRedirectPath('/wallet')).toBe('/wallet')
    expect(safeRedirectPath('/workbench/home')).toBe('/workbench/home')
    expect(safeRedirectPath('/plans')).toBe('/plans')
  })

  it('trims whitespace', () => {
    expect(safeRedirectPath('  /wallet  ')).toBe('/wallet')
  })
})

describe('DEFAULT_POST_AUTH', () => {
  it('points to workbench-home', () => {
    expect(DEFAULT_POST_AUTH).toEqual({ name: 'workbench-home' })
  })
})

describe('pickRedirectFromRoute', () => {
  it('returns redirect path from query', () => {
    const route = { query: { redirect: '/wallet' } }
    expect(pickRedirectFromRoute(route)).toBe('/wallet')
  })

  it('returns default when no redirect in query', () => {
    const route = { query: {} }
    expect(pickRedirectFromRoute(route)).toEqual(DEFAULT_POST_AUTH)
  })

  it('returns default for empty redirect', () => {
    const route = { query: { redirect: '' } }
    expect(pickRedirectFromRoute(route)).toEqual(DEFAULT_POST_AUTH)
  })

  it('handles array redirect query param', () => {
    const route = { query: { redirect: ['/wallet', '/plans'] } }
    expect(pickRedirectFromRoute(route)).toBe('/wallet')
  })

  it('sanitizes redirect path', () => {
    const route = { query: { redirect: '/login' } }
    expect(pickRedirectFromRoute(route)).toBe('/workbench/home')
  })
})
