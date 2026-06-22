import { afterEach, describe, expect, it, vi } from 'vitest'

let mockToken = 'token'
let mockMobileVoice = false
const mockCaptureStops: unknown[] = []
const mockSharedEnsures: unknown[] = []

vi.mock('./infrastructure/storage/tokenStore', () => ({
  getAccessToken: () => mockToken,
}))

vi.mock('./composables/voiceDevice', () => ({
  isMobileVoiceDevice: () => mockMobileVoice,
}))

vi.mock('./composables/asr/audioCapture', () => ({
  AudioCapture: class MockAudioCapture {
    sampleRate = 32000
    async start(callbacks: { onAudioData: (pcm: Float32Array) => void; onAudioLevel?: (level: number) => void }) {
      callbacks.onAudioLevel?.(0.4)
      callbacks.onAudioData(new Float32Array(1000).fill(0.25))
      callbacks.onAudioData(new Float32Array(1000).fill(-0.25))
      callbacks.onAudioData(new Float32Array(1000).fill(0.5))
    }
    stop() {
      mockCaptureStops.push(this)
    }
  },
  float32ToInt16: (pcm: Float32Array) => new Int16Array(pcm.map((value) => Math.max(-1, Math.min(1, value)) * 32767)),
  resampleFloat32: (pcm: Float32Array) => pcm,
}))

vi.mock('./composables/asr/sharedMicCapture', () => {
  const shared = {
    active: true,
    sampleRate: 16000,
    setHandlers: vi.fn(),
    wake: vi.fn(),
    stop: vi.fn(),
  }
  return {
    ensureSharedMicCapture: vi.fn(async (handlers) => {
      mockSharedEnsures.push(handlers)
      handlers.onAudioData(new Float32Array(3000).fill(0.2))
      return shared
    }),
    getSharedMicCapture: vi.fn(() => shared),
  }
})

class FakeWebSocket {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSED = 3
  static instances: FakeWebSocket[] = []
  static connectMode: 'connected' | 'server-error' | 'open-error' = 'connected'

  readyState = FakeWebSocket.CONNECTING
  binaryType = ''
  sent: unknown[] = []
  url: string
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  onclose: (() => void) | null = null
  onmessage: ((event: { data: unknown }) => void) | null = null

  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
    queueMicrotask(() => {
      if (FakeWebSocket.connectMode === 'open-error') {
        this.onerror?.()
        return
      }
      this.readyState = FakeWebSocket.OPEN
      this.onopen?.()
      queueMicrotask(() => {
        if (FakeWebSocket.connectMode === 'server-error') {
          this.onmessage?.({ data: JSON.stringify({ type: 'error', message: 'server down' }) })
        } else {
          this.onmessage?.({ data: JSON.stringify({ type: 'connected' }) })
        }
      })
    })
  }

  send(data: unknown) {
    this.sent.push(data)
  }

  close() {
    this.readyState = FakeWebSocket.CLOSED
    this.onclose?.()
  }

  emit(payload: Record<string, unknown> | string) {
    this.onmessage?.({ data: typeof payload === 'string' ? payload : JSON.stringify(payload) })
  }
}

async function flushSocketHandshake(ms = 0) {
  await Promise.resolve()
  await Promise.resolve()
  if (ms) await vi.advanceTimersByTimeAsync(ms)
  await Promise.resolve()
  await Promise.resolve()
}

