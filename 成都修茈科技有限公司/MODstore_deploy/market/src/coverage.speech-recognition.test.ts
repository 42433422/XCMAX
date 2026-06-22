import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ASRResult } from './composables/asr/types'

let mockFunAvailable = true
let mockWebAvailable = true
let mockWhisperAvailable = true
let mockHubReady = true
let mockFunMode: 'success' | 'startup-error' | 'ready-no-result' | 'ready-error' | 'throw' | 'connect-hang' | 'pending' = 'success'
let mockWebMode: 'success' | 'startup-error' | 'ready-no-result' | 'ready-error' = 'success'
let mockWhisperMode: 'success' | 'startup-error' | 'ready-no-result' | 'ready-error' = 'success'
let mockFunStopText = 'fun stop'
let mockWebStopText = 'web stop'
let mockWhisperStopText = 'whisper stop'
let mockFunFlushText = 'fun flush'
let mockStartupErrorMsg = '麦克风 Permission denied'
let mockLastFunBackend: MockBackend | null = null
let mockLastWebBackend: MockBackend | null = null
let mockLastWhisperBackend: MockBackend | null = null
const mockReleaseSharedMicCapture = vi.fn()
const mockWakeSharedMicCapture = vi.fn()

class MockBackend {
  abort = vi.fn()
  signalEndOfSpeech = vi.fn()
  flushUtterance = vi.fn(async () => mockFunFlushText)
  stop = vi.fn(async () => 'stop')
  available = true
  mode: 'success' | 'startup-error' | 'ready-no-result' | 'ready-error' | 'throw' | 'connect-hang' | 'pending' = 'success'
  stopText = 'stop'
  text = '识别结果'

  isAvailable() {
    return this.available
  }

  async start(
    onResult: (r: ASRResult) => void,
    onError: (msg: string) => void,
    onAudioLevel?: (level: number) => void,
    onReady?: () => void,
    onMicReady?: () => void,
  ) {
    onMicReady?.()
    if (this.mode === 'throw') throw new Error('boom')
    if (this.mode === 'startup-error') {
      onError(mockStartupErrorMsg)
      return
    }
    if (this.mode === 'pending') {
      return new Promise<void>(() => undefined)
    }
    if (this.mode === 'connect-hang') return
    onReady?.()
    onAudioLevel?.(0.6)
    if (this.mode === 'ready-no-result') return
    onResult({ text: this.text, isFinal: false, segmentMode: 'online' })
    if (this.mode === 'ready-error') {
      await onError('runtime disconnected')
    }
  }
}

vi.mock('./composables/asr/FunASRBackend', () => ({
  FunASRBackend: class extends MockBackend {
    constructor() {
      super()
      this.available = mockFunAvailable
      this.mode = mockFunMode
      this.stopText = mockFunStopText
      this.text = '服务端结果'
      this.stop = vi.fn(async () => mockFunStopText)
      this.flushUtterance = vi.fn(async () => mockFunFlushText)
      mockLastFunBackend = this
    }
  },
}))

vi.mock('./composables/asr/WebSpeechBackend', () => ({
  WebSpeechBackend: class extends MockBackend {
    constructor() {
      super()
      this.available = mockWebAvailable
      this.mode = mockWebMode
      this.stopText = mockWebStopText
      this.text = '浏览器结果'
      this.stop = vi.fn(async () => mockWebStopText)
      mockLastWebBackend = this
    }
  },
}))

vi.mock('./composables/asr/WhisperWebBackend', () => ({
  WhisperWebBackend: class extends MockBackend {
    constructor() {
      super()
      this.available = mockWhisperAvailable
      this.mode = mockWhisperMode
      this.stopText = mockWhisperStopText
      this.text = '本地模型结果'
      this.stop = vi.fn(async () => mockWhisperStopText)
      mockLastWhisperBackend = this
    }
  },
}))

vi.mock('./composables/asr/hfHub', () => ({
  probeWhisperHubReady: vi.fn(async () => mockHubReady),
}))

vi.mock('./composables/asr/sharedMicCapture', () => ({
  releaseSharedMicCapture: () => mockReleaseSharedMicCapture(),
  wakeSharedMicCapture: () => mockWakeSharedMicCapture(),
}))

