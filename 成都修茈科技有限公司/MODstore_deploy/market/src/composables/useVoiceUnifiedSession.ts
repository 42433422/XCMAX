import { ref } from 'vue'
import type { ASRResult } from './asr/types'
import { AudioCapture, float32ToInt16, resampleFloat32 } from './asr/audioCapture'
import { ensureSharedMicCapture } from './asr/sharedMicCapture'
import { S2sMseAudioPlayer } from './s2sMseAudioPlayer'
import { markVoiceLatency, reportVoiceLatencyIfComplete } from './voiceLatency'
import { refreshLevelAndWalletAfterLlm } from '../utils/llmBillingRefresh'

export type VoiceUnifiedState = 'idle' | 'connecting' | 'ready' | 'listening' | 'streaming' | 'speaking' | 'error'

export interface VoiceUnifiedEndUtteranceOpts {
  text: string
  turnId: string
  system: string
  messages: Array<{ role: 'user' | 'assistant'; content: string }>
  provider: string
  model: string
  voice: string
  rate: number
  ttsEnabled: boolean
  maxTokens?: number
  onTextDelta: (delta: string, soFar: string) => void
}

function buildWsUrl(): string {
  const token = localStorage.getItem('modstore_token') || ''
  const proto = typeof location !== 'undefined' && location.protocol === 'https:' ? 'wss' : 'ws'
  const host = typeof location !== 'undefined' ? location.host : 'localhost'
  return `${proto}://${host}/api/workbench/voice/unified/ws?token=${encodeURIComponent(token)}`
}

const SEND_CHUNK = 960

