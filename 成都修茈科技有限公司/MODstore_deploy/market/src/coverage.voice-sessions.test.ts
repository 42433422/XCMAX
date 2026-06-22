import { afterEach, describe, expect, it, vi } from 'vitest'

const mockRefreshLevelAndWalletAfterLlm = vi.fn(async () => undefined)
const mockMarkVoiceLatency = vi.fn()
const mockReportVoiceLatencyIfComplete = vi.fn(() => ({ speech_to_tts_ms: 1 }))
const mockPlayers: MockMsePlayer[] = []
const mockCaptureStops: unknown[] = []

class MockMsePlayer {
  isPlaying = false
  beginTurn = vi.fn()
  appendChunk = vi.fn(() => {
    this.isPlaying = true
  })
  endSentence = vi.fn()
  endTurn = vi.fn(() => {
    this.isPlaying = false
  })
  reset = vi.fn(() => {
    this.isPlaying = false
  })
  whenIdle = vi.fn(async () => {
    this.isPlaying = false
  })
  constructor() {
    mockPlayers.push(this)
  }
}

vi.mock('./composables/s2sMseAudioPlayer', () => ({
  S2sMseAudioPlayer: MockMsePlayer,
}))

vi.mock('./utils/llmBillingRefresh', () => ({
  refreshLevelAndWalletAfterLlm: () => mockRefreshLevelAndWalletAfterLlm(),
}))

vi.mock('./composables/voiceLatency', () => ({
  markVoiceLatency: (name: string) => mockMarkVoiceLatency(name),
  reportVoiceLatencyIfComplete: () => mockReportVoiceLatencyIfComplete(),
}))

vi.mock('./composables/asr/audioCapture', () => ({
  AudioCapture: class MockAudioCapture {},
  float32ToInt16: (pcm: Float32Array) => new Int16Array(pcm.map((value) => value * 32767)),
  resampleFloat32: (pcm: Float32Array) => pcm,
}))

vi.mock('./composables/asr/sharedMicCapture', () => ({
  ensureSharedMicCapture: vi.fn(async (handlers) => {
    handlers.onAudioLevel?.(0.7)
    handlers.onAudioData(new Float32Array([0.1, -0.1]))
    return {
      sampleRate: 48000,
      stop: vi.fn(() => {
        mockCaptureStops.push('stopped')
      }),
    }
  }),
}))

class FakeAudio {
  static instances: FakeAudio[] = []
  onended: (() => void) | null = null
  onerror: (() => void) | null = null
  src = ''
  pause = vi.fn()
  play = vi.fn(async () => undefined)
  constructor(src: string) {
    this.src = src
    FakeAudio.instances.push(this)
  }
}

class FakeWebSocket {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSED = 3
  static instances: FakeWebSocket[] = []
  readyState = FakeWebSocket.CONNECTING
  binaryType = ''
  sent: unknown[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: { data: unknown }) => void) | null = null
  onerror: (() => void) | null = null
  onclose: (() => void) | null = null
  constructor(public url: string) {
    FakeWebSocket.instances.push(this)
  }
  open() {
    this.readyState = FakeWebSocket.OPEN
    this.onopen?.()
  }
  send(data: unknown) {
    this.sent.push(data)
  }
  emit(payload: Record<string, unknown> | string) {
    this.onmessage?.({ data: typeof payload === 'string' ? payload : JSON.stringify(payload) })
  }
  error() {
    this.onerror?.()
  }
  close() {
    this.readyState = FakeWebSocket.CLOSED
    this.onclose?.()
  }
}

function turnOptions(overrides: Record<string, unknown> = {}) {
  return {
    text: '你好',
    system: 'system',
    messages: [{ role: 'user' as const, content: 'hi' }],
    provider: 'openai',
    model: 'gpt',
    voice: 'alloy',
    rate: 1,
    ttsEnabled: true,
    maxTokens: 64,
    turnId: 'turn-1',
    onTextDelta: vi.fn(),
    ...overrides,
  }
}