afterEach(() => {
  mockToken = 'token'
  mockMobileVoice = false
  mockCaptureStops.length = 0
  mockSharedEnsures.length = 0
  FakeWebSocket.instances.length = 0
  FakeWebSocket.connectMode = 'connected'
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('FunASR backend extra coverage', () => {
  it('connects, flushes pre-connect PCM, emits segments, flushes utterances, and stops cleanly', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('WebSocket', FakeWebSocket)
    const { FunASRBackend } = await import('./composables/asr/FunASRBackend')
    const backend = new FunASRBackend()
    const onResult = vi.fn()
    const onError = vi.fn()
    const onAudioLevel = vi.fn()
    const onReady = vi.fn()
    const onMicReady = vi.fn()

    const start = backend.start(onResult, onError, onAudioLevel, onReady, onMicReady)
    await flushSocketHandshake()
    await start

    const socket = FakeWebSocket.instances[0]
    expect(socket.url).toContain('/api/asr/funasr?token=token')
    expect(socket.sent[0]).toEqual(expect.stringContaining('"mode":"2pass"'))
    expect(socket.sent.some((item) => item instanceof ArrayBuffer)).toBe(true)
    expect(onMicReady).toHaveBeenCalled()
    expect(onReady).toHaveBeenCalled()
    expect(onAudioLevel).toHaveBeenCalledWith(0.4)

    socket.emit({ mode: '2pass-online', stamp_sents: [{ text_seg: ' 你 ' }, { text_seg: ' 好 ' }] })
    expect(onResult).toHaveBeenLastCalledWith({ text: '你好', isFinal: false, segmentMode: 'online' })

    backend.signalEndOfSpeech()
    expect(socket.sent).toContainEqual(JSON.stringify({ is_speaking: false }))

    const flush = backend.flushUtterance()
    socket.emit({ mode: '2pass-offline', text: '完成' })
    await expect(flush).resolves.toBe('完成')
    expect(socket.sent).toContainEqual(JSON.stringify({ is_speaking: true }))

    const stop = backend.stop()
    socket.emit({ mode: 'offline', text: '最终' })
    await expect(stop).resolves.toBe('最终')
    expect(mockCaptureStops).toHaveLength(1)
  })

  it('uses persistent shared mic and keeps capture alive on abort', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('WebSocket', FakeWebSocket)
    const { FunASRBackend } = await import('./composables/asr/FunASRBackend')
    const backend = new FunASRBackend()

    const start = backend.start(vi.fn(), vi.fn(), undefined, vi.fn(), vi.fn(), undefined, { persistentMic: true })
    await flushSocketHandshake()
    await start

    expect(mockSharedEnsures).toHaveLength(1)
    backend.abort()
    expect(mockCaptureStops).toHaveLength(0)
  })

  it('reports login, open, server, parse, and close errors', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('WebSocket', FakeWebSocket)
    const { FunASRBackend } = await import('./composables/asr/FunASRBackend')

    mockToken = ''
    const loginError = vi.fn()
    await new FunASRBackend().start(vi.fn(), loginError)
    expect(loginError).toHaveBeenCalledWith('请先登录后再使用语音识别。')

    mockToken = 'token'
    FakeWebSocket.connectMode = 'open-error'
    const openError = vi.fn()
    const openStart = new FunASRBackend().start(vi.fn(), openError)
    await flushSocketHandshake()
    await openStart
    expect(openError).toHaveBeenCalledWith('FunASR 服务未启动')

    FakeWebSocket.connectMode = 'server-error'
    const serverError = vi.fn()
    const serverStart = new FunASRBackend().start(vi.fn(), serverError)
    await flushSocketHandshake()
    await serverStart
    expect(serverError).toHaveBeenCalledWith('server down')
    expect(serverError).toHaveBeenCalledWith('FunASR 服务未启动')

    FakeWebSocket.connectMode = 'connected'
    const closeError = vi.fn()
    const backend = new FunASRBackend()
    const start = backend.start(vi.fn(), closeError)
    await flushSocketHandshake()
    await start
    const socket = FakeWebSocket.instances.at(-1)!
    socket.emit('{bad json')
    socket.close()
    await vi.advanceTimersByTimeAsync(2100)
    expect(closeError).toHaveBeenCalledWith('FunASR 服务连接中断')
  })

  it('covers guard paths, message variants, flush timeouts, and cleanup branches', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('WebSocket', FakeWebSocket)
    const { FunASRBackend } = await import('./composables/asr/FunASRBackend')

    const abortedDuringMic = new FunASRBackend()
    await abortedDuringMic.start(vi.fn(), vi.fn(), () => abortedDuringMic.abort())

    const empty = new FunASRBackend() as any
    expect(empty.isLoading()).toBe(false)
    empty.flushPreConnectPcm()
    for (let i = 0; i < 205; i += 1) empty.onPcm(new Float32Array([i]))
    expect(empty._preConnectPcm).toHaveLength(200)
    empty._aborted = true
    empty.onPcm(new Float32Array([1]))
    expect(empty._preConnectPcm).toHaveLength(200)
    empty.clearCloseNotifyTimer()
    empty._closeNotifyTimer = setTimeout(() => undefined, 10)
    empty.clearCloseNotifyTimer()
    expect(empty._closeNotifyTimer).toBeNull()
    await expect(empty.flushUtterance()).resolves.toBe('')
    empty._finalText = 'cached'
    await expect(empty.flushUtterance()).resolves.toBe('cached')
    empty.signalEndOfSpeech()

    const onResult = vi.fn()
    const onError = vi.fn()
    const backend = new FunASRBackend() as any
    const start = backend.start(onResult, onError)
    await flushSocketHandshake()
    await start
    const socket = FakeWebSocket.instances.at(-1)!

    socket.onmessage?.({ data: { mode: 'online', text: '对象消息' } })
    expect(onResult).toHaveBeenLastCalledWith({ text: '对象消息', isFinal: false, segmentMode: 'online' })
    backend.handleServerMessage({ type: 'connected' })
    backend.handleServerMessage({ type: 'error' })
    expect(onError).toHaveBeenLastCalledWith('FunASR 服务错误')
    backend.handleServerMessage({ mode: 'custom', text: '其他模式' })
    expect(onResult).toHaveBeenLastCalledWith({ text: '其他模式', isFinal: false, segmentMode: 'other' })
    backend.handleServerMessage({ stamp_sents: [] })

    backend._pcmChunksSent = 0
    backend._onlinePartial = ''
    backend._finalText = ''
    backend.signalEndOfSpeech()
    backend._aborted = true
    socket.emit({ mode: 'online', text: '忽略' })
    socket.onerror?.()
    socket.onclose?.()
    await vi.advanceTimersByTimeAsync(2100)
    expect(onError).not.toHaveBeenCalledWith('FunASR 服务连接中断')

    backend._aborted = false
    backend._flushing = true
    socket.onclose?.()
    backend._flushing = false
    backend.ws = { readyState: FakeWebSocket.OPEN, send: vi.fn() }
    socket.onclose?.()

    backend.ws = socket
    backend._finalText = 'timeout fallback'
    const timeoutFlush = backend.waitOfflineAfterSpeaking(false)
    await vi.advanceTimersByTimeAsync(8000)
    await expect(timeoutFlush).resolves.toBe('timeout fallback')

    backend.ws = {
      readyState: FakeWebSocket.OPEN,
      send: () => {
        throw new Error('send down')
      },
    }
    backend._finalText = 'send fallback'
    await expect(backend.waitOfflineAfterSpeaking(false)).resolves.toBe('send fallback')

    backend.ws = { readyState: FakeWebSocket.CLOSED, send: vi.fn() }
    backend.sendPcmChunk(new Float32Array(1000))
    backend._ownsCapture = false
    backend._persistentMic = false
    backend.capture = { stop: vi.fn() }
    backend.cleanupWsOnly()
    expect(backend.capture).toBeNull()
    backend.cleanup()
  })

  it('covers connection construction failures, mobile timeouts, server defaults, and aborted handshakes', async () => {
    vi.useFakeTimers()
    const { FunASRBackend } = await import('./composables/asr/FunASRBackend')

    class ThrowingWebSocket {
      static OPEN = 1
      constructor() {
        throw new Error('constructor boom')
      }
    }
    vi.stubGlobal('WebSocket', ThrowingWebSocket)
    const ctorError = vi.fn()
    await new FunASRBackend().start(vi.fn(), ctorError)
    expect(ctorError).toHaveBeenCalledWith('FunASR 连接失败：constructor boom')

    class NeverOpenWebSocket {
      static OPEN = 1
      readyState = 0
      binaryType = ''
      onopen: (() => void) | null = null
      onerror: (() => void) | null = null
      onclose: (() => void) | null = null
      onmessage: ((event: { data: unknown }) => void) | null = null
      sent: unknown[] = []
      constructor(public url: string) {}
      send(data: unknown) { this.sent.push(data) }
      close() { this.readyState = 3; this.onclose?.() }
    }
    mockMobileVoice = true
    vi.stubGlobal('WebSocket', NeverOpenWebSocket)
    const openTimeoutError = vi.fn()
    const openTimeout = new FunASRBackend().start(vi.fn(), openTimeoutError)
    await Promise.resolve()
    await vi.advanceTimersByTimeAsync(18_000)
    await openTimeout
    expect(openTimeoutError).toHaveBeenCalledWith('FunASR 服务未启动')

    class OpenNoServerWebSocket extends NeverOpenWebSocket {
      constructor(url: string) {
        super(url)
        queueMicrotask(() => {
          this.readyState = 1
          this.onopen?.()
        })
      }
    }
    mockMobileVoice = false
    vi.stubGlobal('WebSocket', OpenNoServerWebSocket)
    const serverTimeoutError = vi.fn()
    const serverTimeout = new FunASRBackend().start(vi.fn(), serverTimeoutError)
    await flushSocketHandshake()
    await vi.advanceTimersByTimeAsync(10_000)
    await serverTimeout
    expect(serverTimeoutError).toHaveBeenCalledWith('FunASR 服务未启动')

    class ServerDefaultErrorWebSocket extends OpenNoServerWebSocket {
      constructor(url: string) {
        super(url)
        queueMicrotask(() => {
          queueMicrotask(() => this.onmessage?.({ data: JSON.stringify({ type: 'error' }) }))
        })
      }
    }
    vi.stubGlobal('WebSocket', ServerDefaultErrorWebSocket)
    const defaultServerError = vi.fn()
    const defaultServerStart = new FunASRBackend().start(vi.fn(), defaultServerError)
    await flushSocketHandshake()
    await defaultServerStart
    expect(defaultServerError).toHaveBeenCalledWith('FunASR 服务错误')

    class ServerOnErrorWebSocket extends OpenNoServerWebSocket {
      constructor(url: string) {
        super(url)
        queueMicrotask(() => {
          queueMicrotask(() => this.onerror?.())
        })
      }
    }
    vi.stubGlobal('WebSocket', ServerOnErrorWebSocket)
    const serverOnError = vi.fn()
    const serverOnErrorStart = new FunASRBackend().start(vi.fn(), serverOnError)
    await flushSocketHandshake()
    await serverOnErrorStart
    expect(serverOnError).toHaveBeenCalledWith('FunASR 服务未启动')

    vi.stubGlobal('WebSocket', OpenNoServerWebSocket)
    const aborted = new FunASRBackend()
    const abortedError = vi.fn()
    const abortedStart = aborted.start(vi.fn(), abortedError)
    await flushSocketHandshake()
    aborted.abort()
    await vi.advanceTimersByTimeAsync(10_000)
    await abortedStart
    expect(abortedError).not.toHaveBeenCalledWith('FunASR 服务未启动')
  })
})
