import { afterEach, describe, expect, it, vi } from 'vitest'
import { AudioCapture, float32ToInt16, resampleFloat32 } from './composables/asr/audioCapture'

class FakeTrack {
  readyState = 'live'
  stop = vi.fn(() => {
    this.readyState = 'ended'
  })
}

class FakeMediaStream {
  tracks = [new FakeTrack()]
  getAudioTracks() {
    return this.tracks
  }
  getTracks() {
    return this.tracks
  }
}

type FakeProcessor = {
  connect: ReturnType<typeof vi.fn>
  disconnect: ReturnType<typeof vi.fn>
  onaudioprocess: ((event: { inputBuffer: { getChannelData: (index: number) => Float32Array } }) => void) | null
}

const contexts: FakeAudioContext[] = []
const workletNodes: FakeAudioWorkletNode[] = []

class FakeAudioContext {
  state = 'suspended'
  sampleRate = 48000
  destination = {}
  processor: FakeProcessor | null = null
  source = { connect: vi.fn(), disconnect: vi.fn() }
  analyser = {
    fftSize: 0,
    frequencyBinCount: 4,
    connect: vi.fn(),
    disconnect: vi.fn(),
    getByteTimeDomainData: vi.fn((data: Uint8Array) => {
      data.set([128, 160, 96, 128])
    }),
  }
  mute = {
    gain: { value: 1 },
    connect: vi.fn(),
    disconnect: vi.fn(),
  }
  audioWorklet = {
    addModule: vi.fn(async () => {
      throw new Error('force script processor fallback')
    }),
  }
  resume = vi.fn(async () => {
    this.state = 'running'
  })
  close = vi.fn()

  constructor() {
    contexts.push(this)
  }

  createMediaStreamSource() {
    return this.source
  }

  createAnalyser() {
    return this.analyser
  }

  createGain() {
    return this.mute
  }

  createScriptProcessor() {
    this.processor = {
      connect: vi.fn(),
      disconnect: vi.fn(),
      onaudioprocess: null,
    }
    return this.processor
  }
}

class ZeroRateAudioContext extends FakeAudioContext {
  sampleRate = 0
}

class WorkletAudioContext extends FakeAudioContext {
  audioWorklet = {
    addModule: vi.fn(async () => undefined),
  }
}

class FakeAudioWorkletNode {
  port = {
    onmessage: null as ((event: { data: Float32Array }) => void) | null,
  }
  connect = vi.fn()
  disconnect = vi.fn()

  constructor() {
    workletNodes.push(this)
  }
}

function emitPcm(processor: FakeProcessor | null, pcm = new Float32Array([0.25, -0.5, 0.75, -1])) {
  processor?.onaudioprocess?.({
    inputBuffer: {
      getChannelData: () => pcm,
    },
  })
}

