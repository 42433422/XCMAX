import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { effectScope, ref } from 'vue'
import { apiFetch, apiUrl } from '@/utils/apiBase'
import { speakText, stopSpeaking, createChineseUtterance, pauseSpeaking, resumeSpeaking } from '@/utils/tts'
import { useVoiceCall } from './useVoiceCall'
import type { ChatMessage } from './useChatMessages'

vi.mock('@/utils/apiBase', () => ({
  apiFetch: vi.fn(),
  apiUrl: vi.fn((path: string) => path),
}))

vi.mock('@/utils/tts', () => ({
  speakText: vi.fn(),
  stopSpeaking: vi.fn(),
  createChineseUtterance: vi.fn((text: string) => ({ text, onend: null, onerror: null })),
  pauseSpeaking: vi.fn(() => true),
  resumeSpeaking: vi.fn(() => true),
}))

vi.mock('@/utils/sanitizeHtml', () => ({
  plainTextFromChatHtml: (html: string) => String(html).replace(/<[^>]*>/g, ''),
}))

interface VadInstance {
  listening: boolean
  start: () => Promise<void>
  pause: () => Promise<void>
  destroy: () => Promise<void>
  opts: {
    onSpeechStart: () => void
    onSpeechEnd: (audio: Float32Array) => void
    onVADMisfire: () => void
    onFrameProcessed: (probabilities: { isSpeech?: number }) => void
  }
}

const vadState: { throwOnNew: boolean; startReject: boolean; instance: VadInstance | null } = {
  throwOnNew: false,
  startReject: false,
  instance: null,
}

vi.mock('@ricky0123/vad-web', () => ({
  MicVAD: {
    new: vi.fn(async (opts: VadInstance['opts']) => {
      if (vadState.throwOnNew) throw new Error('vad 模型加载失败')
      const instance: VadInstance = {
        listening: false,
        opts,
        start: vi.fn(async () => {
          if (vadState.startReject) throw new Error('vad 启动失败')
          instance.listening = true
        }),
        pause: vi.fn(async () => {}),
        destroy: vi.fn(async () => {}),
      }
      vadState.instance = instance
      return instance
    }),
  },
}))

vi.mock('onnxruntime-web', () => ({ env: { wasm: { numThreads: 0 } } }))

const sendMessageMock = vi.fn<(message: string) => Promise<void>>()
const refreshMessagesMock = vi.fn<() => Promise<void>>()
const messages = ref<ChatMessage[]>([])

let micLevel = 0
let audioDecodeFails = false
let transcriptQueue: string[] = []
let turnComplete = true
let turnDetectOk = true
let transcribeHandler: ((init?: { signal?: AbortSignal }) => Promise<Response>) | null = null
let call: ReturnType<typeof useVoiceCall> | null = null

// jsdom 的 Blob 未实现 arrayBuffer，补齐后 blobToWav16k 才能解出 WAV。
const blobProto = Blob.prototype as Blob & { arrayBuffer?: () => Promise<ArrayBuffer> }
if (typeof blobProto.arrayBuffer !== 'function') {
  Object.defineProperty(blobProto, 'arrayBuffer', {
    configurable: true,
    value: async function arrayBuffer(this: Blob) {
      return new ArrayBuffer(Math.max(8, this.size))
    },
  })
}

const scriptProcessors: Array<{ connect: ReturnType<typeof vi.fn>; onaudioprocess: ((event: unknown) => void) | null }> = []

class MockAnalyser {
  fftSize = 1024
  smoothingTimeConstant = 0
  connect = vi.fn()
  getFloatTimeDomainData(buffer: Float32Array) {
    buffer.fill(micLevel)
  }
}

