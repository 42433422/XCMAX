import { describe, it, expect, beforeEach, vi } from 'vitest'

const { mockPipeline } = vi.hoisted(() => ({
  mockPipeline: vi.fn(),
}))

vi.mock('@huggingface/transformers', () => ({
  env: {
    allowRemoteModels: false,
    allowLocalModels: false,
    remoteHost: '',
    backends: { onnx: { wasm: { proxy: false } } },
  },
  pipeline: mockPipeline,
}))

async function importFresh() {
  vi.resetModules()
  return await import('./offlineTts')
}

describe('offlineTts ensureOfflineReady and synthesis', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockPipeline.mockReset()
  })

  describe('ensureOfflineReady', () => {
    it('loads pipeline successfully', async () => {
      const synth = vi.fn().mockResolvedValue({ audio: new Float32Array([0.1]), sampling_rate: 16000 })
      mockPipeline.mockResolvedValue(synth)

      const { ensureOfflineReady, isOfflineReady } = await importFresh()
      await ensureOfflineReady()
      expect(mockPipeline).toHaveBeenCalledWith('text-to-speech', 'Xenova/mms-tts-cmn', expect.objectContaining({
        dtype: 'q8',
      }))
      expect(isOfflineReady()).toBe(true)
    })

    it('reports progress via callback', async () => {
      const synth = vi.fn().mockResolvedValue({ audio: new Float32Array([0.1]), sampling_rate: 16000 })
      mockPipeline.mockImplementation(async (_task, _model, opts) => {
        const cb = opts?.progress_callback
        if (cb) {
          cb({ progress: 50 })
          cb({ status: 'done' })
        }
        return synth
      })

      const { ensureOfflineReady } = await importFresh()
      const progressValues: number[] = []
      await ensureOfflineReady((p) => progressValues.push(p))
      expect(progressValues.length).toBeGreaterThan(0)
    })

    it('sets error state on failure', async () => {
      mockPipeline.mockRejectedValue(new Error('Network error'))

      const { ensureOfflineReady, getOfflineError, isOfflineReady } = await importFresh()
      await expect(ensureOfflineReady()).rejects.toThrow()
      expect(getOfflineError()).toBeTruthy()
      expect(isOfflineReady()).toBe(false)
    })

    it('retries with hf-mirror on 401 error', async () => {
      const authError = new Error('Unauthorized access to file')
      const synth = vi.fn().mockResolvedValue({ audio: new Float32Array([0.1]), sampling_rate: 16000 })
      mockPipeline
        .mockRejectedValueOnce(authError)
        .mockResolvedValueOnce(synth)

      const { ensureOfflineReady, isOfflineReady } = await importFresh()
      await ensureOfflineReady()
      expect(mockPipeline).toHaveBeenCalledTimes(2)
      expect(isOfflineReady()).toBe(true)
    })

    it('throws formatted error after mirror retry fails', async () => {
      const authError = new Error('Unauthorized access to file')
      mockPipeline
        .mockRejectedValueOnce(authError)
        .mockRejectedValueOnce(new Error('Still unauthorized'))

      const { ensureOfflineReady, getOfflineError } = await importFresh()
      await expect(ensureOfflineReady()).rejects.toThrow()
      expect(getOfflineError()).toBeTruthy()
    })

    it('throws formatted error for forbidden without retry', async () => {
      const forbiddenError = new Error('Some other error')
      mockPipeline.mockRejectedValue(forbiddenError)

      const { ensureOfflineReady, getOfflineError } = await importFresh()
      await expect(ensureOfflineReady()).rejects.toThrow()
      expect(getOfflineError()).toBeTruthy()
    })
  })

  describe('synthesizeOffline after load', () => {
    it('returns empty audio for empty text segments', async () => {
      const synth = vi.fn().mockResolvedValue({ audio: new Float32Array([0.1]), sampling_rate: 16000 })
      mockPipeline.mockResolvedValue(synth)
      const { ensureOfflineReady, synthesizeOffline } = await importFresh()
      await ensureOfflineReady()

      const result = await synthesizeOffline('')
      expect(result.audio.length).toBe(0)
      expect(result.samplingRate).toBe(16000)
    })

    it('returns empty audio for whitespace-only text', async () => {
      const synth = vi.fn().mockResolvedValue({ audio: new Float32Array([0.1]), sampling_rate: 16000 })
      mockPipeline.mockResolvedValue(synth)
      const { ensureOfflineReady, synthesizeOffline } = await importFresh()
      await ensureOfflineReady()

      const result = await synthesizeOffline('   ')
      expect(result.audio.length).toBe(0)
    })

    it('synthesizes text and merges audio chunks', async () => {
      const synth = vi.fn().mockResolvedValue({ audio: new Float32Array([0.1, 0.2]), sampling_rate: 16000 })
      mockPipeline.mockResolvedValue(synth)
      const { ensureOfflineReady, synthesizeOffline } = await importFresh()
      await ensureOfflineReady()

      const result = await synthesizeOffline('你好。世界！')
      expect(result.audio.length).toBeGreaterThan(0)
      expect(result.samplingRate).toBe(16000)
      expect(synth).toHaveBeenCalled()
    })

    it('handles segments with no audio output', async () => {
      const synth = vi.fn().mockResolvedValue({ audio: new Float32Array(0), sampling_rate: 16000 })
      mockPipeline.mockResolvedValue(synth)
      const { ensureOfflineReady, synthesizeOffline } = await importFresh()
      await ensureOfflineReady()

      const result = await synthesizeOffline('测试文本')
      expect(result.audio.length).toBe(0)
    })
  })

  describe('playOfflinePcm edge cases', () => {
    it('resolves immediately for null-length PCM', async () => {
      const { playOfflinePcm } = await importFresh()
      await expect(playOfflinePcm(new Float32Array(0), 16000)).resolves.toBeUndefined()
    })

    it('resolves on audio context error without throwing', async () => {
      const original = window.AudioContext
      // @ts-expect-error mock
      window.AudioContext = vi.fn(() => {
        throw new Error('AudioContext not available')
      })

      const { playOfflinePcm } = await importFresh()
      const pcm = new Float32Array([0.1, 0.2])
      await expect(playOfflinePcm(pcm, 16000)).resolves.toBeUndefined()

      window.AudioContext = original
    })
  })

  describe('stopOffline', () => {
    it('does not throw when called without active source', async () => {
      const { stopOffline } = await importFresh()
      expect(() => stopOffline()).not.toThrow()
    })

    it('can be called multiple times', async () => {
      const { stopOffline } = await importFresh()
      expect(() => {
        stopOffline()
        stopOffline()
      }).not.toThrow()
    })
  })
})
