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
})