afterEach(() => {
  mockFunAvailable = true
  mockWebAvailable = true
  mockWhisperAvailable = true
  mockHubReady = true
  mockFunMode = 'success'
  mockWebMode = 'success'
  mockWhisperMode = 'success'
  mockFunStopText = 'fun stop'
  mockWebStopText = 'web stop'
  mockWhisperStopText = 'whisper stop'
  mockFunFlushText = 'fun flush'
  mockStartupErrorMsg = '麦克风 Permission denied'
  mockLastFunBackend = null
  mockLastWebBackend = null
  mockLastWhisperBackend = null
  mockReleaseSharedMicCapture.mockClear()
  mockWakeSharedMicCapture.mockClear()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('useSpeechRecognition coverage', () => {
  it('runs the FunASR success path, flushes, signals, stops, and aborts', async () => {
    const { useSpeechRecognition } = await import('./composables/useSpeechRecognition')
    const speech = useSpeechRecognition()
    const onResult = vi.fn()
    const onError = vi.fn()
    const onAudioLevel = vi.fn()

    await speech.startListening(onResult, onError, onAudioLevel)

    expect(speech.activeBackendId.value).toBe('funasr')
    expect(speech.sessionReady.value).toBe(true)
    expect(speech.interimText.value).toBe('服务端结果')
    expect(speech.audioLevel.value).toBe(0.6)
    expect(speech.loadingHint.value).toBe('')
    expect(onResult).toHaveBeenCalledWith({ text: '服务端结果', isFinal: false, segmentMode: 'online' })
    expect(onAudioLevel).toHaveBeenCalledWith(0.6)
    expect(mockWakeSharedMicCapture).toHaveBeenCalled()

    speech.signalEndOfSpeech()
    expect(mockLastFunBackend?.signalEndOfSpeech).toHaveBeenCalled()
    await expect(speech.flushListening()).resolves.toBe('fun flush')
    expect(speech.interimText.value).toBe('服务端结果')

    await expect(speech.stopListening()).resolves.toBe('fun stop')
    expect(speech.activeBackendId.value).toBe('')
    expect(speech.sessionReady.value).toBe(false)
    expect(onError).not.toHaveBeenCalled()

    await speech.startListening(onResult, onError, onAudioLevel, { continuous: true })
    speech.abort({ keepMic: true })
    expect(mockReleaseSharedMicCapture).not.toHaveBeenCalled()
    speech.abort()
    expect(mockReleaseSharedMicCapture).toHaveBeenCalled()
  })

  it('falls back from FunASR startup failure to WebSpeech and preserves result state', async () => {
    mockFunMode = 'startup-error'
    const { useSpeechRecognition } = await import('./composables/useSpeechRecognition')
    const speech = useSpeechRecognition()
    const onError = vi.fn()

    await speech.startListening(vi.fn(), onError)

    expect(mockLastFunBackend?.abort).toHaveBeenCalled()
    expect(speech.activeBackendId.value).toBe('webspeech')
    expect(speech.interimText.value).toBe('浏览器结果')
    expect(onError).not.toHaveBeenCalled()
    await expect(speech.stopListening()).resolves.toBe('web stop')
  })

  it('falls through unavailable backends and reports final startup errors', async () => {
    mockFunAvailable = false
    mockWebAvailable = false
    mockHubReady = false
    const { useSpeechRecognition } = await import('./composables/useSpeechRecognition')
    const speech = useSpeechRecognition()
    const onError = vi.fn()

    await speech.startListening(vi.fn(), onError)

    expect(speech.error.value).toBe('语音识别不可用。请检查麦克风权限或使用文字输入。')
    expect(onError).toHaveBeenCalledWith('语音识别不可用。请检查麦克风权限或使用文字输入。')
    expect(speech.activeBackendId.value).toBe('')
  })

  it('uses Whisper when hub probing succeeds after browser fallback is unavailable', async () => {
    mockFunAvailable = false
    mockWebAvailable = false
    mockHubReady = true
    const { useSpeechRecognition } = await import('./composables/useSpeechRecognition')
    const speech = useSpeechRecognition()

    await speech.startListening(vi.fn(), vi.fn())

    expect(speech.activeBackendId.value).toBe('whisper-web')
    expect(speech.interimText.value).toBe('本地模型结果')
    expect(mockLastWhisperBackend).not.toBeNull()
    await expect(speech.stopListening()).resolves.toBe('whisper stop')
  })

  it('handles continuous mode stop release and no-browser-fallback error', async () => {
    Object.defineProperty(navigator, 'userAgent', {
      value: 'iPhone',
      configurable: true,
    })
    const { useSpeechRecognition } = await import('./composables/useSpeechRecognition')
    const speech = useSpeechRecognition()

    await speech.startListening(vi.fn(), vi.fn(), undefined, { continuous: true })
    await expect(speech.stopListening()).resolves.toBe('fun stop')
    expect(mockReleaseSharedMicCapture).toHaveBeenCalled()

    mockReleaseSharedMicCapture.mockClear()
    mockFunAvailable = false
    const failed = useSpeechRecognition()
    const onError = vi.fn()
    await failed.startListening(vi.fn(), onError, undefined, { continuous: true })
    expect(failed.error.value).toBe('服务端语音识别不可用，请检查网络后重试；国内环境请勿依赖浏览器识别。')
    expect(onError).toHaveBeenCalledWith('服务端语音识别不可用，请检查网络后重试；国内环境请勿依赖浏览器识别。')
  })

  it('falls back when a ready backend times out without results', async () => {
    vi.useFakeTimers()
    mockFunMode = 'ready-no-result'
    const { useSpeechRecognition } = await import('./composables/useSpeechRecognition')
    const speech = useSpeechRecognition()
    const onError = vi.fn()

    await speech.startListening(vi.fn(), onError)
    expect(speech.activeBackendId.value).toBe('funasr')

    await vi.advanceTimersByTimeAsync(15_000)
    await Promise.resolve()

    expect(mockLastFunBackend?.abort).toHaveBeenCalled()
    expect(speech.activeBackendId.value).toBe('webspeech')
    expect(speech.interimText.value).toBe('浏览器结果')
    expect(onError).not.toHaveBeenCalled()
  })

  it('falls back after a runtime backend error and keeps the latest partial text', async () => {
    mockFunMode = 'ready-error'
    const { useSpeechRecognition } = await import('./composables/useSpeechRecognition')
    const speech = useSpeechRecognition()
    const onResult = vi.fn()
    const onError = vi.fn()

    await speech.startListening(onResult, onError)

    expect(onResult).toHaveBeenCalledWith({ text: '服务端结果', isFinal: false, segmentMode: 'online' })
    expect(mockLastFunBackend?.abort).toHaveBeenCalled()
    expect(speech.activeBackendId.value).toBe('webspeech')
    expect(speech.interimText.value).toBe('浏览器结果')
    expect(onError).not.toHaveBeenCalled()
  })

  it('returns cached recognition text when stopping after backend abort', async () => {
    const { useSpeechRecognition } = await import('./composables/useSpeechRecognition')
    const speech = useSpeechRecognition()

    await speech.startListening(vi.fn(), vi.fn())
    speech.abort()

    await expect(speech.stopListening()).resolves.toBe('服务端结果')
    expect(speech.loadingHint.value).toBe('')
  })

  it('exhausts continuous startup retries and maps authentication and permission failures', async () => {
    vi.useFakeTimers()
    mockFunMode = 'startup-error'
    mockStartupErrorMsg = '请先登录后再使用语音识别。'
    const { useSpeechRecognition } = await import('./composables/useSpeechRecognition')
    const speech = useSpeechRecognition()
    const onError = vi.fn()

    const start = speech.startListening(vi.fn(), onError, undefined, { continuous: true })
    await vi.advanceTimersByTimeAsync(20_000)
    await start

    expect(speech.error.value).toBe('请先登录后再使用语音识别。')
    expect(onError).toHaveBeenLastCalledWith('请先登录后再使用语音识别。')
    expect(mockLastFunBackend?.abort).toHaveBeenCalled()

    vi.useRealTimers()
    vi.useFakeTimers()
    mockStartupErrorMsg = '麦克风 Permission denied'
    const mobile = useSpeechRecognition()
    Object.defineProperty(navigator, 'userAgent', { value: 'iPhone', configurable: true })
    const mobileError = vi.fn()
    const mobileStart = mobile.startListening(vi.fn(), mobileError, undefined, { continuous: true })
    await vi.advanceTimersByTimeAsync(20_000)
    await mobileStart

    expect(mobile.error.value).toBe('请先点击右下角麦克风按钮，在系统弹窗中允许麦克风后再说话。')
    expect(mobileError).toHaveBeenLastCalledWith('请先点击右下角麦克风按钮，在系统弹窗中允许麦克风后再说话。')
  })

  it('uses promised media streams and handles backend throw fallback', async () => {
    mockFunMode = 'throw'
    const { useSpeechRecognition } = await import('./composables/useSpeechRecognition')
    const speech = useSpeechRecognition()
    const stream = Promise.resolve(new MediaStream())

    await speech.startListening(vi.fn(), vi.fn(), undefined, { mediaStream: stream })

    expect(speech.activeBackendId.value).toBe('webspeech')
    expect(speech.interimText.value).toBe('浏览器结果')
    await expect(speech.flushListening()).resolves.toBe('fun flush')
  })

  it('skips Whisper on mobile and returns final unavailable error', async () => {
    Object.defineProperty(navigator, 'userAgent', { value: 'Android Chrome', configurable: true })
    mockFunAvailable = false
    mockWebAvailable = false
    mockWhisperAvailable = true
    mockHubReady = true
    const { useSpeechRecognition } = await import('./composables/useSpeechRecognition')
    const speech = useSpeechRecognition()
    const onError = vi.fn()

    await speech.startListening(vi.fn(), onError)

    expect(mockLastWhisperBackend).toBeNull()
    expect(speech.error.value).toBe('语音识别不可用。请检查麦克风权限或使用文字输入。')
    expect(onError).toHaveBeenCalledWith('语音识别不可用。请检查麦克风权限或使用文字输入。')
  })

  it('covers direct and rejected prefetched media streams', async () => {
    const { useSpeechRecognition } = await import('./composables/useSpeechRecognition')
    const direct = useSpeechRecognition()

    await direct.startListening(vi.fn(), vi.fn(), undefined, { mediaStream: new MediaStream() })
    expect(direct.activeBackendId.value).toBe('funasr')
    await direct.stopListening()

    const rejected = useSpeechRecognition()
    await rejected.startListening(vi.fn(), vi.fn(), undefined, {
      mediaStream: Promise.reject(new Error('preflight failed')),
    })
    expect(rejected.activeBackendId.value).toBe('funasr')
  })

  it('retries continuous FunASR connection timeouts before surfacing service errors', async () => {
    vi.useFakeTimers()
    mockFunMode = 'connect-hang'
    const { useSpeechRecognition } = await import('./composables/useSpeechRecognition')
    const speech = useSpeechRecognition()
    const onError = vi.fn()

    const start = speech.startListening(vi.fn(), onError, undefined, { continuous: true })

    for (let i = 0; i < 4; i += 1) {
      await vi.advanceTimersByTimeAsync(600 + (i + 1) * 400)
      await Promise.resolve()
    }

    await start

    expect(speech.error.value).toBe('服务端语音识别不可用，请检查网络后重试；国内环境请勿依赖浏览器识别。')
    expect(onError).toHaveBeenLastCalledWith('服务端语音识别不可用，请检查网络后重试；国内环境请勿依赖浏览器识别。')
  })

  it('exhausts non-continuous listen timers across all backends', async () => {
    vi.useFakeTimers()
    Object.defineProperty(navigator, 'userAgent', { value: 'Desktop Chrome', configurable: true })
    mockFunMode = 'ready-no-result'
    mockWebMode = 'ready-no-result'
    mockWhisperMode = 'ready-no-result'
    mockHubReady = true
    const { useSpeechRecognition } = await import('./composables/useSpeechRecognition')
    const speech = useSpeechRecognition()
    const onError = vi.fn()

    await speech.startListening(vi.fn(), onError)
    expect(speech.activeBackendId.value).toBe('funasr')

    await vi.advanceTimersByTimeAsync(15_000)
    await Promise.resolve()
    expect(speech.activeBackendId.value).toBe('webspeech')

    await vi.advanceTimersByTimeAsync(12_000)
    await Promise.resolve()
    expect(speech.activeBackendId.value).toBe('whisper-web')

    await vi.advanceTimersByTimeAsync(30_000)
    await Promise.resolve()
    expect(speech.error.value).toBe('语音识别无响应，请检查麦克风或使用文字输入。')
    expect(onError).toHaveBeenLastCalledWith('语音识别无响应，请检查麦克风或使用文字输入。')
  })

  it('reports final startup errors and flushes cached text without a backend flush method', async () => {
    Object.defineProperty(navigator, 'userAgent', { value: 'Desktop Chrome', configurable: true })
    mockFunAvailable = false
    mockWebAvailable = false
    mockWhisperMode = 'startup-error'
    mockStartupErrorMsg = '本地模型启动失败'
    mockHubReady = true
    const { useSpeechRecognition } = await import('./composables/useSpeechRecognition')
    const failed = useSpeechRecognition()
    const onError = vi.fn()

    await failed.startListening(vi.fn(), onError)

    expect(failed.error.value).toBe('本地模型启动失败')
    expect(onError).toHaveBeenCalledWith('本地模型启动失败')

    mockFunAvailable = true
    mockWebAvailable = true
    mockWhisperMode = 'success'
    const cached = useSpeechRecognition()
    await cached.startListening(vi.fn(), vi.fn())
    delete (mockLastFunBackend as any)?.flushUtterance

    await expect(cached.flushListening()).resolves.toBe('服务端结果')
  })

  it('handles missing navigator, desktop mic startup mapping, no-current flush, and stop fallback text', async () => {
    vi.stubGlobal('navigator', undefined)
    mockFunAvailable = false
    mockWebAvailable = false
    mockHubReady = false
    const { useSpeechRecognition } = await import('./composables/useSpeechRecognition')
    const unavailable = useSpeechRecognition()
    const unavailableError = vi.fn()

    await unavailable.startListening(vi.fn(), unavailableError)
    expect(unavailable.error.value).toBe('语音识别不可用。请检查麦克风权限或使用文字输入。')

    vi.unstubAllGlobals()
    Object.defineProperty(navigator, 'userAgent', { value: 'Desktop Chrome', configurable: true })
    vi.useFakeTimers()
    mockFunAvailable = true
    mockWebAvailable = true
    mockHubReady = true
    mockFunMode = 'startup-error'
    mockStartupErrorMsg = '麦克风 Permission denied'
    const desktopMic = useSpeechRecognition()
    const desktopMicError = vi.fn()
    const desktopStart = desktopMic.startListening(vi.fn(), desktopMicError, undefined, { continuous: true })
    await vi.advanceTimersByTimeAsync(20_000)
    await desktopStart
    expect(desktopMic.error.value).toBe('麦克风 Permission denied')
    expect(desktopMicError).toHaveBeenLastCalledWith('麦克风 Permission denied')

    vi.useRealTimers()
    mockFunMode = 'success'
    mockFunStopText = ''
    const cachedStop = useSpeechRecognition()
    await cachedStop.startListening(vi.fn(), vi.fn())
    await expect(cachedStop.stopListening()).resolves.toBe('服务端结果')

    const fresh = useSpeechRecognition()
    await expect(fresh.flushListening()).resolves.toBe('')
  })

  it('retries continuous pending sessions on result timeout', async () => {
    vi.useFakeTimers()
    Object.defineProperty(navigator, 'userAgent', { value: 'Desktop Chrome', configurable: true })
    mockFunMode = 'pending'
    const { useSpeechRecognition } = await import('./composables/useSpeechRecognition')
    const speech = useSpeechRecognition()
    const onError = vi.fn()

    void speech.startListening(vi.fn(), onError, undefined, { continuous: true })

    await vi.advanceTimersByTimeAsync(20_000)
    await Promise.resolve()
    expect(mockLastFunBackend?.abort).toHaveBeenCalled()
    expect(speech.loadingHint.value).toBe('正在重连语音服务…')

    await vi.advanceTimersByTimeAsync(1000)
    await Promise.resolve()
    expect(onError).not.toHaveBeenCalled()
    speech.abort()
  })

  it('retries continuous FunASR runtime errors and preserves the latest partial', async () => {
    vi.useFakeTimers()
    Object.defineProperty(navigator, 'userAgent', { value: 'Desktop Chrome', configurable: true })
    mockFunMode = 'ready-error'
    const { useSpeechRecognition } = await import('./composables/useSpeechRecognition')
    const speech = useSpeechRecognition()
    const onError = vi.fn()

    const start = speech.startListening(vi.fn(), onError, undefined, { continuous: true })
    await Promise.resolve()
    expect(speech.interimText.value).toBe('服务端结果')
    expect(speech.loadingHint.value).toBe('正在重连语音服务…')

    mockFunMode = 'success'
    await vi.advanceTimersByTimeAsync(1000)
    await start

    expect(speech.activeBackendId.value).toBe('funasr')
    expect(speech.sessionReady.value).toBe(true)
    expect(speech.interimText.value).toBe('服务端结果')
    expect(onError).not.toHaveBeenCalled()
    await speech.stopListening()
  })

})
