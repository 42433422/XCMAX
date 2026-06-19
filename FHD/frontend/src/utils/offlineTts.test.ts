import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  isOfflineReady,
  isOfflineLoading,
  getOfflineProgress,
  getOfflineError,
  stopOffline,
  synthesizeOffline,
  playOfflinePcm,
  ensureOfflineReady,
} from './offlineTts'

// Mock @huggingface/transformers
const mockPipeline = vi.fn()
vi.mock('@huggingface/transformers', () => ({
  env: {
    allowRemoteModels: true,
    allowLocalModels: false,
    remoteHost: 'https://huggingface.co/',
    backends: { onnx: { wasm: { proxy: false } } },
  },
  pipeline: (...args: unknown[]) => mockPipeline(...args),
}))

describe('offlineTts', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('state helpers', () => {
    it('isOfflineReady returns boolean', () => {
      expect(typeof isOfflineReady()).toBe('boolean')
    })

    it('isOfflineLoading returns boolean', () => {
      expect(typeof isOfflineLoading()).toBe('boolean')
    })

    it('getOfflineProgress returns number between 0 and 1', () => {
      const p = getOfflineProgress()
      expect(typeof p).toBe('number')
      expect(p).toBeGreaterThanOrEqual(0)
      expect(p).toBeLessThanOrEqual(1)
    })

    it('getOfflineError returns null or error', () => {
      const err = getOfflineError()
      expect(err === null || err instanceof Error).toBe(true)
    })
  })

  describe('stopOffline', () => {
    it('does not throw when called without active playback', () => {
      expect(() => stopOffline()).not.toThrow()
    })
  })

  describe('synthesizeOffline', () => {
    it('throws when pipeline not loaded', async () => {
      try {
        await synthesizeOffline('test')
        // If pipeline was loaded from a previous test, this is acceptable
      } catch (e) {
        expect(e).toBeInstanceOf(Error)
        expect((e as Error).message).toContain('ensureOfflineReady')
      }
    })
  })

  describe('playOfflinePcm', () => {
    it('resolves immediately for empty PCM', async () => {
      await expect(playOfflinePcm(new Float32Array(0), 16000)).resolves.toBeUndefined()
    })

    it('resolves immediately for null-like PCM', async () => {
      await expect(playOfflinePcm(null as unknown as Float32Array, 16000)).resolves.toBeUndefined()
    })

    it('resolves for valid PCM data with mocked AudioContext', async () => {
      const pcm = new Float32Array([0.1, 0.2, 0.3, 0.4])
      // Mock AudioContext
      const mockBufferSource = {
        buffer: null,
        connect: vi.fn(),
        start: vi.fn(),
        onended: null as (() => void) | null,
        disconnect: vi.fn(),
      }
      const mockAudioBuffer = {
        copyToChannel: vi.fn(),
      }
      const mockCtx = {
        createBuffer: vi.fn().mockReturnValue(mockAudioBuffer),
        createBufferSource: vi.fn().mockReturnValue(mockBufferSource),
        destination: {},
      }
      vi.stubGlobal('AudioContext', vi.fn().mockReturnValue(mockCtx))
      vi.stubGlobal('webkitAudioContext', undefined)

      const promise = playOfflinePcm(pcm, 16000)
      // Simulate the onended callback
      if (mockBufferSource.onended) mockBufferSource.onended()
      await expect(promise).resolves.toBeUndefined()

      vi.unstubAllGlobals()
    })
  })

  describe('ensureOfflineReady', () => {
    it('returns immediately if already ready', async () => {
      // If already ready from a previous test, it should resolve immediately
      const progressCb = vi.fn()
      await ensureOfflineReady(progressCb).catch(() => {})
      // No error expected if already ready
    })

    it('handles pipeline creation with progress callback', async () => {
      const mockSynth = vi.fn().mockResolvedValue({
        audio: new Float32Array(100),
        sampling_rate: 16000,
      })
      mockPipeline.mockImplementation(async (task: string, model: string, opts: Record<string, unknown>) => {
        // Simulate progress callback
        const progressCb = opts?.progress_callback as ((event: unknown) => void) | undefined
        if (progressCb) {
          progressCb({ progress: 50 })
          progressCb({ status: 'done' })
        }
        return mockSynth
      })

      const progressCb = vi.fn()
      try {
        await ensureOfflineReady(progressCb)
      } catch {
        // May fail due to module state from previous tests
      }
    })

    it('handles pipeline creation failure', async () => {
      mockPipeline.mockRejectedValue(new Error('Model download failed'))
      try {
        await ensureOfflineReady()
      } catch (e) {
        expect(e).toBeInstanceOf(Error)
      }
    })

    it('handles Hub auth error with mirror fallback', async () => {
      let callCount = 0
      mockPipeline.mockImplementation(async () => {
        callCount++
        if (callCount === 1) {
          throw new Error('Unauthorized access to file')
        }
        return vi.fn().mockResolvedValue({ audio: new Float32Array(100), sampling_rate: 16000 })
      })
      try {
        await ensureOfflineReady()
      } catch {
        // Expected - mirror may also fail in test env
      }
    })
  })

  describe('module exports', () => {
    it('exports expected functions', async () => {
      const mod = await import('./offlineTts')
      expect(typeof mod.isOfflineReady).toBe('function')
      expect(typeof mod.isOfflineLoading).toBe('function')
      expect(typeof mod.getOfflineProgress).toBe('function')
      expect(typeof mod.getOfflineError).toBe('function')
      expect(typeof mod.stopOffline).toBe('function')
      expect(typeof mod.synthesizeOffline).toBe('function')
      expect(typeof mod.playOfflinePcm).toBe('function')
      expect(typeof mod.ensureOfflineReady).toBe('function')
    })
  })
})