class MockAudioContext {
  sampleRate = 48_000
  destination = {}
  createMediaStreamSource() { return { connect: vi.fn() } }
  createGain() { return { gain: { value: 1 }, connect: vi.fn() } }
  createBiquadFilter() {
    return { type: '', frequency: { value: 0 }, Q: { value: 0 }, connect: vi.fn() }
  }
  createAnalyser() { return new MockAnalyser() }
  createScriptProcessor() {
    const node = { connect: vi.fn(), onaudioprocess: null as ((event: unknown) => void) | null }
    scriptProcessors.push(node)
    return node
  }
  decodeAudioData = async (_buffer: ArrayBuffer) => {
    if (audioDecodeFails) throw new Error('decode failed')
    return { duration: 0.4 }
  }
  resume() { return Promise.resolve() }
  close() { return Promise.resolve() }
}

class MockOfflineAudioContext {
  destination = {}
  constructor(
    public channels: number,
    public frames: number,
    public rate: number,
  ) {}
  createBufferSource() { return { buffer: null, connect: vi.fn(), start: vi.fn() } }
  startRendering = async () => ({ getChannelData: () => new Float32Array(32) })
}

class MockMediaRecorder {
  static isTypeSupported = vi.fn(() => true)
  static dispatchData = true
  static instances: MockMediaRecorder[] = []
  state: 'inactive' | 'recording' = 'inactive'
  mimeType = 'audio/webm'
  private listeners: Record<string, Array<(event?: unknown) => void>> = {}
  constructor(_stream: unknown, options?: { mimeType?: string }) {
    if (options?.mimeType) this.mimeType = options.mimeType
    MockMediaRecorder.instances.push(this)
  }
  addEventListener(type: string, callback: (event?: unknown) => void) {
    ;(this.listeners[type] ||= []).push(callback)
  }
  start() { this.state = 'recording' }
  stop() {
    if (this.state === 'inactive') return
    this.state = 'inactive'
    if (MockMediaRecorder.dispatchData) {
      this.listeners.dataavailable?.forEach(cb => cb({ data: new Blob(['voice'], { type: this.mimeType }) }))
    }
    this.listeners.stop?.forEach(cb => cb())
  }
}

class MockWebSocket {
  static OPEN = 1
  static instances: MockWebSocket[] = []
  readyState = 0
  binaryType = ''
  sent: unknown[] = []
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  onclose: (() => void) | null = null
  constructor(public url: string) {
    MockWebSocket.instances.push(this)
  }
  send(data: unknown) { this.sent.push(data) }
  close() {
    this.readyState = 3
    this.onclose?.()
  }
  open() { this.readyState = MockWebSocket.OPEN }
  emit(payload: unknown) { this.onmessage?.({ data: JSON.stringify(payload) }) }
}

const originalMediaDevices = Object.getOwnPropertyDescriptor(navigator, 'mediaDevices')
const originalMediaRecorder = Object.getOwnPropertyDescriptor(window, 'MediaRecorder')

function createStream() {
  const track = { stop: vi.fn(), readyState: 'live', applyConstraints: vi.fn(() => Promise.resolve()) }
  return {
    getTracks: () => [track],
    getAudioTracks: () => [track],
  } as unknown as MediaStream
}

function installSupport(getUserMedia: () => Promise<MediaStream> = async () => createStream()) {
  const spy = vi.fn(getUserMedia)
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia: spy } })
  Object.defineProperty(window, 'MediaRecorder', { configurable: true, value: MockMediaRecorder })
  vi.stubGlobal('AudioContext', MockAudioContext)
  vi.stubGlobal('OfflineAudioContext', MockOfflineAudioContext)
  return spy
}

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    text: async () => JSON.stringify(body),
    json: async () => body,
  } as unknown as Response
}

function installApiMock() {
  vi.mocked(apiFetch).mockImplementation(async (url, init) => {
    const target = String(url)
    if (target.includes('/api/voice/turn-detect')) {
      if (!turnDetectOk) return jsonResponse({ success: false }, false, 503)
      return jsonResponse({ success: true, data: { complete: turnComplete } })
    }
    if (target.includes('/api/voice/transcribe')) {
      if (transcribeHandler) return transcribeHandler(init)
      const text = transcriptQueue.length > 1 ? transcriptQueue.shift()! : (transcriptQueue[0] ?? '帮我查下库存')
      return jsonResponse({ success: true, data: { text } })
    }
    return jsonResponse({ success: true })
  })
}

