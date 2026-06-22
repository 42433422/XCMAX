import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'

const asrMocks = vi.hoisted(() => {
  class FakeAudioCapture {
    static instances: FakeAudioCapture[] = []
    sampleRate = 48000
    opts: any = null
    stopped = false
    constructor() { FakeAudioCapture.instances.push(this) }
    async start(opts: any) {
      this.opts = opts
      opts.onAudioLevel?.(0.42)
      opts.onAudioData?.(new Float32Array(2200).fill(0.2))
    }
    stop() { this.stopped = true }
  }

  class FakeRecognizer {
    handlers: Record<string, Function> = {}
    accepted: Array<{ pcm: Float32Array; rate: number }> = []
    removed = false
    on(event: string, cb: Function) { this.handlers[event] = cb }
    acceptWaveformFloat(pcm: Float32Array, rate: number) { this.accepted.push({ pcm, rate }) }
    retrieveFinalResult() { return { result: { text: 'vosk final' } } }
    remove() { this.removed = true }
  }

  return {
    FakeAudioCapture,
    FakeRecognizer,
    createVoskClient: vi.fn(async () => ({ KaldiRecognizer: FakeRecognizer })),
    workers: [] as any[],
  }
})

vi.mock('./composables/asr/audioCapture', () => ({
  AudioCapture: asrMocks.FakeAudioCapture,
  resampleFloat32: vi.fn((pcm: Float32Array) => pcm),
}))

vi.mock('@lichess-org/vosk-browser', () => ({
  createVoskClient: asrMocks.createVoskClient,
}))

class FakeWorker {
  onmessage: ((e: MessageEvent) => void) | null = null
  onerror: ((e: ErrorEvent) => void) | null = null
  listeners: Record<string, Function[]> = { message: [], error: [] }
  terminated = false
  messages: unknown[] = []
  constructor() { asrMocks.workers.push(this) }
  postMessage(msg: any) {
    this.messages.push(msg)
    if (msg.type === 'init') {
      setTimeout(() => this.emitMessage({ type: 'ready' }), 0)
    }
    if (msg.type === 'transcribe') {
      setTimeout(() => this.emitMessage({ type: 'result', jobId: msg.jobId, data: 'whisper text' }), 0)
    }
  }
  addEventListener(type: string, cb: Function) { this.listeners[type] ||= []; this.listeners[type].push(cb) }
  removeEventListener(type: string, cb: Function) { this.listeners[type] = (this.listeners[type] || []).filter((x) => x !== cb) }
  terminate() { this.terminated = true }
  emitMessage(data: any) {
    const event = { data } as MessageEvent
    this.onmessage?.(event)
    for (const cb of this.listeners.message || []) cb(event)
  }
  emitError(message = 'worker failed') {
    const event = { message } as ErrorEvent
    this.onerror?.(event)
    for (const cb of this.listeners.error || []) cb(event)
  }
}

function finalEvent(text: string, isFinal = true) {
  const seg: any = [{ transcript: text }]
  seg.isFinal = isFinal
  return { resultIndex: 0, results: [seg] }
}

beforeEach(() => {
  vi.useFakeTimers()
  asrMocks.FakeAudioCapture.instances.length = 0
  asrMocks.workers.length = 0
  asrMocks.createVoskClient.mockClear()
  Object.defineProperty(globalThis, 'Worker', { configurable: true, value: FakeWorker })
  Object.defineProperty(window, 'SpeechRecognition', { configurable: true, value: undefined })
  Object.defineProperty(window, 'webkitSpeechRecognition', { configurable: true, value: undefined })
  Object.defineProperty(navigator, 'userAgent', { configurable: true, value: 'Mozilla/5.0 Chrome' })
  Object.defineProperty(globalThis, 'fetch', {
    configurable: true,
    value: vi.fn(async () => new Response('ok', { status: 200 })),
  })
})

afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
})

