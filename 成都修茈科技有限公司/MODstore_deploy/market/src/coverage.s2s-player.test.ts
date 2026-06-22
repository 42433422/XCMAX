import { afterEach, describe, expect, it, vi } from 'vitest'

const mockUnlockVoiceAudioPlayback = vi.fn(async () => undefined)

vi.mock('./composables/voiceDevice', () => ({
  unlockVoiceAudioPlayback: () => mockUnlockVoiceAudioPlayback(),
}))

class FakeSource {
  buffer: unknown = null
  onended: (() => void) | null = null
  connect = vi.fn()
  start = vi.fn()
}

class FakeAudioContext {
  state = 'suspended'
  currentTime = 10
  destination = {}
  sources: FakeSource[] = []
  resume = vi.fn(async () => {
    this.state = 'running'
  })
  close = vi.fn()
  decodeAudioData = vi.fn(async () => {
    if (FakeAudioContext.decodeReject) throw new Error('decode failed')
    return { duration: 0.5 }
  })
  createBufferSource() {
    const source = new FakeSource()
    this.sources.push(source)
    return source
  }
  static decodeReject = false
  static instances: FakeAudioContext[] = []
  constructor() {
    FakeAudioContext.instances.push(this)
  }
}

class FakeAudio {
  static instances: FakeAudio[] = []
  onended: (() => void) | null = null
  onerror: (() => void) | null = null
  duration = 1.25
  play = vi.fn(async () => undefined)
  constructor(public src: string) {
    FakeAudio.instances.push(this)
  }
}

async function flushMicrotasks(times = 8) {
  for (let i = 0; i < times; i += 1) await Promise.resolve()
}

afterEach(() => {
  FakeAudioContext.instances.length = 0
  FakeAudioContext.decodeReject = false
  FakeAudio.instances.length = 0
  mockUnlockVoiceAudioPlayback.mockClear()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('S2S MSE audio player coverage', () => {
  it('schedules decoded sentence audio and clears active sources on end', async () => {
    vi.stubGlobal('AudioContext', FakeAudioContext)
    const { S2sMseAudioPlayer } = await import('./composables/s2sMseAudioPlayer')
    const player = new S2sMseAudioPlayer()

    player.beginTurn()
    player.appendChunk('s1', new Uint8Array([1, 2]))
    player.appendChunk('s1', new Uint8Array([3]))
    expect(player.isPlaying).toBe(true)
    player.endSentence('s1')
    await flushMicrotasks()

    const ctx = FakeAudioContext.instances[0]
    expect(mockUnlockVoiceAudioPlayback).toHaveBeenCalled()
    expect(ctx.resume).toHaveBeenCalled()
    expect(ctx.decodeAudioData).toHaveBeenCalled()
    expect(ctx.sources[0].connect).toHaveBeenCalledWith(ctx.destination)
    expect(ctx.sources[0].start).toHaveBeenCalledWith(10.02)

    ctx.sources[0].onended?.()
    expect(player.isPlaying).toBe(false)

    player.reset()
    expect(ctx.close).toHaveBeenCalled()
  })

  it('falls back to HTMLAudio for decode failures and handles generation resets', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('AudioContext', FakeAudioContext)
    vi.stubGlobal('Audio', FakeAudio)
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn(() => 'blob:audio'),
      revokeObjectURL: vi.fn(),
    })
    FakeAudioContext.decodeReject = true
    const { S2sMseAudioPlayer } = await import('./composables/s2sMseAudioPlayer')
    const player = new S2sMseAudioPlayer()

    player.appendChunk('fallback', new Uint8Array([9]))
    player.endTurn()
    await flushMicrotasks()
    await vi.advanceTimersByTimeAsync(25)
    await flushMicrotasks()

    expect(FakeAudio.instances[0].src).toBe('blob:audio')
    expect(FakeAudio.instances[0].play).toHaveBeenCalled()
    FakeAudio.instances[0].onended?.()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:audio')
    expect(player.isPlaying).toBe(false)

    player.appendChunk('reset-before-play', new Uint8Array([1]))
    player.endSentence('reset-before-play')
    player.reset()
    await flushMicrotasks()
    expect(player.isPlaying).toBe(false)
  })

  it('resolves idle waits once playback drains', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('AudioContext', FakeAudioContext)
    const { S2sMseAudioPlayer } = await import('./composables/s2sMseAudioPlayer')
    const player = new S2sMseAudioPlayer()

    player.appendChunk('wait', new Uint8Array([1]))
    player.endSentence('wait')
    await flushMicrotasks()
    const idle = player.whenIdle()
    FakeAudioContext.instances[0].sources[0].onended?.()
    await vi.advanceTimersByTimeAsync(40)
    await expect(idle).resolves.toBeUndefined()
  })
})
