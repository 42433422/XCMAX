import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const httpMocks = vi.hoisted(() => {
  class ApiError extends Error {
    status: number

    constructor(status: number) {
      super(`api ${status}`)
      this.status = status
    }
  }

  return {
    requestStreamBlob: vi.fn(),
    requestStreamResponse: vi.fn(),
    ApiError,
  }
})

vi.mock('./infrastructure/http/client', () => httpMocks)

class FakeUtterance {
  text: string
  lang = ''
  rate = 1
  voice: unknown = null
  onend: (() => void) | null = null
  onerror: (() => void) | null = null

  constructor(text: string) {
    this.text = text
  }
}

class FakeAudio {
  src = ''
  preload = ''
  ended = false
  private listeners = new Map<string, () => void>()

  constructor(src?: string) {
    this.src = src || ''
  }

  addEventListener(name: string, cb: () => void) {
    this.listeners.set(name, cb)
  }

  removeAttribute(name: string) {
    if (name === 'src') this.src = ''
  }

  load() {}
  pause() {}

  play() {
    queueMicrotask(() => {
      this.ended = true
      this.listeners.get('ended')?.()
    })
    return Promise.resolve()
  }
}

function installSpeechSynthesis() {
  const speak = vi.fn((utterance: FakeUtterance) => {
    queueMicrotask(() => utterance.onend?.())
  })
  const cancel = vi.fn()
  Object.defineProperty(globalThis, 'SpeechSynthesisUtterance', {
    configurable: true,
    value: FakeUtterance,
  })
  Object.defineProperty(window, 'speechSynthesis', {
    configurable: true,
    value: {
      speak,
      cancel,
      getVoices: () => [
        { name: 'NamedVoice', lang: 'en-US' },
        { name: '中文女声', lang: 'zh-CN' },
      ],
    },
  })
  return { speak, cancel }
}

function installAudio() {
  Object.defineProperty(globalThis, 'Audio', {
    configurable: true,
    value: FakeAudio,
  })
  Object.defineProperty(URL, 'createObjectURL', {
    configurable: true,
    value: vi.fn(() => 'blob:tts'),
  })
  Object.defineProperty(URL, 'revokeObjectURL', {
    configurable: true,
    value: vi.fn(),
  })
}

function installMediaSource(options: { appendThrows?: boolean; endThrows?: boolean } = {}) {
  class FakeSourceBuffer {
    mode = ''
    buffered = { length: 1 }
    private listeners = new Map<string, () => void>()

    addEventListener(name: string, cb: () => void) {
      this.listeners.set(name, cb)
    }

    removeEventListener(name: string) {
      this.listeners.delete(name)
    }

    appendBuffer() {
      if (options.appendThrows) {
        const error = this.listeners.get('error')
        if (error) queueMicrotask(error)
        throw new Error('append failed')
      }
      const done = this.listeners.get('updateend')
      if (done) queueMicrotask(done)
    }
  }

  class FakeMediaSource {
    static isTypeSupported = vi.fn(() => true)
    readyState = 'open'
    private listeners = new Map<string, () => void>()
    sourceBuffer = new FakeSourceBuffer()

    addEventListener(name: string, cb: () => void) {
      this.listeners.set(name, cb)
      if (name === 'sourceopen') queueMicrotask(cb)
    }

    addSourceBuffer() {
      return this.sourceBuffer
    }

    endOfStream() {
      if (options.endThrows) throw new Error('end failed')
      this.readyState = 'ended'
    }
  }

  Object.defineProperty(globalThis, 'MediaSource', {
    configurable: true,
    value: FakeMediaSource,
  })
}

