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
      expect(mockPipeline).toHaveBeenCalledWith(
        'text-to-speech',
        'Xenova/mms-tts-cmn',
        expect.objectContaining({
          dtype: 'q8',
        }),
      )
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
      mockPipeline.mockRejectedValueOnce(authError).mockResolvedValueOnce(synth)

      const { ensureOfflineReady, isOfflineReady } = await importFresh()
      await ensureOfflineReady()
      expect(mockPipeline).toHaveBeenCalledTimes(2)
      expect(isOfflineReady()).toBe(true)
    })

    it('throws formatted error after mirror retry fails', async () => {
      const authError = new Error('Unauthorized access to file')
      mockPipeline.mockRejectedValueOnce(authError).mockRejectedValueOnce(new Error('Still unauthorized'))

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
    it('removes its abort listener when a segment finishes', async () => {
      const synth = vi.fn().mockResolvedValue({ audio: new Float32Array([1]), sampling_rate: 16000 })
      mockPipeline.mockResolvedValue(synth)
      const { ensureOfflineReady, synthesizeOffline } = await importFresh()
      await ensureOfflineReady()
      const controller = new AbortController()
      const add = vi.spyOn(controller.signal, 'addEventListener')
      const remove = vi.spyOn(controller.signal, 'removeEventListener')
      await synthesizeOffline('文本', controller.signal)
      expect(add).toHaveBeenCalledWith('abort', expect.any(Function), expect.anything())
      expect(remove).toHaveBeenCalledWith('abort', add.mock.calls[0][1])
    })

    it('rejects immediately when cancelled during a segment and skips remaining segments', async () => {
      let finish!: (value: { audio: Float32Array; sampling_rate: number }) => void
      const synth = vi.fn(() => new Promise<{ audio: Float32Array; sampling_rate: number }>((resolve) => { finish = resolve }))
      mockPipeline.mockResolvedValue(synth)
      const { ensureOfflineReady, synthesizeOffline } = await importFresh()
      await ensureOfflineReady()
      const controller = new AbortController()
      const result = synthesizeOffline('第一句。第二句。', controller.signal)
      const rejected = expect(result).rejects.toMatchObject({ name: 'AbortError' })
      controller.abort()
      await rejected
      finish({ audio: new Float32Array([1]), sampling_rate: 16000 })
      await Promise.resolve()
      expect(synth).toHaveBeenCalledTimes(1)
    })

    it('does not start synthesis when already cancelled', async () => {
      const synth = vi.fn()
      mockPipeline.mockResolvedValue(synth)
      const { ensureOfflineReady, synthesizeOffline } = await importFresh()
      await ensureOfflineReady()
      const controller = new AbortController()
      controller.abort()
      await expect(synthesizeOffline('文本', controller.signal)).rejects.toMatchObject({ name: 'AbortError' })
      expect(synth).not.toHaveBeenCalled()
    })

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
    it('settles stopped playback even when stop throws and no ended event fires', async () => {
      const source = { buffer: null, connect: vi.fn(), start: vi.fn(), stop: vi.fn(() => { throw new Error('stop failed') }), disconnect: vi.fn(), onended: null }
      const context = { createBuffer: vi.fn(() => ({ copyToChannel: vi.fn() })), createBufferSource: vi.fn(() => source), destination: {} }
      vi.stubGlobal('AudioContext', vi.fn(function () { return context }))
      try {
        const { playOfflinePcm, stopOffline } = await importFresh()
        const result = playOfflinePcm(new Float32Array([1]), 16000)
        stopOffline()
        await expect(result).resolves.toBeUndefined()
        expect(source.disconnect).toHaveBeenCalledOnce()
        expect(source.onended).toBeNull()
      } finally {
        vi.unstubAllGlobals()
      }
    })

    it('does not let cancelling an earlier playback stop the current playback', async () => {
      const sources = Array.from({ length: 2 }, () => ({ buffer: null, connect: vi.fn(), start: vi.fn(), stop: vi.fn(), disconnect: vi.fn(), onended: null as (() => void) | null }))
      const context = { createBuffer: vi.fn(() => ({ copyToChannel: vi.fn() })), createBufferSource: vi.fn().mockReturnValueOnce(sources[0]).mockReturnValueOnce(sources[1]), destination: {} }
      vi.stubGlobal('AudioContext', vi.fn(function () { return context }))
      try {
        const { playOfflinePcm } = await importFresh()
        const controller = new AbortController()
        const first = playOfflinePcm(new Float32Array([1]), 16000, controller.signal)
        const rejected = expect(first).rejects.toMatchObject({ name: 'AbortError' })
        const second = playOfflinePcm(new Float32Array([2]), 16000)
        controller.abort()
        await rejected
        expect(sources[0].stop).toHaveBeenCalledOnce()
        expect(sources[1].stop).not.toHaveBeenCalled()
        sources[1].onended?.()
        await expect(second).resolves.toBeUndefined()
      } finally {
        vi.unstubAllGlobals()
      }
    })

    it('stops and settles playback on cancellation without an ended event', async () => {
      const source = { buffer: null, connect: vi.fn(), start: vi.fn(), stop: vi.fn(), disconnect: vi.fn(), onended: null }
      const context = { createBuffer: vi.fn(() => ({ copyToChannel: vi.fn() })), createBufferSource: vi.fn(() => source), destination: {} }
      vi.stubGlobal('AudioContext', vi.fn(function () { return context }))
      try {
        const { playOfflinePcm } = await importFresh()
        const controller = new AbortController()
        const result = playOfflinePcm(new Float32Array([1]), 16000, controller.signal)
        const rejected = expect(result).rejects.toMatchObject({ name: 'AbortError' })
        controller.abort()
        await rejected
        expect(source.stop).toHaveBeenCalledOnce()
        expect(source.disconnect).toHaveBeenCalledOnce()
        expect(source.onended).toBeNull()
      } finally {
        vi.unstubAllGlobals()
      }
    })

    it('does not create an audio context when already cancelled', async () => {
      const context = vi.fn()
      vi.stubGlobal('AudioContext', context)
      try {
        const { playOfflinePcm } = await importFresh()
        const controller = new AbortController()
        controller.abort()
        await expect(playOfflinePcm(new Float32Array([1]), 16000, controller.signal)).rejects.toMatchObject({ name: 'AbortError' })
        expect(context).not.toHaveBeenCalled()
      } finally {
        vi.unstubAllGlobals()
      }
    })

    it('resolves immediately for null-length PCM', async () => {
      const { playOfflinePcm } = await importFresh()
      await expect(playOfflinePcm(new Float32Array(0), 16000)).resolves.toBeUndefined()
    })

    it('resolves on audio context error without throwing', async () => {
      const original = window.AudioContext
      // @ts-expect-error mock
      window.AudioContext = vi.fn(function () {
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