describe('coverage ASR backends', () => {
  it('covers WebSpeech recognition lifecycle, errors and iOS restart', async () => {
    const { WebSpeechBackend } = await import('./composables/asr/WebSpeechBackend')
    const recs: any[] = []
    class FakeSpeechRecognition {
      lang = ''
      interimResults = false
      continuous = false
      onresult: any = null
      onerror: any = null
      onend: any = null
      start = vi.fn()
      stop = vi.fn()
      abort = vi.fn()
      constructor() { recs.push(this) }
    }
    Object.defineProperty(window, 'SpeechRecognition', { configurable: true, value: FakeSpeechRecognition })

    const backend = new WebSpeechBackend()
    expect(backend.isAvailable()).toBe(true)
    expect(backend.isLoading()).toBe(false)
    const results: any[] = []
    const errors: string[] = []
    const levels: number[] = []
    const ready = vi.fn()
    await backend.start((r) => results.push(r), (e) => errors.push(e), (l) => levels.push(l), ready)
    expect(ready).toHaveBeenCalled()
    const rec = recs[0]
    rec.onresult(finalEvent('临时文本', false))
    rec.onresult(finalEvent('最终文本', true))
    rec.onerror({ error: 'network' })
    rec.onerror({ error: 'no-speech' })
    expect(results).toEqual(expect.arrayContaining([
      { text: '临时文本', isFinal: false },
      { text: '最终文本', isFinal: true },
    ]))
    expect(errors[0]).toContain('语音服务连接失败')
    expect(levels).toContain(0.42)
    await expect(backend.flushUtterance()).resolves.toBe('最终文本')
    rec.onresult(finalEvent('结束补全', false))
    rec.onend()
    expect(results).toContainEqual({ text: '结束补全', isFinal: true })
    await expect(backend.stop()).resolves.toBe('结束补全')
    backend.abort()

    Object.defineProperty(navigator, 'userAgent', { configurable: true, value: 'iPhone Safari' })
    const ios = new WebSpeechBackend()
    await ios.start(() => undefined, () => undefined)
    const iosRec = recs[1]
    iosRec.onend()
    await vi.advanceTimersByTimeAsync(280)
    expect(iosRec.start).toHaveBeenCalledTimes(2)
    ios.abort()
  })

  it('covers WebSpeech unsupported, fallback, stopped, flush, and start-error branches', async () => {
    const { WebSpeechBackend } = await import('./composables/asr/WebSpeechBackend')

    const unavailable = new WebSpeechBackend()
    const unsupportedErrors: string[] = []
    expect(unavailable.isAvailable()).toBe(false)
    await unavailable.start(() => undefined, (e) => unsupportedErrors.push(e))
    expect(unsupportedErrors[0]).toContain('不支持语音识别')

    const recs: any[] = []
    class FakeWebkitRecognition {
      lang = ''
      interimResults = false
      continuous = false
      onresult: any = null
      onerror: any = null
      onend: any = null
      start = vi.fn()
      stop = vi.fn()
      abort = vi.fn()
      constructor() { recs.push(this) }
    }
    Object.defineProperty(window, 'webkitSpeechRecognition', { configurable: true, value: FakeWebkitRecognition })
    const backend = new WebSpeechBackend()
    expect(backend.isAvailable()).toBe(true)
    const results: any[] = []
    const errors: string[] = []
    await backend.start((r) => results.push(r), (e) => errors.push(e))
    const rec = recs[0]
    const emptySeg: any = [{}]
    emptySeg.isFinal = false
    rec.onresult({ resultIndex: 0, results: [emptySeg] })
    rec.onresult(finalEvent('  临时 flush  ', false))
    await expect(backend.flushUtterance()).resolves.toBe('临时 flush')
    rec.onerror({ error: 'unknown-code' })
    rec.onerror({})
    expect(errors).toEqual(['语音识别失败：unknown-code', '语音识别失败'])
    backend.abort()
    rec.onresult(finalEvent('ignored', true))
    rec.onerror({ error: 'network' })
    rec.onend()
    expect(results).not.toContainEqual({ text: 'ignored', isFinal: true })

    class ThrowingRecognition extends FakeWebkitRecognition {
      start = vi.fn(() => {
        throw new Error('start boom')
      })
    }
    Object.defineProperty(window, 'SpeechRecognition', { configurable: true, value: ThrowingRecognition })
    Object.defineProperty(window, 'webkitSpeechRecognition', { configurable: true, value: undefined })
    const errorStart = new WebSpeechBackend()
    const startErrors: string[] = []
    await errorStart.start(() => undefined, (e) => startErrors.push(e))
    expect(startErrors).toContain('start boom')

    class StringThrowingRecognition extends FakeWebkitRecognition {
      start = vi.fn(() => {
        throw 'string boom'
      })
    }
    Object.defineProperty(window, 'SpeechRecognition', { configurable: true, value: StringThrowingRecognition })
    const stringStart = new WebSpeechBackend()
    await stringStart.start(() => undefined, (e) => startErrors.push(e))
    expect(startErrors).toContain('string boom')

    const originalAudioStart = asrMocks.FakeAudioCapture.prototype.start
    asrMocks.FakeAudioCapture.prototype.start = vi.fn(async () => {
      throw new Error('level capture failed')
    })
    Object.defineProperty(window, 'SpeechRecognition', { configurable: true, value: FakeWebkitRecognition })
    const levelFallback = new WebSpeechBackend()
    await levelFallback.start(() => undefined, (e) => startErrors.push(e), () => undefined)
    expect((levelFallback as any).levelCapture).toBe(null)
    asrMocks.FakeAudioCapture.prototype.start = originalAudioStart
    await levelFallback.stop()

    const originalWindow = window
    Object.defineProperty(globalThis, 'window', { configurable: true, value: undefined })
    expect(new WebSpeechBackend().isAvailable()).toBe(false)
    Object.defineProperty(globalThis, 'window', { configurable: true, value: originalWindow })
  })

  it('covers WebSpeech iOS restart guard and failure branches', async () => {
    const { WebSpeechBackend } = await import('./composables/asr/WebSpeechBackend')
    const recs: any[] = []
    class FakeSpeechRecognition {
      lang = ''
      interimResults = false
      continuous = false
      onresult: any = null
      onerror: any = null
      onend: any = null
      start = vi.fn()
      stop = vi.fn()
      abort = vi.fn()
      constructor() { recs.push(this) }
    }
    Object.defineProperty(window, 'SpeechRecognition', { configurable: true, value: FakeSpeechRecognition })
    Object.defineProperty(navigator, 'userAgent', { configurable: true, value: 'iPhone Safari' })

    const clearPending = new WebSpeechBackend()
    await clearPending.start(() => undefined, () => undefined)
    const pendingRec = recs.at(-1)
    pendingRec.onend()
    pendingRec.onend()
    clearPending.abort()

    const maxRestarts = new WebSpeechBackend()
    await maxRestarts.start(() => undefined, () => undefined)
    const maxRestartRec = recs.at(-1)
    ;(maxRestarts as any)._restartCount = 200
    maxRestartRec.onend()
    await vi.advanceTimersByTimeAsync(500)
    expect(maxRestartRec.start).toHaveBeenCalledTimes(1)

    const maxFailures = new WebSpeechBackend()
    await maxFailures.start(() => undefined, () => undefined)
    const maxFailureRec = recs.at(-1)
    ;(maxFailures as any)._restartFailures = 8
    maxFailureRec.onend()
    await vi.advanceTimersByTimeAsync(500)
    expect(maxFailureRec.start).toHaveBeenCalledTimes(1)

    const stale = new WebSpeechBackend()
    await stale.start(() => undefined, () => undefined)
    const staleRec = recs.at(-1)
    staleRec.onend()
    ;(stale as any).rec = {}
    await vi.advanceTimersByTimeAsync(280)
    expect(staleRec.start).toHaveBeenCalledTimes(1)

    const failed = new WebSpeechBackend()
    await failed.start(() => undefined, () => undefined)
    const failedRec = recs.at(-1)
    failedRec.start.mockImplementation(() => {
      throw new Error('busy')
    })
    failedRec.onend()
    await vi.advanceTimersByTimeAsync(280)
    expect((failed as any)._restartFailures).toBe(1)
    failed.abort()
  })

  it('covers Vosk loading, result, stop and abort paths', async () => {
    const mod = await import('./composables/asr/VoskBackend')
    mod.invalidateVoskCache()
    const backend = new mod.VoskBackend()
    expect(backend.isAvailable()).toBe(true)
    const results: any[] = []
    const errors: string[] = []
    const ready = vi.fn()
    await backend.start((r) => results.push(r), (e) => errors.push(e), undefined, ready)
    expect(ready).toHaveBeenCalled()
    const capture = asrMocks.FakeAudioCapture.instances.at(-1)!
    const recognizer = (capture.opts && asrMocks.createVoskClient.mock.results.length) ? null : null
    expect(errors).toEqual([])
    const client = await asrMocks.createVoskClient.mock.results.at(-1)!.value
    const rec = new client.KaldiRecognizer(16000)
    rec.handlers.partialresult = vi.fn()
    expect(rec).toBeTruthy()

    const backendAny = backend as any
    backendAny.recognizer.handlers.partialresult({ result: { partial: 'vosk partial' } })
    backendAny.recognizer.handlers.result({ result: { text: 'vosk done' } })
    expect(results).toContainEqual({ text: 'vosk partial', isFinal: false })
    expect(results).toContainEqual({ text: 'vosk done', isFinal: true })
    await expect(backend.stop()).resolves.toBe('vosk final')
    await backend.start(() => undefined, (e) => errors.push(e))
    backend.abort()
  })

  it('covers Whisper worker readiness, chunk processing, flush, stop and abort', async () => {
    const { WhisperWebBackend } = await import('./composables/asr/WhisperWebBackend')
    const backend = new WhisperWebBackend()
    expect(backend.isAvailable()).toBe(true)
    expect(backend.isLoading()).toBe(true)
    const results: any[] = []
    const errors: string[] = []
    const ready = vi.fn()
    const startPromise = backend.start((r) => results.push(r), (e) => errors.push(e), undefined, ready)
    await vi.advanceTimersByTimeAsync(0)
    await startPromise
    expect(ready).toHaveBeenCalled()
    expect(errors).toEqual([])
    const firstCapture = asrMocks.FakeAudioCapture.instances.at(-1)!
    firstCapture.opts.onAudioData(new Float32Array(2200).fill(0.25))
    ;(backend as any).processChunk()
    await vi.advanceTimersByTimeAsync(0)
    expect(results).toContainEqual({ text: 'whisper text', isFinal: false })

    const capture = asrMocks.FakeAudioCapture.instances.at(-1)!
    capture.opts.onAudioData(new Float32Array(2200).fill(0.3))
    const flushPromise = backend.flushUtterance()
    await vi.advanceTimersByTimeAsync(0)
    await expect(flushPromise).resolves.toBe('whisper text')
    expect(results).toContainEqual({ text: 'whisper text', isFinal: true })
    capture.opts.onAudioData(new Float32Array(2200).fill(0.4))
    const stopPromise = backend.stop()
    await vi.advanceTimersByTimeAsync(0)
    await expect(stopPromise).resolves.toBe('whisper text')
    backend.abort()
    expect(asrMocks.workers.at(-1).terminated).toBe(true)
  })

  it('covers Whisper worker error, timeout, stale job, microphone failure, and stop fallbacks', async () => {
    const { WhisperWebBackend } = await import('./composables/asr/WhisperWebBackend')

    const noWorkerBackend = new WhisperWebBackend() as any
    await expect(noWorkerBackend.waitForModelReady(1)).resolves.toBe(false)

    const errors: string[] = []
    const timeoutBackend = new WhisperWebBackend()
    class SilentWorker extends FakeWorker {
      postMessage(msg: any) {
        this.messages.push(msg)
      }
    }
    Object.defineProperty(globalThis, 'Worker', { configurable: true, value: SilentWorker })
    const timeoutStart = timeoutBackend.start(() => undefined, (e) => errors.push(e))
    await vi.advanceTimersByTimeAsync(18_000)
    await timeoutStart
    expect(errors.at(-1)).toContain('Whisper 模型加载失败')

    errors.length = 0
    class InitErrorWorker extends FakeWorker {
      postMessage(msg: any) {
        this.messages.push(msg)
        if (msg.type === 'init') {
          setTimeout(() => this.emitMessage({ type: 'error', data: '模型坏了' }), 0)
        }
      }
    }
    Object.defineProperty(globalThis, 'Worker', { configurable: true, value: InitErrorWorker })
    const initErrorStart = new WhisperWebBackend().start(() => undefined, (e) => errors.push(e))
    await vi.advanceTimersByTimeAsync(0)
    await initErrorStart
    expect(errors.at(-1)).toBe('模型坏了')

    errors.length = 0
    class StartupErrorWorker extends FakeWorker {
      postMessage(msg: any) {
        this.messages.push(msg)
        if (msg.type === 'init') setTimeout(() => this.emitError(''), 0)
      }
    }
    Object.defineProperty(globalThis, 'Worker', { configurable: true, value: StartupErrorWorker })
    const startupErrorStart = new WhisperWebBackend().start(() => undefined, (e) => errors.push(e))
    await vi.advanceTimersByTimeAsync(0)
    await startupErrorStart
    expect(errors.at(-1)).toContain('Whisper Worker 错误')

    Object.defineProperty(globalThis, 'Worker', { configurable: true, value: FakeWorker })
    const originalStart = asrMocks.FakeAudioCapture.prototype.start
    asrMocks.FakeAudioCapture.prototype.start = async () => {
      throw new Error('permission denied')
    }
    const micErrorStart = new WhisperWebBackend().start(() => undefined, (e) => errors.push(e))
    await vi.advanceTimersByTimeAsync(0)
    await micErrorStart
    expect(errors.at(-1)).toContain('麦克风启动失败：permission denied')
    asrMocks.FakeAudioCapture.prototype.start = originalStart

    const backend = new WhisperWebBackend() as any
    const results: any[] = []
    const runtimeErrors: string[] = []
    const startPromise = backend.start((r: any) => results.push(r), (e: string) => runtimeErrors.push(e))
    await vi.advanceTimersByTimeAsync(0)
    await startPromise
    expect(backend.ensureWorker()).toBe(backend.ensureWorker())
    await expect(backend.waitForModelReady(1)).resolves.toBe(true)

    const worker = asrMocks.workers.at(-1)!
    worker.emitMessage({ type: 'result', jobId: -1, data: 'stale text' })
    worker.emitMessage({ type: 'error', jobId: -1, data: 'stale error' })
    worker.emitMessage({ type: 'error', jobId: 9999, data: 'job error' })
    worker.emitMessage({ type: 'error', data: 'runtime error' })
    expect(results).not.toContainEqual({ text: 'stale text', isFinal: false })
    expect(runtimeErrors.at(-1)).toBe('runtime error')

    backend.processChunk()
    backend.audioBuffer = [new Float32Array(10)]
    backend.processChunk()

    const jobId = backend.nextJobId()
    const failedTranscribe = backend.transcribeBuffer(new Float32Array(2200), jobId)
    worker.emitMessage({ type: 'error', jobId, data: 'chunk failed' })
    await expect(failedTranscribe).resolves.toBe('')

    backend._lastText = 'last partial'
    backend.audioBuffer = [new Float32Array(2200)]
    backend.transcribeBuffer = vi.fn(async () => '')
    await expect(backend.stop()).resolves.toBe('last partial')
    expect(results).toContainEqual({ text: 'last partial', isFinal: true })

    const abortBackend = new WhisperWebBackend()
    const abortStart = abortBackend.start(() => undefined, () => undefined)
    await vi.advanceTimersByTimeAsync(0)
    await abortStart
    abortBackend.abort()
    expect(asrMocks.workers.at(-1).terminated).toBe(true)
  })

  it('covers HF hub host resolution and probe success/failure', async () => {
    const hf = await import('./composables/asr/hfHub')
    expect(hf.resolveHfRemoteHost()).toMatch(/hf-hub|huggingface/)
    await expect(hf.probeWhisperHubReady()).resolves.toBe(true)
    vi.mocked(fetch).mockResolvedValueOnce(new Response('missing', { status: 404 }))
    await expect(hf.probeWhisperHubReady()).resolves.toBe(false)
    vi.mocked(fetch).mockRejectedValueOnce(new Error('offline'))
    await expect(hf.probeWhisperHubReady()).resolves.toBe(false)
  })
})