async function flush(): Promise<void> {
  await vi.advanceTimersByTimeAsync(0)
  for (let i = 0; i < 8; i += 1) await Promise.resolve()
  await vi.advanceTimersByTimeAsync(0)
}

async function startCall(getUserMedia?: () => Promise<MediaStream>) {
  if (getUserMedia) installSupport(getUserMedia)
  call = useVoiceCall({ sendMessage: sendMessageMock, messages, refreshMessages: refreshMessagesMock })
  call.start()
  await vi.advanceTimersByTimeAsync(400)
  await flush()
  return call
}

/** 让麦克风先有声再静音，触发一轮断句。 */
async function speakAndStop(voicedMs = 1_100, silenceMs = 900) {
  micLevel = 0.3
  await vi.advanceTimersByTimeAsync(voicedMs)
  micLevel = 0
  await vi.advanceTimersByTimeAsync(silenceMs)
  await flush()
}

/** 推进一轮对话剩余的重试等待、朗读与续听。 */
async function completeTurn(ms = 1_500) {
  await vi.advanceTimersByTimeAsync(ms)
  await flush()
}

describe('useVoiceCall', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    micLevel = 0
    audioDecodeFails = false
    transcriptQueue = []
    turnComplete = true
    turnDetectOk = true
    transcribeHandler = null
    vadState.throwOnNew = false
    vadState.startReject = false
    vadState.instance = null
    MockWebSocket.instances = []
    MockMediaRecorder.instances = []
    MockMediaRecorder.dispatchData = true
    scriptProcessors.length = 0
    messages.value = []
    call = null
    sendMessageMock.mockReset().mockResolvedValue(undefined)
    refreshMessagesMock.mockReset().mockResolvedValue(undefined)
    vi.mocked(speakText).mockReset().mockResolvedValue(true)
    vi.mocked(stopSpeaking).mockReset()
    vi.mocked(createChineseUtterance).mockReset().mockImplementation((text: string) => ({ text, onend: null, onerror: null }))
    vi.mocked(pauseSpeaking).mockReset().mockReturnValue(true)
    vi.mocked(resumeSpeaking).mockReset().mockReturnValue(true)
    vi.mocked(apiUrl).mockReset().mockImplementation((path: string) => path)
    installApiMock()
    vi.stubGlobal('WebSocket', MockWebSocket)
    installSupport()
  })

  afterEach(() => {
    try { call?.hangUp() } catch { /* ignore */ }
    vi.useRealTimers()
    vi.unstubAllGlobals()
    if (originalMediaDevices) Object.defineProperty(navigator, 'mediaDevices', originalMediaDevices)
    else delete (navigator as unknown as { mediaDevices?: unknown }).mediaDevices
    if (originalMediaRecorder) Object.defineProperty(window, 'MediaRecorder', originalMediaRecorder)
    else delete (window as unknown as { MediaRecorder?: unknown }).MediaRecorder
    delete (window as unknown as { __xcagiVoice?: unknown }).__xcagiVoice
  })

  it('缺少麦克风能力时进入已结束并给出原因', async () => {
    delete (navigator as unknown as { mediaDevices?: unknown }).mediaDevices
    call = useVoiceCall({ sendMessage: sendMessageMock, messages })
    call.start()

    expect(call.open.value).toBe(true)
    expect(call.stage.value).toBe('ended')
    expect(call.errorText.value).toContain('不支持麦克风采集')
    expect(call.statusText.value).toContain('不支持麦克风采集')

    call.start()
    expect(call.stage.value).toBe('ended')
  })

  it('缺少录音能力时提示升级客户端', async () => {
    Object.defineProperty(window, 'MediaRecorder', { configurable: true, value: undefined })
    call = useVoiceCall({ sendMessage: sendMessageMock, messages })
    call.start()

    expect(call.stage.value).toBe('ended')
    expect(call.errorText.value).toContain('不支持录音')
  })

  it('开始通话后进入聆听、累计时长，挂断后停止计时', async () => {
    await startCall()
    expect(call!.stage.value).toBe('listening')
    expect(call!.statusText.value).toBe('正在聆听…')
    expect(vadState.instance?.listening).toBe(true)

    await vi.advanceTimersByTimeAsync(1_000)
    expect(call!.seconds.value).toBe(1)
    expect(call!.durationText.value).toBe('00:01')

    call!.hangUp()
    expect(call!.open.value).toBe(false)
    expect(call!.stage.value).toBe('ended')
    expect(call!.statusText.value).toBe('通话已结束')
    expect(vi.mocked(stopSpeaking)).toHaveBeenCalled()
    expect(vadState.instance?.destroy).toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(2_000)
    expect(call!.seconds.value).toBe(1)
  })

  it('不支持流式识别时给出降级提示', async () => {
    vi.stubGlobal('WebSocket', undefined as unknown as typeof WebSocket)
    call = useVoiceCall({ sendMessage: sendMessageMock, messages })
    call.start()

    expect(call.noticeText.value).toContain('不支持流式识别')
    expect(call.stage.value).toBe('connecting')
    call.hangUp()
  })

  it('静音、免提与暂停朗读按状态切换', async () => {
    await startCall()

    call!.toggleMute()
    expect(call!.muted.value).toBe(true)
    expect(call!.stage.value).toBe('muted')
    expect(call!.statusText.value).toBe('已静音')
    expect(vi.mocked(stopSpeaking)).toHaveBeenCalled()

    call!.toggleMute()
    expect(call!.muted.value).toBe(false)
    expect(call!.stage.value).toBe('listening')

    call!.toggleSpeaker()
    expect(call!.speakerOn.value).toBe(false)
    expect(vi.mocked(stopSpeaking)).toHaveBeenCalledTimes(2)

    call!.toggleSpeechPause()
    expect(vi.mocked(pauseSpeaking)).not.toHaveBeenCalled()

    call!.toggleSpeaker()
    expect(call!.speakerOn.value).toBe(true)
    call!.toggleSpeechPause()
    expect(call!.speechPaused.value).toBe(true)
    expect(vi.mocked(pauseSpeaking)).toHaveBeenCalledTimes(1)
    call!.toggleSpeechPause()
    expect(call!.speechPaused.value).toBe(false)
    expect(vi.mocked(resumeSpeaking)).toHaveBeenCalledTimes(1)

    call!.hangUp()
    call!.toggleMute()
    expect(call!.stage.value).toBe('ended')
  })

  it('完整一轮：转写 → 思考 → 朗读 → 回到聆听', async () => {
    vi.stubGlobal('WebSocket', undefined as unknown as typeof WebSocket)
    let resolveTranscribe: (response: Response) => void = () => {}
    let resolveSend: () => void = () => {}
    let resolveSpeak: () => void = () => {}
    let sendStarted = false
    vi.mocked(apiFetch).mockImplementation(async (url) => {
      if (String(url).includes('/turn-detect')) return jsonResponse({ success: true, data: { complete: true } })
      return new Promise<Response>(resolve => { resolveTranscribe = resolve })
    })
    vi.mocked(sendMessageMock).mockImplementation(() => new Promise<void>(resolve => {
      sendStarted = true
      resolveSend = resolve
    }))
    vi.mocked(speakText).mockImplementation(() => new Promise<boolean>(resolve => {
      resolveSpeak = () => resolve(true)
    }))

    await startCall()
    await speakAndStop()
    expect(call!.stage.value).toBe('recognizing')
    expect(call!.statusText.value).toBe('正在识别…')

    resolveTranscribe(jsonResponse({ success: true, data: { text: '帮我查下库存' } }))
    await flush()
    expect(sendStarted).toBe(true)
    expect(call!.heardText.value).toBe('帮我查下库存')
    expect(call!.stage.value).toBe('thinking')
    expect(call!.statusText.value).toBe('正在思考…')

    messages.value = [...messages.value, { role: 'ai', content: '库存还有 12 件', time: '10:00' }]
    resolveSend()
    await flush()
    expect(call!.stage.value).toBe('speaking')
    expect(call!.statusText.value).toBe('正在说话…')
    expect(call!.replyText.value).toBe('库存还有 12 件')
    expect(vi.mocked(speakText)).toHaveBeenCalledWith('库存还有 12 件', expect.objectContaining({ onError: expect.any(Function) }))

    call!.toggleSpeechPause()
    expect(call!.speechPaused.value).toBe(true)
    expect(call!.statusText.value).toBe('朗读已暂停')
    call!.toggleSpeechPause()
    expect(call!.speechPaused.value).toBe(false)

    resolveSpeak()
    await completeTurn(400)
    expect(call!.stage.value).toBe('listening')
    expect(MockMediaRecorder.instances.length).toBeGreaterThanOrEqual(2)
  })

  it('录音为空时重新聆听而不发起对话', async () => {
    MockMediaRecorder.dispatchData = false
    await startCall()
    await speakAndStop()
    await completeTurn()

    expect(sendMessageMock).not.toHaveBeenCalled()
    expect(call!.stage.value).toBe('listening')
  })

  it('转写为空时重试后回到聆听', async () => {
    transcriptQueue = ['', '']
    await startCall()
    await speakAndStop()
    await completeTurn()

    const transcribeCalls = vi.mocked(apiFetch).mock.calls.filter(item => String(item[0]).includes('/transcribe'))
    expect(transcribeCalls).toHaveLength(2)
    expect(sendMessageMock).not.toHaveBeenCalled()
    expect(call!.stage.value).toBe('listening')
  })

  it('转写为低信息量时忽略并继续聆听', async () => {
    transcriptQueue = ['嗯']
    await startCall()
    await speakAndStop()
    await completeTurn()

    expect(sendMessageMock).not.toHaveBeenCalled()
    expect(call!.stage.value).toBe('listening')
  })

  it('转写失败时重试后回到聆听', async () => {
    vi.stubGlobal('WebSocket', undefined as unknown as typeof WebSocket)
    transcribeHandler = async () => jsonResponse({ success: false, detail: '识别服务暂不可用' }, false, 503)
    await startCall()
    await speakAndStop()
    await completeTurn()

    const transcribeCalls = vi.mocked(apiFetch).mock.calls.filter(item => String(item[0]).includes('/transcribe'))
    expect(transcribeCalls).toHaveLength(2)
    expect(sendMessageMock).not.toHaveBeenCalled()
    expect(call!.stage.value).toBe('listening')
  })

  it('转写超时给出重说提示', async () => {
    vi.stubGlobal('WebSocket', undefined as unknown as typeof WebSocket)
    transcribeHandler = (init?: { signal?: AbortSignal }) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })))
    })
    await startCall()
    await speakAndStop()
    expect(call!.stage.value).toBe('recognizing')

    await vi.advanceTimersByTimeAsync(90_000)
    await flush()
    expect(sendMessageMock).not.toHaveBeenCalled()
    expect(call!.stage.value).toBe('listening')
  })

  it('没有回复时回读服务端确认已成功', async () => {
    vi.stubGlobal('WebSocket', undefined as unknown as typeof WebSocket)
    refreshMessagesMock.mockImplementation(async () => {
      messages.value = [...messages.value, { role: 'ai', content: '稍后回复你', time: '10:00' }]
    })
    await startCall()
    await speakAndStop()
    await completeTurn()

    expect(sendMessageMock).toHaveBeenCalledTimes(2)
    expect(refreshMessagesMock).toHaveBeenCalledTimes(1)
    expect(call!.replyText.value).toBe('稍后回复你')
    expect(vi.mocked(speakText)).toHaveBeenCalledWith('稍后回复你', expect.anything())
  })

  it('确实没有回复时提示重说一次', async () => {
    vi.stubGlobal('WebSocket', undefined as unknown as typeof WebSocket)
    await startCall()
    await speakAndStop()
    await vi.advanceTimersByTimeAsync(600)
    await flush()

    expect(sendMessageMock).toHaveBeenCalledTimes(2)
    expect(call!.replyText.value).toBe('这次没拿到回复，请再说一次')
    expect(call!.errorText.value).toContain('网络有点慢')
    expect(vi.mocked(speakText)).toHaveBeenCalledWith('网络有点慢，我没收到回复，请再说一次。', expect.anything())

    await completeTurn(400)
    expect(call!.stage.value).toBe('listening')
  })

  it('执行结果未知时提示不要重复操作', async () => {
    vi.stubGlobal('WebSocket', undefined as unknown as typeof WebSocket)
    sendMessageMock.mockImplementation(async () => {
      messages.value = [...messages.value, { role: 'ai', content: '', time: '10:00', workflowAction: 'unknown' }]
    })
    await startCall()
    await speakAndStop()
    await vi.advanceTimersByTimeAsync(600)
    await flush()

    expect(call!.replyText.value).toContain('正在核对执行结果')
    expect(call!.errorText.value).toContain('结果待核对')
    expect(vi.mocked(speakText)).toHaveBeenCalledWith(expect.stringContaining('不要重复操作'), expect.anything())
  })

  it('对话异常时展示错误并继续聆听', async () => {
    vi.stubGlobal('WebSocket', undefined as unknown as typeof WebSocket)
    sendMessageMock.mockRejectedValue(new Error('网络连接中断，请稍后再试'))
    await startCall()
    await speakAndStop()

    expect(call!.errorText.value).toContain('网络连接中断')

    await completeTurn(400)
    expect(call!.stage.value).toBe('listening')
  })

  it('朗读失败时回退系统语音', async () => {
    vi.stubGlobal('WebSocket', undefined as unknown as typeof WebSocket)
    const systemSpeak = vi.fn((utterance: { onend?: () => void }) => { utterance.onend?.() })
    vi.stubGlobal('speechSynthesis', {
      speak: systemSpeak,
      cancel: vi.fn(),
      speaking: false,
      pending: false,
      pause: vi.fn(),
      resume: vi.fn(),
    })
    vi.mocked(speakText).mockImplementation(async (_text, options) => {
      options?.onError?.(new Error('online tts failed'))
      return false
    })
    messages.value = []

    await startCall()
    sendMessageMock.mockImplementation(async () => {
      messages.value = [...messages.value, { role: 'ai', content: '库存还有 12 件', time: '10:00' }]
    })
    await speakAndStop()
    await completeTurn()

    expect(vi.mocked(createChineseUtterance)).toHaveBeenCalledWith('库存还有 12 件')
    expect(systemSpeak).toHaveBeenCalled()
  })

  it('系统语音也不可用时提示环境不支持朗读', async () => {
    vi.stubGlobal('WebSocket', undefined as unknown as typeof WebSocket)
    Reflect.deleteProperty(window, 'speechSynthesis')
    vi.mocked(speakText).mockImplementation(async (_text, options) => {
      options?.onError?.(new Error('online tts failed'))
      return false
    })
    sendMessageMock.mockImplementation(async () => {
      messages.value = [...messages.value, { role: 'ai', content: '收到', time: '10:00' }]
    })

    await startCall()
    await speakAndStop()
    await completeTurn()

    expect(call!.noticeText.value).toContain('不支持朗读')
  })

  it('麦克风权限被拒绝时提示检查系统设置', async () => {
    await startCall(async () => {
      throw Object.assign(new Error('denied'), { name: 'NotAllowedError' })
    })

    expect(call!.stage.value).toBe('ended')
    expect(call!.errorText.value).toContain('麦克风权限被拒绝')
  })

  it('设备约束失败时退化为最宽松的采集参数', async () => {
    let attempts = 0
    const getUserMedia = vi.fn(async () => {
      attempts += 1
      if (attempts === 1) throw new Error('设备不支持降噪')
      return createStream()
    })
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia } })

    await startCall()
    expect(getUserMedia).toHaveBeenCalledTimes(2)
    expect(getUserMedia.mock.calls[1][0]).toEqual({ audio: true })
    expect(call!.stage.value).toBe('listening')
  })

  it('流式识别可用时更新字幕、发送 PCM 与结束帧', async () => {
    sendMessageMock.mockImplementation(async () => {
      messages.value = [...messages.value, { role: 'ai', content: '库存还有 12 件', time: '10:00' }]
    })
    await startCall()

    micLevel = 0.3
    await vi.advanceTimersByTimeAsync(1_100)
    const ws = MockWebSocket.instances[0]
    expect(ws).toBeTruthy()

    ws.open()
    ws.emit({ type: 'ready' })
    ws.emit({ type: 'partial', text: '帮我查' })
    expect(call!.partialText.value).toBe('帮我查')
    expect(call!.statusText.value).toBe('正在识别…')

    const processor = scriptProcessors[0]
    processor.onaudioprocess?.({ inputBuffer: { getChannelData: () => new Float32Array(48_000) } })
    expect(ws.sent[0]).toBeInstanceOf(ArrayBuffer)
    expect((ws.sent[0] as ArrayBuffer).byteLength).toBe(32_000)

    ws.emit({ type: 'final', text: '帮我查下库存' })
    micLevel = 0
    await vi.advanceTimersByTimeAsync(900)
    await flush()
    await completeTurn()

    expect(ws.sent).toContain(JSON.stringify({ type: 'end' }))
    expect(call!.heardText.value).toBe('帮我查下库存')
    expect(sendMessageMock).toHaveBeenCalledWith('帮我查下库存')
    const transcribeCalls = vi.mocked(apiFetch).mock.calls.filter(item => String(item[0]).includes('/transcribe'))
    expect(transcribeCalls).toHaveLength(0)
    expect(call!.partialText.value).toBe('')
  })

  it('流式识别不可用时降级为整段识别', async () => {
    sendMessageMock.mockImplementation(async () => {
      messages.value = [...messages.value, { role: 'ai', content: '收到', time: '10:00' }]
    })
    await startCall()

    micLevel = 0.3
    await vi.advanceTimersByTimeAsync(1_100)
    const ws = MockWebSocket.instances[0]
    ws.open()
    ws.emit({ type: 'unavailable', reason: 'platform offline' })
    expect(call!.noticeText.value).toContain('流式识别不可用')

    transcriptQueue = ['帮我查下库存']
    micLevel = 0
    await vi.advanceTimersByTimeAsync(900)
    await flush()
    await completeTurn()

    expect(sendMessageMock).toHaveBeenCalledWith('帮我查下库存')
  })

  it('流式识别就绪超时后回退整段识别', async () => {
    sendMessageMock.mockImplementation(async () => {
      messages.value = [...messages.value, { role: 'ai', content: '收到', time: '10:00' }]
    })
    await startCall()

    micLevel = 0.3
    await vi.advanceTimersByTimeAsync(1_100)
    expect(MockWebSocket.instances).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(1_600)

    transcriptQueue = ['帮我查下库存']
    micLevel = 0
    await vi.advanceTimersByTimeAsync(900)
    await flush()
    await completeTurn()

    expect(sendMessageMock).toHaveBeenCalledWith('帮我查下库存')
  })

  it('Smart Turn 判为未说完且没有目的词时先挂起', async () => {
    turnComplete = false
    transcriptQueue = ['文件放在桌上']
    await startCall()
    await speakAndStop()
    await completeTurn()

    expect(vi.mocked(apiFetch).mock.calls.some(item => String(item[0]).includes('/turn-detect'))).toBe(true)
    expect(sendMessageMock).not.toHaveBeenCalled()
    expect(call!.heardText.value).toBe('文件放在桌上')
    expect(call!.stage.value).toBe('listening')
  })

  it('语气词先挂起，超时后合入下一轮再发送', async () => {
    transcriptQueue = ['嗯嗯', '然后']
    await startCall()
    await speakAndStop()
    await completeTurn()

    expect(sendMessageMock).not.toHaveBeenCalled()
    expect(call!.heardText.value).toBe('嗯嗯')

    await vi.advanceTimersByTimeAsync(8_000)
    await speakAndStop()
    await completeTurn()

    expect(sendMessageMock).toHaveBeenCalledWith('嗯嗯然后')
  })

  it('插话：语气词不打断，真打断则停止朗读并作为新一轮', async () => {
    vi.stubGlobal('WebSocket', undefined as unknown as typeof WebSocket)
    let resolveSpeak: () => void = () => {}
    vi.mocked(speakText).mockImplementation(() => new Promise<boolean>(resolve => {
      resolveSpeak = () => resolve(true)
    }))
    sendMessageMock.mockImplementation(async () => {
      messages.value = [...messages.value, { role: 'ai', content: '库存还有 12 件', time: '10:00' }]
    })

    await startCall()
    const vad = vadState.instance
    expect(vad).toBeTruthy()

    vad!.opts.onSpeechStart()
    expect((window as unknown as { __xcagiVoice: { interrupts: number } }).__xcagiVoice.interrupts).toBe(0)

    await speakAndStop()
    await completeTurn(700)
    expect(call!.stage.value).toBe('speaking')
    const callsBefore = sendMessageMock.mock.calls.length

    await vi.advanceTimersByTimeAsync(300)
    vad!.opts.onSpeechStart()
    expect((window as unknown as { __xcagiVoice: { interrupts: number } }).__xcagiVoice.interrupts).toBe(1)

    transcriptQueue = ['嗯']
    vad!.opts.onSpeechEnd(new Float32Array(1_600))
    await flush()
    expect(sendMessageMock.mock.calls.length).toBe(callsBefore)
    expect(vi.mocked(stopSpeaking)).not.toHaveBeenCalled()

    vad!.opts.onSpeechStart()
    transcriptQueue = ['帮我查库存']
    vad!.opts.onSpeechEnd(new Float32Array(3_200))
    await flush()
    expect(vi.mocked(stopSpeaking)).toHaveBeenCalled()

    resolveSpeak()
    await vi.advanceTimersByTimeAsync(400)
    await flush()
    expect(sendMessageMock).toHaveBeenCalledWith('帮我查库存')
  })

  it('VAD 模型加载失败时通话仍然可用', async () => {
    vi.stubGlobal('WebSocket', undefined as unknown as typeof WebSocket)
    vadState.throwOnNew = true
    await startCall()
    await speakAndStop()
    await completeTurn()

    expect(sendMessageMock).toHaveBeenCalledWith('帮我查下库存')
    expect((window as unknown as { __xcagiVoice: { state: string } }).__xcagiVoice.state).toBe('error')
  })

  it('作用域销毁时自动挂断', async () => {
    const scope = effectScope()
    let scoped: ReturnType<typeof useVoiceCall> | null = null
    scope.run(() => {
      scoped = useVoiceCall({ sendMessage: sendMessageMock, messages })
    })
    scoped!.start()
    await vi.advanceTimersByTimeAsync(400)
    await flush()
    expect(scoped!.open.value).toBe(true)

    scope.stop()
    expect(scoped!.open.value).toBe(false)
    expect(scoped!.stage.value).toBe('ended')
  })
})
