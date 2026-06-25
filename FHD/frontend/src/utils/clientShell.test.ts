import { describe, it, expect, beforeEach, vi } from 'vitest'
import { resolveClientShellId, clientShellRequestHeaders } from './clientShell'

describe('clientShell', () => {
  beforeEach(() => {
    vi.unstubAllEnvs()
  })

  describe('resolveClientShellId', () => {
    it('returns enterprise when not admin console', () => {
      vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '')
      expect(resolveClientShellId()).toBe('enterprise')
    })

    it('returns admin when VITE_XCMAX_ADMIN_CONSOLE is 1', () => {
      vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '1')
      expect(resolveClientShellId()).toBe('admin')
    })

    it('returns enterprise when VITE_XCMAX_ADMIN_CONSOLE is 0', () => {
      vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '0')
      expect(resolveClientShellId()).toBe('enterprise')
    })

    it('returns enterprise when VITE_XCMAX_ADMIN_CONSOLE is empty string', () => {
      vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '')
      expect(resolveClientShellId()).toBe('enterprise')
    })

    it('returns enterprise when VITE_XCMAX_ADMIN_CONSOLE is whitespace', () => {
      vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '   ')
      expect(resolveClientShellId()).toBe('enterprise')
    })
  })

  describe('clientShellRequestHeaders', () => {
    it('returns enterprise header by default', () => {
      vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '')
      const headers = clientShellRequestHeaders()
      expect(headers).toEqual({ 'X-XCMAX-Client-Shell': 'enterprise' })
    })

    it('returns admin header when admin console', () => {
      vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '1')
      const headers = clientShellRequestHeaders()
      expect(headers).toEqual({ 'X-XCMAX-Client-Shell': 'admin' })
    })

    it('header key is X-XCMAX-Client-Shell', () => {
      vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '')
      const headers = clientShellRequestHeaders()
      expect(headers).toHaveProperty('X-XCMAX-Client-Shell')
    })

    it('header value matches resolveClientShellId', () => {
      vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '1')
      const headers = clientShellRequestHeaders()
      expect(headers['X-XCMAX-Client-Shell']).toBe(resolveClientShellId())
    })
  })
})
