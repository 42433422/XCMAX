import { afterEach, describe, expect, it, vi } from 'vitest'

class TestMediaStream {
  tracks = [{ readyState: 'live', stop: vi.fn() }]
  getAudioTracks() {
    return this.tracks
  }
  getTracks() {
    return this.tracks
  }
}

const mockStarts: Array<{ handlers: { onAudioData: (pcm: Float32Array) => void; onAudioLevel?: (level: number) => void }; stream?: MediaStream }> = []
const mockStops: unknown[] = []
const mockWakes: unknown[] = []

vi.mock('./composables/asr/audioCapture', () => {
  class MockAudioCapture {
    active = false
    setHandlers = vi.fn((handlers) => {
      this.handlers = handlers
    })
    wake = vi.fn(() => {
      mockWakes.push(this)
    })
    stop = vi.fn(() => {
      this.active = false
      mockStops.push(this)
    })
    handlers: { onAudioData: (pcm: Float32Array) => void; onAudioLevel?: (level: number) => void } | null = null

    async start(
      handlers: { onAudioData: (pcm: Float32Array) => void; onAudioLevel?: (level: number) => void },
      stream?: MediaStream,
    ) {
      this.handlers = handlers
      this.active = true
      mockStarts.push({ handlers, stream })
      handlers.onAudioData(new Float32Array([0.3]))
      handlers.onAudioLevel?.(0.8)
    }
  }

  return { AudioCapture: MockAudioCapture }
})

afterEach(() => {
  mockStarts.length = 0
  mockStops.length = 0
  mockWakes.length = 0
  vi.unstubAllGlobals()
  vi.resetModules()
  vi.restoreAllMocks()
})

describe('shared mic and preflight coverage', () => {
  it('binds, reuses, wakes, and releases shared microphone capture', async () => {
    vi.stubGlobal('MediaStream', TestMediaStream)
    const {
      bindPrefetchedStream,
      ensureSharedMicCapture,
      getHeldMicStream,
      getSharedMicCapture,
      releaseHeldMicStream,
      releaseSharedMicCapture,
      wakeSharedMicCapture,
    } = await import('./composables/asr/sharedMicCapture')

    const stream = new TestMediaStream() as unknown as MediaStream
    bindPrefetchedStream(stream)
    expect(getHeldMicStream()).toBe(stream)

    const onAudioData = vi.fn()
    const onAudioLevel = vi.fn()
    const capture = await ensureSharedMicCapture({ onAudioData, onAudioLevel })
    expect(onAudioData).toHaveBeenCalled()
    expect(onAudioLevel).toHaveBeenCalledWith(0.8)
    expect(mockStarts[0].stream).toBe(stream)
    expect(getSharedMicCapture()).toBe(capture)

    const nextData = vi.fn()
    const reused = await ensureSharedMicCapture({ onAudioData: nextData })
    expect(reused).toBe(capture)
    expect(mockStarts).toHaveLength(1)
    expect(mockWakes.length).toBeGreaterThan(0)

    wakeSharedMicCapture()
    expect(mockWakes.length).toBeGreaterThan(1)

    releaseHeldMicStream()
    expect(stream.getTracks()[0].stop).toHaveBeenCalled()
    expect(getHeldMicStream()).toBeNull()

    releaseSharedMicCapture()
    expect(mockStops).toHaveLength(1)
    expect(getSharedMicCapture()).toBeNull()
  })

  it('requests mic preflight, falls back to loose constraints, and clears pending state', async () => {
    vi.stubGlobal('MediaStream', TestMediaStream)
    const stream = new TestMediaStream() as unknown as MediaStream
    const getUserMedia = vi.fn()
      .mockRejectedValueOnce(new Error('strict rejected'))
      .mockResolvedValueOnce(stream)
    Object.defineProperty(navigator, 'mediaDevices', {
      value: { getUserMedia },
      configurable: true,
    })

    const { releaseHeldMicStream } = await import('./composables/asr/sharedMicCapture')
    const {
      requestMicInUserGesture,
      takeMicPreflight,
      clearMicPreflight,
    } = await import('./composables/asr/micPreflight')

    const pending = requestMicInUserGesture()
    await expect(pending).resolves.toBe(stream)
    expect(getUserMedia).toHaveBeenNthCalledWith(1, {
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    })
    expect(getUserMedia).toHaveBeenNthCalledWith(2, { audio: true })

    await expect(takeMicPreflight()).resolves.toBe(stream)
    releaseHeldMicStream()
    clearMicPreflight()
    expect(takeMicPreflight()).toBeNull()
  })

  it('returns null when no browser microphone API exists', async () => {
    Object.defineProperty(navigator, 'mediaDevices', {
      value: undefined,
      configurable: true,
    })
    const { requestMicInUserGesture, takeMicPreflight } = await import('./composables/asr/micPreflight')

    expect(requestMicInUserGesture()).toBeNull()
    expect(takeMicPreflight()).toBeNull()
  })
})
