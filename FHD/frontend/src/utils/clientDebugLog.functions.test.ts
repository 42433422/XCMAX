import { describe, it, expect, vi, beforeEach } from 'vitest'

const { mockApiFetch } = vi.hoisted(() => ({
  mockApiFetch: vi.fn(),
}))

vi.mock('./apiBase', () => ({
  apiFetch: mockApiFetch,
}))

import type { postClientDebugLog as PostClientDebugLog, installClientConsoleBridge as InstallClientConsoleBridge } from './clientDebugLog'

async function loadModule() {
  vi.resetModules()
  vi.doMock('./apiBase', () => ({ apiFetch: mockApiFetch }))
  return (await import('./clientDebugLog')) as {
    postClientDebugLog: typeof PostClientDebugLog
    installClientConsoleBridge: typeof InstallClientConsoleBridge
  }
}

describe('clientDebugLog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    vi.resetModules()
  })

  describe('postClientDebugLog', () => {
    it('does not throw when called with bridge disabled', async () => {
      localStorage.setItem('xcagi_client_debug_log', '0')
      const { postClientDebugLog } = await loadModule()
      expect(() => postClientDebugLog({ msg: 'test' })).not.toThrow()
    })

    it('calls apiFetch when bridge is enabled via localStorage', async () => {
      localStorage.setItem('xcagi_client_debug_log', '1')
      mockApiFetch.mockResolvedValue({ status: 200, ok: true })
      const { postClientDebugLog } = await loadModule()
      postClientDebugLog({ msg: 'test log' })
      await vi.waitFor(() => {
        expect(mockApiFetch).toHaveBeenCalled()
      })
    })

    it('does not call apiFetch when bridge disabled via localStorage', async () => {
      localStorage.setItem('xcagi_client_debug_log', '0')
      mockApiFetch.mockClear()
      const { postClientDebugLog } = await loadModule()
      postClientDebugLog({ msg: 'test log' })
      await new Promise((r) => setTimeout(r, 50))
      expect(mockApiFetch).not.toHaveBeenCalled()
    })

    it('stops posting after 403 response (bridgeForbidden)', async () => {
      localStorage.setItem('xcagi_client_debug_log', '1')
      mockApiFetch.mockResolvedValue({ status: 403, ok: false })
      const { postClientDebugLog } = await loadModule()
      postClientDebugLog({ msg: 'first' })
      await vi.waitFor(() => {
        expect(mockApiFetch).toHaveBeenCalledTimes(1)
      })
      await new Promise((r) => setTimeout(r, 50))
      mockApiFetch.mockClear()
      postClientDebugLog({ msg: 'second' })
      await new Promise((r) => setTimeout(r, 50))
      expect(mockApiFetch).not.toHaveBeenCalled()
    })

    it('stops posting after 404 response (bridgeForbidden)', async () => {
      localStorage.setItem('xcagi_client_debug_log', '1')
      mockApiFetch.mockResolvedValue({ status: 404, ok: false })
      const { postClientDebugLog } = await loadModule()
      postClientDebugLog({ msg: 'first' })
      await vi.waitFor(() => {
        expect(mockApiFetch).toHaveBeenCalledTimes(1)
      })
      await new Promise((r) => setTimeout(r, 50))
      mockApiFetch.mockClear()
      postClientDebugLog({ msg: 'second' })
      await new Promise((r) => setTimeout(r, 50))
      expect(mockApiFetch).not.toHaveBeenCalled()
    })

    it('continues posting after 200 response', async () => {
      localStorage.setItem('xcagi_client_debug_log', '1')
      mockApiFetch.mockResolvedValue({ status: 200, ok: true })
      const { postClientDebugLog } = await loadModule()
      postClientDebugLog({ msg: 'first' })
      await vi.waitFor(() => {
        expect(mockApiFetch).toHaveBeenCalled()
      })
      await new Promise((r) => setTimeout(r, 50))
      mockApiFetch.mockClear()
      postClientDebugLog({ msg: 'second' })
      await vi.waitFor(() => {
        expect(mockApiFetch).toHaveBeenCalled()
      })
    })

    it('handles apiFetch rejection gracefully', async () => {
      localStorage.setItem('xcagi_client_debug_log', '1')
      mockApiFetch.mockRejectedValue(new Error('network'))
      const { postClientDebugLog } = await loadModule()
      expect(() => postClientDebugLog({ msg: 'test' })).not.toThrow()
      await new Promise((r) => setTimeout(r, 50))
    })

    it('processes queue in batches of 8', async () => {
      localStorage.setItem('xcagi_client_debug_log', '1')
      mockApiFetch.mockResolvedValue({ status: 200, ok: true })
      const { postClientDebugLog } = await loadModule()
      for (let i = 0; i < 10; i++) {
        postClientDebugLog({ msg: `msg-${i}` })
      }
      await vi.waitFor(() => {
        expect(mockApiFetch.mock.calls.length).toBeGreaterThanOrEqual(8)
      })
    })
  })

  describe('installClientConsoleBridge', () => {
    it('installs without throwing when enabled', async () => {
      localStorage.setItem('xcagi_client_debug_log', '1')
      const origError = console.error
      const origWarn = console.warn
      try {
        const { installClientConsoleBridge } = await loadModule()
        expect(() => installClientConsoleBridge()).not.toThrow()
      } finally {
        console.error = origError
        console.warn = origWarn
      }
    })

    it('does not install when disabled via localStorage', async () => {
      localStorage.setItem('xcagi_client_debug_log', '0')
      const origError = console.error
      const { installClientConsoleBridge } = await loadModule()
      installClientConsoleBridge()
      expect(console.error).toBe(origError)
    })

    it('wraps console.error and console.warn when enabled', async () => {
      localStorage.setItem('xcagi_client_debug_log', '1')
      const origError = console.error
      const origWarn = console.warn
      try {
        const { installClientConsoleBridge } = await loadModule()
        installClientConsoleBridge()
        expect(console.error).not.toBe(origError)
        expect(console.warn).not.toBe(origWarn)
      } finally {
        console.error = origError
        console.warn = origWarn
      }
    })

    it('wrapped console.error pushes to queue and calls flushQueue', async () => {
      localStorage.setItem('xcagi_client_debug_log', '1')
      mockApiFetch.mockResolvedValue({ status: 200, ok: true })
      const origError = console.error
      const origWarn = console.warn
      try {
        const { installClientConsoleBridge } = await loadModule()
        installClientConsoleBridge()
        console.error('test error message')
        await vi.waitFor(() => {
          expect(mockApiFetch).toHaveBeenCalled()
        })
      } finally {
        console.error = origError
        console.warn = origWarn
      }
    })

    it('wrapped console.warn pushes to queue and calls flushQueue', async () => {
      localStorage.setItem('xcagi_client_debug_log', '1')
      mockApiFetch.mockResolvedValue({ status: 200, ok: true })
      const origError = console.error
      const origWarn = console.warn
      try {
        const { installClientConsoleBridge } = await loadModule()
        installClientConsoleBridge()
        console.warn('test warn message')
        await vi.waitFor(() => {
          expect(mockApiFetch).toHaveBeenCalled()
        })
      } finally {
        console.error = origError
        console.warn = origWarn
      }
    })

    it('does not install when bridgeForbidden is true', async () => {
      localStorage.setItem('xcagi_client_debug_log', '1')
      mockApiFetch.mockResolvedValue({ status: 403, ok: false })
      const { postClientDebugLog, installClientConsoleBridge } = await loadModule()
      postClientDebugLog({ msg: 'trigger 403' })
      await vi.waitFor(() => {
        expect(mockApiFetch).toHaveBeenCalledTimes(1)
      })
      await new Promise((r) => setTimeout(r, 50))
      const origError = console.error
      installClientConsoleBridge()
      expect(console.error).toBe(origError)
    })
  })
})