beforeEach(() => {
  vi.useRealTimers()
  vi.clearAllMocks()
  installAudio()
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('streaming TTS extra coverage', () => {
  it('speaks with browser voices and exposes composable/config helpers', async () => {
    const speech = installSpeechSynthesis()
    const { StreamingTtsPlayer, ttsConfigFromPersonalSettings, useStreamingTts } = await import('./composables/useStreamingTts')
    const player = new StreamingTtsPlayer(() => ({
      engine: 'browser',
      edgeVoice: '',
      browserVoiceName: '中文女声',
      rate: 2,
    }))

    await player.speak('第一句。第二句。')
    expect(speech.speak).toHaveBeenCalled()
    expect(player.state.value).toBe('idle')

    const api = useStreamingTts(() => ({
      engine: 'browser',
      edgeVoice: '',
      browserVoiceName: '',
      rate: 1,
    }))
    api.resetStream({ maxLen: 12 })
    api.feed('流式第一句。')
    api.finish('流式第一句。')
    await api.whenIdle(50)
    api.stop()
    expect(api.state.value).toBe('idle')

    expect(ttsConfigFromPersonalSettings({
      ttsEngine: 'edge-online',
      ttsEdgeVoice: '',
      ttsVoiceName: 'LocalVoice',
      ttsRate: 1.2,
    })).toMatchObject({
      engine: 'edge-online',
      edgeVoice: 'zh-CN-XiaoxiaoNeural',
      browserVoiceName: 'LocalVoice',
      streamThreshold: 0,
      browserLeadIn: false,
    })
  })

  it('warms edge TTS and falls back to browser when edge is rate limited', async () => {
    const speech = installSpeechSynthesis()
    const { StreamingTtsPlayer } = await import('./composables/useStreamingTts')
    const player = new StreamingTtsPlayer(() => ({
      engine: 'edge-online',
      edgeVoice: '',
      browserVoiceName: '',
      rate: 1,
      prefetchDepth: 2,
    }))
    httpMocks.requestStreamBlob.mockRejectedValueOnce(new httpMocks.ApiError(429))

    player.warmUp()
    await Promise.resolve()
    await Promise.resolve()
    expect(httpMocks.requestStreamBlob).toHaveBeenCalledWith('/api/workbench/tts/edge/stream', expect.objectContaining({
      method: 'POST',
      body: expect.stringContaining('你好，我在。'),
    }))

    httpMocks.requestStreamBlob.mockClear()
    await player.speak('被限流后浏览器朗读。')
    expect(httpMocks.requestStreamBlob).not.toHaveBeenCalled()
    expect(speech.speak).toHaveBeenCalled()
  })

  it('prefetches edge audio and plays blobs for queued streaming sentences', async () => {
    installSpeechSynthesis()
    const { StreamingTtsPlayer } = await import('./composables/useStreamingTts')
    httpMocks.requestStreamBlob.mockResolvedValue(new Blob([new Uint8Array([1, 2, 3])], { type: 'audio/mpeg' }))
    httpMocks.requestStreamResponse.mockResolvedValue(new Response(null))
    const player = new StreamingTtsPlayer(() => ({
      engine: 'edge-online',
      edgeVoice: 'EdgeVoice',
      browserVoiceName: '',
      rate: 0.5,
      prefetchDepth: 1,
      browserLeadIn: false,
    }))

    await player.speak('第一段已经结束。第二段也结束。')
    expect(httpMocks.requestStreamBlob).toHaveBeenCalledWith('/api/workbench/tts/edge/stream', expect.objectContaining({
      method: 'POST',
      body: expect.stringContaining('EdgeVoice'),
    }))
    expect(URL.createObjectURL).toHaveBeenCalled()
    player.stop()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:tts')
  })

  it('plays edge streaming responses through MediaSource when supported', async () => {
    installSpeechSynthesis()
    installMediaSource()
    const { StreamingTtsPlayer } = await import('./composables/useStreamingTts')
    httpMocks.requestStreamBlob.mockResolvedValue(new Blob([], { type: 'audio/mpeg' }))
    httpMocks.requestStreamResponse.mockResolvedValue(new Response(new ReadableStream({
      start(controller) {
        controller.enqueue(new Uint8Array([1, 2, 3]))
        controller.close()
      },
    })))
    const player = new StreamingTtsPlayer(() => ({
      engine: 'edge-online',
      edgeVoice: 'EdgeVoice',
      browserVoiceName: '',
      rate: 1.7,
      prefetchDepth: 1,
      browserLeadIn: false,
    }))

    await player.speak('MSE 流式播放一句。')

    expect(httpMocks.requestStreamResponse).toHaveBeenCalled()
    expect(URL.createObjectURL).toHaveBeenCalled()
    expect(player.state.value).toBe('idle')
  })

  it('falls back to browser speech when MediaSource streaming fails', async () => {
    const speech = installSpeechSynthesis()
    installMediaSource({ appendThrows: true })
    const { StreamingTtsPlayer } = await import('./composables/useStreamingTts')
    httpMocks.requestStreamBlob.mockResolvedValue(new Blob([], { type: 'audio/mpeg' }))
    httpMocks.requestStreamResponse.mockResolvedValue(new Response(new ReadableStream({
      start(controller) {
        controller.enqueue(new Uint8Array([9, 8, 7]))
        controller.close()
      },
    })))
    const player = new StreamingTtsPlayer(() => ({
      engine: 'edge-online',
      edgeVoice: '',
      browserVoiceName: 'missing voice',
      rate: 0.2,
      prefetchDepth: 1,
      browserLeadIn: false,
    }))

    await player.speak('MSE 失败后浏览器兜底。')

    expect(httpMocks.requestStreamResponse).toHaveBeenCalled()
    expect(speech.speak).toHaveBeenCalled()
    expect(player.state.value).toBe('idle')
  })

  it('covers warmup skips, lead-in handoff, enqueue dedupe, and idle timeout branches', async () => {
    const speech = installSpeechSynthesis()
    const { StreamingTtsPlayer } = await import('./composables/useStreamingTts')
    const browserPlayer = new StreamingTtsPlayer(() => ({
      engine: 'browser',
      edgeVoice: '',
      browserVoiceName: '',
      rate: 1,
    }))
    browserPlayer.warmUp()
    expect(httpMocks.requestStreamBlob).not.toHaveBeenCalled()
    await browserPlayer.speak('   ')
    expect(speech.speak).not.toHaveBeenCalled()

    const player = new StreamingTtsPlayer(() => ({
      engine: 'edge-online',
      edgeVoice: '',
      browserVoiceName: '中文女声',
      rate: 2,
      browserLeadIn: true,
    }))
    const raw = player as unknown as {
      generation: number
      running: boolean
      queue: string[]
      markEdgeRateLimited: (retryAfterSec?: number) => void
      startBrowserLeadIn: (sentence: string, gen: number) => void
      handoffLeadInToEdge: (gen: number) => void
      cancelBrowserLeadIn: () => void
      enqueue: (sentence: string) => void
      runQueue: (gen: number) => Promise<void>
    }

    raw.markEdgeRateLimited(2)
    player.warmUp()
    expect(httpMocks.requestStreamBlob).not.toHaveBeenCalled()

    raw.startBrowserLeadIn('提前播放一句。', -1)
    raw.startBrowserLeadIn('提前播放一句。', raw.generation)
    raw.handoffLeadInToEdge(-1)
    raw.handoffLeadInToEdge(raw.generation)
    raw.cancelBrowserLeadIn()
    expect(speech.speak).toHaveBeenCalledTimes(1)
    expect(speech.cancel).toHaveBeenCalled()

    raw.running = true
    raw.enqueue('')
    raw.enqueue('重复句子。')
    raw.enqueue('重复句子。')
    expect(raw.queue).toEqual(['重复句子。'])
    await raw.runQueue(raw.generation)
    raw.running = false

    vi.useFakeTimers()
    player.state.value = 'playing'
    const wait = player.whenIdle(1)
    await vi.advanceTimersByTimeAsync(50)
    await expect(wait).resolves.toBeUndefined()
    vi.useRealTimers()
  })

  it('covers stream fallback, abort, missing browser speech, and generation mismatch branches', async () => {
    const { StreamingTtsPlayer } = await import('./composables/useStreamingTts')
    const player = new StreamingTtsPlayer(() => ({
      engine: 'edge-online',
      edgeVoice: '',
      browserVoiceName: '',
      rate: 1,
      browserLeadIn: false,
    }))
    const raw = player as unknown as {
      generation: number
      prefetchBlob: (sentence: string, signal: AbortSignal, gen: number) => Promise<Blob | null>
      playStreamResponse: (res: Response, gen: number) => Promise<boolean>
      playBlob: (blob: Blob, gen: number) => Promise<void>
      pickBrowserVoice: () => SpeechSynthesisVoice | null
      speakBrowser: (text: string, gen: number) => Promise<void>
      speakBrowserSentence: (text: string, gen: number) => Promise<void>
    }

    httpMocks.requestStreamBlob.mockRejectedValueOnce(new DOMException('stop', 'AbortError'))
    expect(await raw.prefetchBlob('中止预取。', new AbortController().signal, raw.generation)).toBeNull()
    httpMocks.requestStreamBlob.mockRejectedValueOnce(new httpMocks.ApiError(429))
    expect(await raw.prefetchBlob('限流预取。', new AbortController().signal, raw.generation)).toBeNull()
    expect(await raw.prefetchBlob('代际不一致。', new AbortController().signal, raw.generation - 1)).toBeNull()

    expect(await raw.playStreamResponse(new Response(null), raw.generation)).toBe(false)
    const mismatchResponse = new Response(new ReadableStream({
      start(controller) {
        controller.enqueue(new Uint8Array([1, 2, 3]))
      },
    }))
    expect(await raw.playStreamResponse(mismatchResponse, raw.generation - 1)).toBe(true)
    await raw.playBlob(new Blob([new Uint8Array([1])]), raw.generation - 1)

    const originalSpeech = Object.getOwnPropertyDescriptor(window, 'speechSynthesis')
    delete (window as unknown as { speechSynthesis?: unknown }).speechSynthesis
    expect(raw.pickBrowserVoice()).toBeNull()
    await raw.speakBrowser('没有浏览器语音。', raw.generation)
    await raw.speakBrowserSentence('代际不一致。', raw.generation - 1)
    if (originalSpeech) Object.defineProperty(window, 'speechSynthesis', originalSpeech)

    Object.defineProperty(globalThis, 'SpeechSynthesisUtterance', {
      configurable: true,
      value: FakeUtterance,
    })
    Object.defineProperty(window, 'speechSynthesis', {
      configurable: true,
      value: {
        speak: vi.fn((utterance: FakeUtterance) => queueMicrotask(() => utterance.onerror?.())),
        cancel: vi.fn(),
        getVoices: () => [],
      },
    })
    await raw.speakBrowserSentence('触发错误回调。', raw.generation)

    installSpeechSynthesis()
    httpMocks.requestStreamBlob.mockRejectedValueOnce(new Error('prefetch down'))
    httpMocks.requestStreamResponse.mockResolvedValueOnce(new Response(null))
    await player.speak('预取失败后使用浏览器。')
    expect(window.speechSynthesis.speak).toHaveBeenCalled()
  })
})

describe('voice device utility extra coverage', () => {
  async function loadVoiceDevice() {
    vi.resetModules()
    return import('./composables/voiceDevice')
  }

  it('detects mobile and iOS voice devices', async () => {
    Object.defineProperty(navigator, 'userAgent', {
      configurable: true,
      value: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)',
    })
    Object.defineProperty(navigator, 'platform', {
      configurable: true,
      value: 'iPhone',
    })
    Object.defineProperty(navigator, 'maxTouchPoints', {
      configurable: true,
      value: 5,
    })
    const mod = await loadVoiceDevice()

    expect(mod.isMobileVoiceDevice()).toBe(true)
    expect(mod.isIOSVoiceDevice()).toBe(true)
    expect(mod.mobileVoiceBottomInsetPx()).toBe(56)
  })

  it('detects iPad desktop mode and scrolls inputs with fallback behavior', async () => {
    Object.defineProperty(navigator, 'userAgent', {
      configurable: true,
      value: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
    })
    Object.defineProperty(navigator, 'platform', {
      configurable: true,
      value: 'MacIntel',
    })
    Object.defineProperty(navigator, 'maxTouchPoints', {
      configurable: true,
      value: 2,
    })
    const mod = await loadVoiceDevice()
    expect(mod.isMobileVoiceDevice()).toBe(false)
    expect(mod.isIOSVoiceDevice()).toBe(true)
    expect(mod.mobileVoiceBottomInsetPx()).toBe(0)

    Object.defineProperty(navigator, 'userAgent', {
      configurable: true,
      value: 'Mozilla/5.0 (Linux; Android 14)',
    })
    const setTimeoutSpy = vi.spyOn(window, 'setTimeout').mockImplementation((cb: TimerHandler) => {
      if (typeof cb === 'function') cb()
      return 1
    })
    const scrollIntoView = vi.fn((arg?: unknown) => {
      if (typeof arg === 'object') throw new Error('smooth unsupported')
    })
    mod.scrollInputIntoViewOnMobile({ scrollIntoView } as unknown as HTMLElement, 0)
    expect(scrollIntoView).toHaveBeenNthCalledWith(1, { block: 'center', behavior: 'smooth' })
    expect(scrollIntoView).toHaveBeenNthCalledWith(2, true)
    setTimeoutSpy.mockRestore()
  })

  it('unlocks voice playback with AudioContext when available', async () => {
    const resume = vi.fn().mockResolvedValue(undefined)
    const close = vi.fn().mockResolvedValue(undefined)
    const start = vi.fn()
    const stop = vi.fn()
    const connect = vi.fn()
    class FakeAudioContext {
      state = 'suspended'
      currentTime = 10
      destination = {}
      resume = resume
      close = close
      createBuffer = vi.fn()
      createBufferSource = vi.fn(() => ({ buffer: null, connect, start, stop }))
    }
    Object.defineProperty(window, 'AudioContext', {
      configurable: true,
      value: FakeAudioContext,
    })
    const mod = await loadVoiceDevice()

    await mod.unlockVoiceAudioPlayback()
    await mod.unlockVoiceAudioPlayback()
    expect(resume).toHaveBeenCalled()
    expect(connect).toHaveBeenCalled()
    expect(start).toHaveBeenCalledWith(0)
    expect(stop).toHaveBeenCalledWith(10.01)
    expect(close).toHaveBeenCalled()
  })
})
