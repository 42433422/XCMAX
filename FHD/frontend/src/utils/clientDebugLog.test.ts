import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'

const apiFetchMock = vi.fn()
vi.mock('@/utils/apiBase', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}))

const STORAGE_KEY = 'xcagi_client_debug_log'

let postClientDebugLog: (payload: Record<string, unknown>) => void
let installClientConsoleBridge: () => void

describe('clientDebugLog', () => {
  beforeEach(async () => {
    apiFetchMock.mockReset()
    localStorage.clear()
    vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    // Reset module-level state (bridgeForbidden, posting, queue) between tests
    vi.resetModules()
    const mod = await import('./clientDebugLog')
    postClientDebugLog = mod.postClientDebugLog
    installClientConsoleBridge = mod.installClientConsoleBridge
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('postClientDebugLog', () => {
    it('does not post when bridge disabled via localStorage=0', () => {
      localStorage.setItem(STORAGE_KEY, '0')
      postClientDebugLog({ message: 'test' })
      expect(apiFetchMock).not.toHaveBeenCalled()
    })

    it('posts when bridge enabled via localStorage=1', () => {
      localStorage.setItem(STORAGE_KEY, '1')
      apiFetchMock.mockResolvedValue({ ok: true, status: 200 })
      postClientDebugLog({ message: 'test' })
      expect(apiFetchMock).toHaveBeenCalled()
    })

    it('posts payload to /api/debug/client-log', () => {
      localStorage.setItem(STORAGE_KEY, '1')
      apiFetchMock.mockResolvedValue({ ok: true, status: 200 })
      const payload = { message: 'error msg', level: 'error' }
      postClientDebugLog(payload)
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/debug/client-log',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        }),
      )
    })

    it('stops posting after 403 response', async () => {
      localStorage.setItem(STORAGE_KEY, '1')
      apiFetchMock.mockResolvedValue({ ok: false, status: 403 })
      postClientDebugLog({ message: 'first' })
      // Wait for async
      await new Promise((r) => setTimeout(r, 10))
      postClientDebugLog({ message: 'second' })
      await new Promise((r) => setTimeout(r, 10))
      // Only first call should have been made
      expect(apiFetchMock).toHaveBeenCalledTimes(1)
    })

    it('stops posting after 404 response', async () => {
      localStorage.setItem(STORAGE_KEY, '1')
      apiFetchMock.mockResolvedValue({ ok: false, status: 404 })
      postClientDebugLog({ message: 'first' })
      await new Promise((r) => setTimeout(r, 10))
      postClientDebugLog({ message: 'second' })
      await new Promise((r) => setTimeout(r, 10))
      expect(apiFetchMock).toHaveBeenCalledTimes(1)
    })

    it('continues posting after 200 response', async () => {
      localStorage.setItem(STORAGE_KEY, '1')
      apiFetchMock.mockResolvedValue({ ok: true, status: 200 })
      postClientDebugLog({ message: 'first' })
      await new Promise((r) => setTimeout(r, 10))
      postClientDebugLog({ message: 'second' })
      await new Promise((r) => setTimeout(r, 10))
      expect(apiFetchMock).toHaveBeenCalledTimes(2)
    })

    it('handles fetch rejection gracefully', async () => {
      localStorage.setItem(STORAGE_KEY, '1')
      apiFetchMock.mockRejectedValue(new Error('network'))
      postClientDebugLog({ message: 'test' })
      // Should not throw
      await new Promise((r) => setTimeout(r, 10))
      expect(apiFetchMock).toHaveBeenCalled()
    })
  })

  describe('installClientConsoleBridge', () => {
    it('does not install when bridge disabled', () => {
      localStorage.setItem(STORAGE_KEY, '0')
      const originalError = console.error
      installClientConsoleBridge()
      // console.error should be unchanged (same reference)
      expect(console.error).toBe(originalError)
    })

    it('installs console.error and console.warn overrides when enabled', () => {
      localStorage.setItem(STORAGE_KEY, '1')
      apiFetchMock.mockResolvedValue({ ok: true, status: 200 })
      const originalError = console.error
      const originalWarn = console.warn
      installClientConsoleBridge()
      // console.error should be overridden (different reference)
      expect(console.error).not.toBe(originalError)
      expect(console.warn).not.toBe(originalWarn)
      // Calling console.error should trigger post
      console.error('test error')
      expect(apiFetchMock).toHaveBeenCalled()
    })

    it('console.error override calls original error', () => {
      localStorage.setItem(STORAGE_KEY, '1')
      apiFetchMock.mockResolvedValue({ ok: true, status: 200 })
      const mockOrigError = vi.fn()
      console.error = mockOrigError
      installClientConsoleBridge()
      console.error('test message')
      expect(mockOrigError).toHaveBeenCalledWith('test message')
    })

    it('console.warn override calls original warn', () => {
      localStorage.setItem(STORAGE_KEY, '1')
      apiFetchMock.mockResolvedValue({ ok: true, status: 200 })
      const mockOrigWarn = vi.fn()
      console.warn = mockOrigWarn
      installClientConsoleBridge()
      console.warn('warn message')
      expect(mockOrigWarn).toHaveBeenCalledWith('warn message')
    })

    it('handles Error objects in console.error', () => {
      localStorage.setItem(STORAGE_KEY, '1')
      apiFetchMock.mockResolvedValue({ ok: true, status: 200 })
      const mockOrigError = vi.fn()
      console.error = mockOrigError
      installClientConsoleBridge()
      const err = new Error('test error')
      console.error(err)
      expect(mockOrigError).toHaveBeenCalledWith(err)
      expect(apiFetchMock).toHaveBeenCalled()
      // Verify the body contains the error stack
      const call = apiFetchMock.mock.calls[0]
      const body = JSON.parse(call[1].body)
      expect(body.message).toContain('test error')
    })

    it('handles object arguments in console.error', () => {
      localStorage.setItem(STORAGE_KEY, '1')
      apiFetchMock.mockResolvedValue({ ok: true, status: 200 })
      const mockOrigError = vi.fn()
      console.error = mockOrigError
      installClientConsoleBridge()
      console.error({ key: 'value' })
      expect(apiFetchMock).toHaveBeenCalled()
      const call = apiFetchMock.mock.calls[0]
      const body = JSON.parse(call[1].body)
      expect(body.message).toContain('key')
    })
  })
})