export function useVoiceUnifiedSession() {
  const state = ref<VoiceUnifiedState>('idle')
  const lastError = ref('')
  const audioLevel = ref(0)
  const activeBackendId = ref('unified')
  const sessionReady = ref(false)
  const loadingHint = ref('')

  let ws: WebSocket | null = null
  let capture: AudioCapture | null = null
  let onAsrResult: ((r: ASRResult) => void) | null = null
  let onAsrError: ((msg: string) => void) | null = null
  let onAudioLevel: ((level: number) => void) | null = null
  let turnResolve: ((content: string) => void) | null = null
  let turnReject: ((e: Error) => void) | null = null
  let onTextDelta: VoiceUnifiedEndUtteranceOpts['onTextDelta'] | null = null
  const msePlayer = new S2sMseAudioPlayer()
  let llmFirstMarked = false
  let activeTurnId = ''

  function b64ToBytes(b64: string): Uint8Array {
    const binary = atob(b64)
    const bytes = new Uint8Array(binary.length)
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
    return bytes
  }

  function handleWsMessage(raw: string) {
    let msg: Record<string, unknown>
    try {
      msg = JSON.parse(raw) as Record<string, unknown>
    } catch {
      return
    }
    const type = String(msg.type || '')

    if (type === 'ready' || type === 'connected') {
      state.value = 'ready'
      sessionReady.value = true
      loadingHint.value = ''
      return
    }

    if (type === 'asr_partial') {
      state.value = 'listening'
      onAsrResult?.({
        text: String(msg.text || ''),
        isFinal: false,
        segmentMode: 'online',
      })
      return
    }

    if (type === 'asr_final') {
      markVoiceLatency('asr_final')
      onAsrResult?.({
        text: String(msg.text || ''),
        isFinal: true,
        segmentMode: 'offline',
      })
      return
    }

    if (type === 'text_delta') {
      if (!llmFirstMarked) {
        markVoiceLatency('llm_first_token')
        llmFirstMarked = true
      }
      state.value = 'streaming'
      onTextDelta?.(String(msg.delta || ''), String(msg.so_far || ''))
      return
    }

    if (type === 'audio_chunk') {
      const b64 = String(msg.data_b64 || '')
      if (b64) {
        if (!msePlayer.isPlaying) {
          msePlayer.beginTurn()
          markVoiceLatency('tts_first_audio')
        }
        state.value = 'speaking'
        msePlayer.appendChunk(String(msg.sentence_id || 's0'), b64ToBytes(b64))
      }
      return
    }

    if (type === 'audio_sentence_end') {
      msePlayer.endSentence(String(msg.sentence_id || 's0'))
      return
    }

    if (type === 'text_done') {
      msePlayer.endTurn()
      void refreshLevelAndWalletAfterLlm()
      reportVoiceLatencyIfComplete()
      turnResolve?.(String(msg.content || ''))
      turnResolve = null
      turnReject = null
      onTextDelta = null
      return
    }

    if (type === 'turn_done') {
      msePlayer.endTurn()
      if (turnResolve) {
        reportVoiceLatencyIfComplete()
        turnResolve('')
      }
      return
    }

    if (type === 'cancelled') {
      turnResolve?.('')
      turnResolve = null
      turnReject = null
      msePlayer.reset()
      state.value = sessionReady.value ? 'ready' : 'idle'
      return
    }

    if (type === 'error') {
      const err = String(msg.message || '统一语音通道错误')
      lastError.value = err
      onAsrError?.(err)
      turnReject?.(new Error(err))
      turnReject = null
      turnResolve = null
      state.value = 'error'
    }
  }

  function sendPcm(pcm: Float32Array) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    const rate = capture?.sampleRate ?? 16000
    const resampled = resampleFloat32(pcm, rate, 16000)
    const i16 = float32ToInt16(resampled)
    const frame = new Uint8Array(i16.byteLength)
    frame.set(i16)
    try {
      ws.send(frame.buffer)
    } catch {
      /* ignore */
    }
  }

  async function connect(): Promise<void> {
    if (ws?.readyState === WebSocket.OPEN) return
    state.value = 'connecting'
    loadingHint.value = '正在连接统一语音通道…'
    return new Promise<void>((resolve, reject) => {
      ws = new WebSocket(buildWsUrl())
      ws.binaryType = 'arraybuffer'
      ws.onopen = () => resolve()
      ws.onmessage = (ev) => {
        if (typeof ev.data === 'string') handleWsMessage(ev.data)
      }
      ws.onerror = () => {
        lastError.value = '统一语音通道连接失败'
        reject(new Error(lastError.value))
      }
      ws.onclose = () => {
        sessionReady.value = false
        if (state.value !== 'error') state.value = 'idle'
      }
    })
  }

  async function startListening(
    onResult: (r: ASRResult) => void,
    onError: (msg: string) => void,
    onLevel?: (level: number) => void,
  ): Promise<void> {
    onAsrResult = onResult
    onAsrError = onError
    onAudioLevel = onLevel ?? null
    await connect()
    capture = await ensureSharedMicCapture({
      onAudioData: (pcm) => sendPcm(pcm),
      onAudioLevel: (l) => {
        audioLevel.value = l
        onAudioLevel?.(l)
      },
    })
    state.value = 'listening'
    sessionReady.value = true
    loadingHint.value = ''
  }

  function signalEndOfSpeech(): void {
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    markVoiceLatency('speech_end')
    try {
      ws.send(JSON.stringify({ type: 'speech_end' }))
    } catch {
      /* ignore */
    }
  }

  async function flushListening(): Promise<string> {
    signalEndOfSpeech()
    return ''
  }

  async function stopListening(): Promise<string> {
    try {
      capture?.stop()
    } catch {
      /* ignore */
    }
    capture = null
    sessionReady.value = false
    state.value = 'idle'
    return ''
  }

  function abort(): void {
    cancelTurn()
    try {
      capture?.stop()
    } catch {
      /* ignore */
    }
    capture = null
    try {
      ws?.close()
    } catch {
      /* ignore */
    }
    ws = null
    sessionReady.value = false
    state.value = 'idle'
    onAsrResult = null
    onAsrError = null
  }

  function cancelTurn(): void {
    msePlayer.reset()
    llmFirstMarked = false
    if (ws?.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify({ type: 'cancel' }))
      } catch {
        /* ignore */
      }
    }
    turnResolve = null
    turnReject = null
    onTextDelta = null
  }

  function buildTurnPayload(opts: VoiceUnifiedEndUtteranceOpts, type: 'end_utterance' | 'utterance' | 'utterance_start') {
    const turnId = opts.turnId || `t${Date.now()}`
    activeTurnId = turnId
    return {
      type,
      turn_id: turnId,
      text: opts.text,
      system: opts.system,
      messages: opts.messages,
      provider: opts.provider,
      model: opts.model,
      voice: opts.voice,
      rate: opts.rate,
      tts_enabled: opts.ttsEnabled,
      max_tokens: opts.maxTokens ?? 1024,
    }
  }

  async function endUtterance(opts: VoiceUnifiedEndUtteranceOpts): Promise<string> {
    await connect()
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      throw new Error(lastError.value || '统一语音未连接')
    }
    llmFirstMarked = false
    msePlayer.reset()
    msePlayer.beginTurn()
    onTextDelta = opts.onTextDelta
    state.value = 'streaming'

    return await new Promise<string>((resolve, reject) => {
      turnResolve = (c) => resolve(c || '（无回复）')
      turnReject = reject
      ws!.send(JSON.stringify(buildTurnPayload(opts, 'end_utterance')))
    })
  }

  /** partial 稳定：提前开 LLM+TTS（与 S2S utterance_start 对齐） */
  async function runTurnStart(opts: VoiceUnifiedEndUtteranceOpts): Promise<void> {
    await connect()
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      throw new Error(lastError.value || '统一语音未连接')
    }
    llmFirstMarked = false
    msePlayer.reset()
    msePlayer.beginTurn()
    onTextDelta = opts.onTextDelta
    state.value = 'streaming'
    ws!.send(JSON.stringify(buildTurnPayload(opts, 'utterance_start')))
  }

  function sendUtteranceFinalize(text: string, turnId: string) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    ws.send(JSON.stringify({ type: 'utterance_finalize', turn_id: turnId, text }))
  }

  function isPlaying(): boolean {
    return msePlayer.isPlaying
  }

  async function whenAudioIdle(): Promise<void> {
    await msePlayer.whenIdle()
    if (state.value === 'speaking') {
      state.value = sessionReady.value ? 'ready' : 'idle'
    }
  }

  function disconnect(): void {
    abort()
  }

  return {
    state,
    lastError,
    audioLevel,
    activeBackendId,
    sessionReady,
    loadingHint,
    connect,
    disconnect,
    startListening,
    signalEndOfSpeech,
    flushListening,
    stopListening,
    abort,
    endUtterance,
    runTurnStart,
    sendUtteranceFinalize,
    cancelTurn,
    isPlaying,
    whenAudioIdle,
  }
}

/** 与 useSpeechRecognition 对齐的桥接，供 useVoiceContinuousChat 注入 */
export function createUnifiedAsrBridge(session: ReturnType<typeof useVoiceUnifiedSession>) {
  return {
    error: session.lastError,
    interimText: ref(''),
    audioLevel: session.audioLevel,
    loadingHint: session.loadingHint,
    activeBackendId: session.activeBackendId,
    sessionReady: session.sessionReady,
    startListening: (
      onResult: (r: ASRResult) => void,
      onError: (msg: string) => void,
      onLevel?: (level: number) => void,
      _onReady?: () => void,
      _onMic?: () => void,
      _stream?: MediaStream,
      _opts?: { continuous?: boolean },
    ) => session.startListening(onResult, onError, onLevel),
    flushListening: () => session.flushListening(),
    signalEndOfSpeech: () => session.signalEndOfSpeech(),
    stopListening: () => session.stopListening(),
    abort: (opts?: { keepMic?: boolean }) => session.abort(),
  }
}
