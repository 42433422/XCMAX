import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import {
  isAdminConsoleSpa,
  resolveAdminConsoleOrigin,
  resolveAdminConsoleLoginUrl,
  resolveAdminConsoleHomeUrl,
} from './adminConsoleUrl'

describe('adminConsoleUrl', () => {
  beforeEach(() => {
    vi.unstubAllEnvs()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.restoreAllMocks()
  })

  describe('isAdminConsoleSpa', () => {
    it('returns false when VITE_XCMAX_ADMIN_CONSOLE is not set', () => {
      vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '')
      expect(isAdminConsoleSpa()).toBe(false)
    })

    it('returns true when VITE_XCMAX_ADMIN_CONSOLE is "1"', () => {
      vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '1')
      expect(isAdminConsoleSpa()).toBe(true)
    })

    it('returns false when VITE_XCMAX_ADMIN_CONSOLE is "0"', () => {
      vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '0')
      expect(isAdminConsoleSpa()).toBe(false)
    })

    it('returns false when VITE_XCMAX_ADMIN_CONSOLE is whitespace', () => {
      vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '  ')
      expect(isAdminConsoleSpa()).toBe(false)
    })
  })

  describe('resolveAdminConsoleOrigin', () => {
    it('returns env value when VITE_ADMIN_CONSOLE_ORIGIN is set', () => {
      vi.stubEnv('VITE_ADMIN_CONSOLE_ORIGIN', 'https://admin.example.com/')
      expect(resolveAdminConsoleOrigin()).toBe('https://admin.example.com')
    })

    it('strips single trailing slash from env value', () => {
      vi.stubEnv('VITE_ADMIN_CONSOLE_ORIGIN', 'https://admin.example.com/')
      expect(resolveAdminConsoleOrigin()).toBe('https://admin.example.com')
    })

    it('returns window.location.origin when env not set (default jsdom)', () => {
      vi.stubEnv('VITE_ADMIN_CONSOLE_ORIGIN', '')
      expect(resolveAdminConsoleOrigin()).toBe(window.location.origin)
    })
  })

  describe('resolveAdminConsoleLoginUrl', () => {
    it('returns login URL without redirect when no redirectPath', () => {
      vi.stubEnv('VITE_ADMIN_CONSOLE_ORIGIN', 'https://admin.example.com')
      expect(resolveAdminConsoleLoginUrl()).toBe('https://admin.example.com/admin/login')
    })

    it('returns login URL with redirect query when redirectPath starts with /', () => {
      vi.stubEnv('VITE_ADMIN_CONSOLE_ORIGIN', 'https://admin.example.com')
      const url = resolveAdminConsoleLoginUrl('/dashboard')
      expect(url).toContain('?redirect=')
      expect(url).toContain(encodeURIComponent('/dashboard'))
    })

    it('does not add redirect when redirectPath does not start with /', () => {
      vi.stubEnv('VITE_ADMIN_CONSOLE_ORIGIN', 'https://admin.example.com')
      expect(resolveAdminConsoleLoginUrl('dashboard')).toBe('https://admin.example.com/admin/login')
    })

    it('does not add redirect when redirectPath starts with //', () => {
      vi.stubEnv('VITE_ADMIN_CONSOLE_ORIGIN', 'https://admin.example.com')
      expect(resolveAdminConsoleLoginUrl('//evil.com')).toBe('https://admin.example.com/admin/login')
    })

    it('handles empty redirectPath', () => {
      vi.stubEnv('VITE_ADMIN_CONSOLE_ORIGIN', 'https://admin.example.com')
      expect(resolveAdminConsoleLoginUrl('')).toBe('https://admin.example.com/admin/login')
    })

    it('handles whitespace-only redirectPath', () => {
      vi.stubEnv('VITE_ADMIN_CONSOLE_ORIGIN', 'https://admin.example.com')
      expect(resolveAdminConsoleLoginUrl('   ')).toBe('https://admin.example.com/admin/login')
    })
  })

  describe('resolveAdminConsoleHomeUrl', () => {
    it('returns admin home URL', () => {
      vi.stubEnv('VITE_ADMIN_CONSOLE_ORIGIN', 'https://admin.example.com')
      expect(resolveAdminConsoleHomeUrl()).toBe('https://admin.example.com/admin/xcmax-admin')
    })
  })
})
