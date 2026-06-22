import { describe, it, expect, vi, afterEach } from 'vitest'

import {
  isAdminConsoleSpa,
  resolveAdminConsoleLoginUrl,
  resolveAdminConsoleHomeUrl,
} from './adminConsoleUrl'

describe('adminConsoleUrl', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('isAdminConsoleSpa reads VITE_XCMAX_ADMIN_CONSOLE', () => {
    vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '1')
    expect(isAdminConsoleSpa()).toBe(true)
    vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '')
    expect(isAdminConsoleSpa()).toBe(false)
  })

  it('resolveAdminConsoleLoginUrl encodes redirect', () => {
    const url = resolveAdminConsoleLoginUrl('/xcmax-admin/users')
    expect(url).toContain('/admin/login')
    expect(url).toContain(encodeURIComponent('/xcmax-admin/users'))
  })

  it('resolveAdminConsoleHomeUrl points to xcmax-admin', () => {
    expect(resolveAdminConsoleHomeUrl()).toContain('/admin/xcmax-admin')
  })

  it('maps local development origins to the admin console dev port', () => {
    const original = window.location
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { protocol: 'http:', hostname: 'localhost', port: '5001', origin: 'http://localhost:5001' },
    })
    try {
      expect(resolveAdminConsoleHomeUrl()).toBe('http://localhost:5011/admin/xcmax-admin')
    } finally {
      Object.defineProperty(window, 'location', { configurable: true, value: original })
    }
  })

  it('uses explicit admin console origin when configured', () => {
    vi.stubEnv('VITE_ADMIN_CONSOLE_ORIGIN', 'http://127.0.0.1:7001/')
    expect(resolveAdminConsoleHomeUrl()).toBe('http://127.0.0.1:7001/admin/xcmax-admin')
  })
})