afterEach(() => {
  mockRefreshLevelAndWalletAfterLlm.mockClear()
  mockMarkVoiceLatency.mockClear()
  mockReportVoiceLatencyIfComplete.mockClear()
  mockPlayers.length = 0
  mockCaptureStops.length = 0
  FakeAudio.instances.length = 0
  FakeWebSocket.instances.length = 0
  localStorage.clear()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('voice session coverage', () => {
  it('runs S2S turns, handles text/audio messages, cancels, and disconnects', async () => {
    vi.stubGlobal('WebSocket', FakeWebSocket)
    vi.stubGlobal('Audio', FakeAudio)
    Object.defineProperty(URL, 'createObjectURL', {
      value: vi.fn(() => 'blob:legacy'),
      configurable: true,
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      value: vi.fn(),
      configurable: true,
    })
    localStorage.setItem('modstore_token', 's2s-token')
    const { useVoiceS2SSession } = await import('./composables/useVoiceS2SSession')
    const session = useVoiceS2SSession()
    const onTextDelta = vi.fn()

    const turn = session.runTurn(turnOptions({ onTextDelta }))
    const ws = FakeWebSocket.instances[0]
    expect(ws.url).toContain('/api/workbench/voice/s2s/ws?token=s2s-token')
    ws.open()
    ws.emit({ type: 'ready' })
    await Promise.resolve()

    expect(JSON.parse(ws.sent[0] as string)).toMatchObject({
      type: 'utterance',
      turn_id: 'turn-1',
      tts_enabled: true,
      max_tokens: 64,
    })
    ws.emit({ type: 'text_delta', delta: '你', so_far: '你' })
    expect(onTextDelta).toHaveBeenCalledWith('你', '你')

    ws.emit({ type: 'audio_chunk', sentence_id: 's1', data_b64: btoa('a') })
    ws.emit({ type: 'audio_sentence_end', sentence_id: 's1' })
    expect(mockPlayers[0].appendChunk).toHaveBeenCalled()
    expect(mockPlayers[0].endSentence).toHaveBeenCalledWith('s1')

    ws.emit({ type: 'audio_sentence', data_b64: btoa('b'), mime: 'audio/mp3' })
    expect(FakeAudio.instances[0].play).toHaveBeenCalled()
    FakeAudio.instances[0].onended?.()

    ws.emit({ type: 'text_done', content: '完成' })
    await expect(turn).resolves.toEqual({ content: '完成', aborted: false })
    expect(mockRefreshLevelAndWalletAfterLlm).toHaveBeenCalled()

    await session.runTurnStart(turnOptions({ turnId: 'turn-2' }))
    expect(JSON.parse(ws.sent.at(-1) as string)).toMatchObject({ type: 'utterance_start', provisional: true })
    session.sendUtteranceFinalize('最终', 'turn-2')
    expect(JSON.parse(ws.sent.at(-1) as string)).toEqual({ type: 'utterance_finalize', turn_id: 'turn-2', text: '最终' })

    session.cancelTurn()
    expect(JSON.parse(ws.sent.at(-1) as string)).toEqual({ type: 'cancel', turn_id: 'turn-2' })
    await session.whenAudioIdle()
    expect(session.isPlaying()).toBe(false)
    session.disconnect()
    expect(session.state.value).toBe('idle')
  })

  it('rejects S2S connection and turn errors', async () => {
    vi.stubGlobal('WebSocket', FakeWebSocket)
    const { useVoiceS2SSession } = await import('./composables/useVoiceS2SSession')
    const session = useVoiceS2SSession()
    const connecting = session.connect()
    const ws = FakeWebSocket.instances[0]
    ws.error()
    await expect(connecting).rejects.toThrow('语音对话通道连接失败')
    expect(session.state.value).toBe('error')

    const next = useVoiceS2SSession()
    const turn = next.runTurn(turnOptions())
    const ws2 = FakeWebSocket.instances[1]
    ws2.open()
    ws2.emit({ type: 'ready' })
    await Promise.resolve()
    ws2.emit({ type: 'error', message: '服务错误' })
    await expect(turn).rejects.toThrow('服务错误')
  })

  it('runs unified voice ASR and end-utterance flow', async () => {
    vi.stubGlobal('WebSocket', FakeWebSocket)
    localStorage.setItem('modstore_token', 'unified-token')
    const { createUnifiedAsrBridge, useVoiceUnifiedSession } = await import('./composables/useVoiceUnifiedSession')
    const session = useVoiceUnifiedSession()
    const onResult = vi.fn()
    const onError = vi.fn()
    const onLevel = vi.fn()

    const start = session.startListening(onResult, onError, onLevel)
    const ws = FakeWebSocket.instances[0]
    expect(ws.url).toContain('/api/workbench/voice/unified/ws?token=unified-token')
    ws.open()
    await start

    expect(session.state.value).toBe('listening')
    expect(session.audioLevel.value).toBe(0.7)
    expect(onLevel).toHaveBeenCalledWith(0.7)
    expect(ws.sent.some((item) => item instanceof ArrayBuffer)).toBe(true)

    ws.emit({ type: 'connected' })
    expect(session.sessionReady.value).toBe(true)
    ws.emit({ type: 'asr_partial', text: '半句' })
    ws.emit({ type: 'asr_final', text: '整句' })
    expect(onResult).toHaveBeenCalledWith({ text: '半句', isFinal: false, segmentMode: 'online' })
    expect(onResult).toHaveBeenCalledWith({ text: '整句', isFinal: true, segmentMode: 'offline' })

    session.signalEndOfSpeech()
    expect(JSON.parse(ws.sent.at(-1) as string)).toEqual({ type: 'speech_end' })
    await expect(session.flushListening()).resolves.toBe('')

    const onTextDelta = vi.fn()
    const end = session.endUtterance(turnOptions({ onTextDelta }))
    await Promise.resolve()
    expect(JSON.parse(ws.sent.at(-1) as string)).toMatchObject({ type: 'end_utterance', turn_id: 'turn-1' })
    ws.emit({ type: 'text_delta', delta: '答', so_far: '答' })
    expect(onTextDelta).toHaveBeenCalledWith('答', '答')
    ws.emit({ type: 'audio_chunk', sentence_id: 'u1', data_b64: btoa('c') })
    ws.emit({ type: 'audio_sentence_end', sentence_id: 'u1' })
    ws.emit({ type: 'text_done', content: '回答' })
    await expect(end).resolves.toBe('回答')
    expect(mockMarkVoiceLatency).toHaveBeenCalledWith('tts_first_audio')
    expect(mockReportVoiceLatencyIfComplete).toHaveBeenCalled()

    await session.runTurnStart(turnOptions({ turnId: 'turn-3' }))
    expect(JSON.parse(ws.sent.at(-1) as string)).toMatchObject({ type: 'utterance_start', turn_id: 'turn-3' })
    session.sendUtteranceFinalize('最终', 'turn-3')
    expect(JSON.parse(ws.sent.at(-1) as string)).toEqual({ type: 'utterance_finalize', turn_id: 'turn-3', text: '最终' })
    session.cancelTurn()
    expect(JSON.parse(ws.sent.at(-1) as string)).toEqual({ type: 'cancel' })

    await session.whenAudioIdle()
    expect(session.isPlaying()).toBe(false)
    await expect(session.stopListening()).resolves.toBe('')
    expect(mockCaptureStops).toContain('stopped')

    const bridge = createUnifiedAsrBridge(session)
    await bridge.startListening(onResult, onError, onLevel)
    expect(bridge.activeBackendId.value).toBe('unified')
    bridge.signalEndOfSpeech()
    await expect(bridge.flushListening()).resolves.toBe('')
    await expect(bridge.stopListening()).resolves.toBe('')
    bridge.abort({ keepMic: true })
  })

  it('reports unified websocket errors and cancellation messages', async () => {
    vi.stubGlobal('WebSocket', FakeWebSocket)
    const { useVoiceUnifiedSession } = await import('./composables/useVoiceUnifiedSession')
    const session = useVoiceUnifiedSession()
    const connecting = session.connect()
    const ws = FakeWebSocket.instances[0]
    ws.error()
    await expect(connecting).rejects.toThrow('统一语音通道连接失败')

    const live = useVoiceUnifiedSession()
    const start = live.startListening(vi.fn(), vi.fn())
    const ws2 = FakeWebSocket.instances[1]
    ws2.open()
    await start
    const end = live.endUtterance(turnOptions())
    await Promise.resolve()
    ws2.emit({ type: 'cancelled' })
    await expect(end).resolves.toBe('（无回复）')

    const rejected = live.endUtterance(turnOptions())
    await Promise.resolve()
    ws2.emit({ type: 'error', message: '统一错误' })
    await expect(rejected).rejects.toThrow('统一错误')
    expect(live.lastError.value).toBe('统一错误')
  })
})