afterEach(() => {
  contexts.length = 0
  workletNodes.length = 0
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('audio capture coverage', () => {
  it('converts and resamples PCM buffers', () => {
    expect(Array.from(float32ToInt16(new Float32Array([-2, -0.5, 0, 0.5, 2])))).toEqual([
      -32768,
      -16384,
      0,
      16383,
      32767,
    ])

    const same = new Float32Array([1, 2, 3])
    expect(resampleFloat32(same, 16000, 16000)).toBe(same)
    expect(Array.from(resampleFloat32(new Float32Array([]), 48000, 16000))).toEqual([])
    expect(Array.from(resampleFloat32(new Float32Array([0, 10, 20, 30]), 32000, 16000))).toEqual([0, 20])
  })

  it('starts, wakes, reuses handlers, records PCM stats, and stops owned resources', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('AudioContext', FakeAudioContext)
    vi.stubGlobal('requestAnimationFrame', vi.fn((cb: FrameRequestCallback) => window.setTimeout(() => cb(0), 16)))
    vi.stubGlobal('cancelAnimationFrame', vi.fn((id: number) => window.clearTimeout(id)))

    const stream = new FakeMediaStream()
    const firstData = vi.fn()
    const firstLevel = vi.fn()
    const capture = new AudioCapture()
    const start = capture.start({ onAudioData: firstData, onAudioLevel: firstLevel }, stream as unknown as MediaStream)
    await vi.advanceTimersByTimeAsync(0)
    emitPcm(contexts[0].processor)
    await vi.advanceTimersByTimeAsync(520)
    await start

    expect(capture.active).toBe(true)
    expect(capture.sampleRate).toBe(48000)
    expect(capture.pcmFrames).toBe(1)
    expect(capture.peakLevel).toBeGreaterThan(0)
    expect(firstData).toHaveBeenCalled()
    expect(firstLevel).toHaveBeenCalled()
    expect(contexts[0].audioWorklet.addModule).toHaveBeenCalled()

    const secondData = vi.fn()
    await capture.start({ onAudioData: secondData }, stream as unknown as MediaStream)
    emitPcm(contexts[0].processor, new Float32Array([0.1, 0.1]))
    expect(secondData).toHaveBeenCalled()

    capture.stop()
    expect(capture.active).toBe(false)
    expect(capture.pcmFrames).toBe(0)
    expect(contexts[0].close).toHaveBeenCalled()
    expect(stream.getTracks()[0].stop).not.toHaveBeenCalled()
  })

  it('falls back from strict getUserMedia constraints and rejects silent tracks', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('AudioContext', FakeAudioContext)
    vi.stubGlobal('requestAnimationFrame', vi.fn((cb: FrameRequestCallback) => window.setTimeout(() => cb(0), 16)))
    vi.stubGlobal('cancelAnimationFrame', vi.fn((id: number) => window.clearTimeout(id)))

    const stream = new FakeMediaStream()
    const getUserMedia = vi.fn()
      .mockRejectedValueOnce(new Error('strict failed'))
      .mockResolvedValueOnce(stream)
    Object.defineProperty(navigator, 'mediaDevices', {
      value: { getUserMedia },
      configurable: true,
    })

    const capture = new AudioCapture()
    const start = capture.start({ onAudioData: vi.fn() })
    await vi.advanceTimersByTimeAsync(0)
    emitPcm(contexts[0].processor)
    await vi.advanceTimersByTimeAsync(520)
    await start

    expect(getUserMedia).toHaveBeenNthCalledWith(1, {
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    })
    expect(getUserMedia).toHaveBeenNthCalledWith(2, { audio: true })
    capture.stop()
    expect(stream.getTracks()[0].stop).toHaveBeenCalled()

    Object.defineProperty(navigator, 'mediaDevices', {
      value: undefined,
      configurable: true,
    })
    await expect(new AudioCapture().start({ onAudioData: vi.fn() })).rejects.toThrow('当前浏览器不支持麦克风采集')
  })

  it('uses script processor on touch Mac devices and restarts active level handlers', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('AudioContext', FakeAudioContext)
    const rafCallbacks: FrameRequestCallback[] = []
    vi.stubGlobal('requestAnimationFrame', vi.fn((cb: FrameRequestCallback) => {
      rafCallbacks.push(cb)
      return rafCallbacks.length
    }))
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
    Object.defineProperty(navigator, 'userAgent', {
      value: 'Mozilla/5.0 (Macintosh; Intel Mac OS X)',
      configurable: true,
    })
    Object.defineProperty(navigator, 'platform', {
      value: 'MacIntel',
      configurable: true,
    })
    Object.defineProperty(navigator, 'maxTouchPoints', {
      value: 3,
      configurable: true,
    })

    const capture = new AudioCapture()
    await capture.wake()

    const onData = vi.fn()
    const start = capture.start({ onAudioData: onData }, new FakeMediaStream() as unknown as MediaStream)
    await vi.advanceTimersByTimeAsync(0)
    expect(contexts[0].audioWorklet.addModule).not.toHaveBeenCalled()

    emitPcm(contexts[0].processor, new Float32Array([]))
    await vi.advanceTimersByTimeAsync(520)
    await start

    expect(onData).toHaveBeenCalledWith(new Float32Array([]))
    capture.setHandlers({ onAudioData: onData, onAudioLevel: vi.fn() })
    capture.setHandlers({ onAudioData: onData, onAudioLevel: vi.fn() })
    ;(capture as unknown as { startLevelLoop: () => void }).startLevelLoop()
    capture.stop()
    ;(capture as unknown as { startLevelLoop: () => void }).startLevelLoop()

    expect(vi.mocked(cancelAnimationFrame)).toHaveBeenCalled()
    expect(rafCallbacks.length).toBeGreaterThan(0)
  })

  it('uses audio worklet capture, emits analyser levels, and keeps the context awake', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('AudioContext', WorkletAudioContext)
    vi.stubGlobal('AudioWorkletNode', FakeAudioWorkletNode)
    Object.defineProperty(navigator, 'userAgent', {
      value: 'Mozilla/5.0 (X11; Linux x86_64)',
      configurable: true,
    })
    Object.defineProperty(navigator, 'platform', {
      value: 'Linux x86_64',
      configurable: true,
    })
    Object.defineProperty(navigator, 'maxTouchPoints', {
      value: 0,
      configurable: true,
    })
    const rafCallbacks: FrameRequestCallback[] = []
    vi.stubGlobal('requestAnimationFrame', vi.fn((cb: FrameRequestCallback) => {
      rafCallbacks.push(cb)
      return rafCallbacks.length
    }))
    vi.stubGlobal('cancelAnimationFrame', vi.fn())

    const onData = vi.fn()
    const onLevel = vi.fn()
    const capture = new AudioCapture()
    const start = capture.start(
      { onAudioData: onData, onAudioLevel: onLevel },
      new FakeMediaStream() as unknown as MediaStream,
    )
    await vi.advanceTimersByTimeAsync(0)

    expect(workletNodes).toHaveLength(1)
    workletNodes[0].port.onmessage?.({ data: new Float32Array([0.001]) })
    await vi.advanceTimersByTimeAsync(520)
    await start

    contexts[0].analyser.getByteTimeDomainData.mockImplementation((data: Uint8Array) => {
      data.set([0, 255, 0, 255])
    })
    rafCallbacks.shift()?.(0)
    await vi.advanceTimersByTimeAsync(800)

    expect(onData).toHaveBeenCalled()
    expect(onLevel).toHaveBeenCalled()
    expect(capture.peakLevel).toBe(1)
    expect((capture as unknown as { _useWorklet: boolean })._useWorklet).toBe(true)
    expect(contexts[0].audioWorklet.addModule).toHaveBeenCalledWith('/vosk/pcm-processor.worklet.js')
    capture.stop()
  })

  it('rejects streams without live tracks and captures that never deliver PCM', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('AudioContext', FakeAudioContext)

    const endedStream = new FakeMediaStream()
    endedStream.tracks[0].readyState = 'ended'
    await expect(
      new AudioCapture().start({ onAudioData: vi.fn() }, endedStream as unknown as MediaStream),
    ).rejects.toThrow('麦克风不可用')

    const silentCapture = new AudioCapture()
    const start = silentCapture.start({ onAudioData: vi.fn() }, new FakeMediaStream() as unknown as MediaStream)
    const rejection = expect(start).rejects.toThrow('未收到音频数据')
    await vi.advanceTimersByTimeAsync(520)
    await rejection
    silentCapture.stop()
  })

  it('falls back to default sample rate and handles navigator-free platform checks', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('AudioContext', ZeroRateAudioContext)
    vi.stubGlobal('navigator', undefined)

    const capture = new AudioCapture()
    const start = capture.start({ onAudioData: vi.fn() }, new FakeMediaStream() as unknown as MediaStream)
    await vi.advanceTimersByTimeAsync(0)
    emitPcm(contexts[0].processor, new Float32Array([0.1]))
    await vi.advanceTimersByTimeAsync(520)
    await start

    expect(capture.sampleRate).toBe(16000)
    capture.stop()
  })

  it('handles queued level callbacks after capture becomes inactive', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('AudioContext', FakeAudioContext)
    const rafCallbacks: FrameRequestCallback[] = []
    vi.stubGlobal('requestAnimationFrame', vi.fn((cb: FrameRequestCallback) => {
      rafCallbacks.push(cb)
      return rafCallbacks.length
    }))
    vi.stubGlobal('cancelAnimationFrame', vi.fn())

    const capture = new AudioCapture()
    const start = capture.start(
      { onAudioData: vi.fn(), onAudioLevel: vi.fn() },
      new FakeMediaStream() as unknown as MediaStream,
    )
    await vi.advanceTimersByTimeAsync(0)
    emitPcm(contexts[0].processor, new Float32Array([0.01]))
    await vi.advanceTimersByTimeAsync(520)
    await start

    capture.stop()
    rafCallbacks[0]?.(0)

    expect((capture as unknown as { rafId: number }).rafId).toBe(0)
  })
})
