import { ref } from 'vue'
import { refreshLevelAndWalletAfterLlm } from '../utils/llmBillingRefresh'
import { S2sMseAudioPlayer } from './s2sMseAudioPlayer'

export type VoiceS2SState = 'idle' | 'connecting' | 'ready' | 'streaming' | 'speaking' | 'error'

export interface VoiceS2STurnOptions {
  text: string
  system: string
  messages: Array<{ role: 'user' | 'assistant'; content: string }>
  provider: string
  model: string
  voice: string
  rate: number
  ttsEnabled: boolean
  maxTokens?: number
  turnId?: string
  /** utterance_start：不等 offline 即开 LLM */
  provisional?: boolean
  onTextDelta: (delta: string, soFar: string) => void
}

function buildWsUrl(): string {
  const token = localStorage.getItem('modstore_token') || ''
  const proto = typeof location !== 'undefined' && location.protocol === 'https:' ? 'wss' : 'ws'
  const host = typeof location !== 'undefined' ? location.host : 'localhost'
  return `${proto}://${host}/api/workbench/voice/s2s/ws?token=${encodeURIComponent(token)}`
}

function b64ToBytes(b64: string): Uint8Array {
  const binary = atob(b64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
  return bytes
}

function bytesToArrayBuffer(bytes: Uint8Array): ArrayBuffer {
  const copy = new Uint8Array(bytes.byteLength)
  copy.set(bytes)
  return copy.buffer
}

export function useVoiceS2SSession() {
  const state = ref<VoiceS2SState>('idle')
  const lastError = ref('')

  let ws: WebSocket | null = null
  let readyResolve: (() => void) | null = null
  let readyReject: ((e: Error) => void) | null = null
  let turnResolve: ((full: string) => void) | null = null
  let turnReject: ((e: Error) => void) | null = null
  let onTextDelta: VoiceS2STurnOptions['onTextDelta'] | null = null
  let activeTurnId = ''
  const msePlayer = new S2sMseAudioPlayer()

  /** 兼容旧版整句 MP3 */
  const legacyAudioQueue: Blob[] = []
  let legacyPlaying = false
  let legacyAudio: HTMLAudioElement | null = null
  const legacyUrls: string[] = []

  function cleanupLegacyAudio() {
    if (legacyAudio) {
      legacyAudio.pause()
      legacyAudio.src = ''
      legacyAudio = null
    }
    for (const u of legacyUrls) URL.revokeObjectURL(u)
    legacyUrls.length = 0
    legacyAudioQueue.length = 0
    legacyPlaying = false
  }

  function playLegacyNext() {
    if (legacyPlaying || !legacyAudioQueue.length) return
    const blob = legacyAudioQueue.shift()
    if (!blob) return
    legacyPlaying = true
    state.value = 'speaking'
    const url = URL.createObjectURL(blob)
    legacyUrls.push(url)
    legacyAudio = new Audio(url)
    const done = () => {
      legacyPlaying = false
      playLegacyNext()
      if (!legacyPlaying && !legacyAudioQueue.length && !msePlayer.isPlaying) {
        state.value = ws?.readyState === WebSocket.OPEN ? 'ready' : 'idle'
      }
    }
    legacyAudio.onended = done
    legacyAudio.onerror = done
    void legacyAudio.play().catch(done)
  }

  function cleanupAudio() {
    msePlayer.endTurn()
    msePlayer.reset()
    cleanupLegacyAudio()
  }

  function beginAudioTurn() {
    msePlayer.beginTurn()
  }

  function settleTurn(content: string) {
    void refreshLevelAndWalletAfterLlm()
    turnResolve?.(content)
    turnResolve = null
    turnReject = null
    onTextDelta = null
    if (!msePlayer.isPlaying && !legacyPlaying && !legacyAudioQueue.length) {
      state.value = ws?.readyState === WebSocket.OPEN ? 'ready' : 'idle'
    }
  }

  function failTurn(err: string) {
    lastError.value = err
    state.value = 'error'
    turnReject?.(new Error(err))
    turnReject = null
    turnResolve = null
    onTextDelta = null
  }

  function handleMessage(raw: string) {
    let msg: Record<string, unknown>
    try {
      msg = JSON.parse(raw) as Record<string, unknown>
    } catch {
      return
    }
    const type = String(msg.type || '')

    if (type === 'ready') {
      state.value = 'ready'
      readyResolve?.()
      readyResolve = null
      readyReject = null
      return
    }

    if (type === 'text_delta') {
      state.value = 'streaming'
      onTextDelta?.(String(msg.delta || ''), String(msg.so_far || ''))
      return
    }

    if (type === 'audio_chunk') {
      const b64 = String(msg.data_b64 || '')
      const sid = String(msg.sentence_id || 's0')
      if (b64) {
        state.value = 'speaking'
        msePlayer.appendChunk(sid, b64ToBytes(b64))
      }
      return
    }

    if (type === 'audio_sentence_end') {
      msePlayer.endSentence(String(msg.sentence_id || 's0'))
      return
    }

    if (type === 'audio_sentence') {
      const b64 = String(msg.data_b64 || '')
      if (b64) {
        legacyAudioQueue.push(new Blob([bytesToArrayBuffer(b64ToBytes(b64))], { type: String(msg.mime || 'audio/mpeg') }))
        playLegacyNext()
      }
      return
    }

    if (type === 'text_done') {
      msePlayer.endTurn()
      settleTurn(String(msg.content || ''))
      return
    }

    if (type === 'turn_done') {
      msePlayer.endTurn()
      if (turnResolve) settleTurn('')
      return
    }

    if (type === 'cancelled') {
      settleTurn('')
      cleanupAudio()
      return
    }

    if (type === 'error') {
      failTurn(String(msg.message || 'S2S 错误'))
    }
  }

  function connect(): Promise<void> {
    if (ws?.readyState === WebSocket.OPEN) {
      state.value = 'ready'
      return Promise.resolve()
    }
    if (ws?.readyState === WebSocket.CONNECTING) {
      return new Promise<void>((resolve, reject) => {
        const prevR = readyResolve
        const prevJ = readyReject
        readyResolve = () => {
          prevR?.()
          resolve()
        }
        readyReject = (e) => {
          prevJ?.(e)
          reject(e)
        }
      })
    }

    disconnect()
    state.value = 'connecting'
    lastError.value = ''

    return new Promise<void>((resolve, reject) => {
      readyResolve = resolve
      readyReject = reject
      ws = new WebSocket(buildWsUrl())
      ws.onmessage = (ev) => {
        const data = typeof ev.data === 'string' ? ev.data : ''
        if (data) handleMessage(data)
      }
      ws.onerror = () => {
        failTurn('语音对话通道连接失败')
        readyReject?.(new Error(lastError.value))
        readyResolve = null
        readyReject = null
      }
      ws.onclose = () => {
        ws = null
        if (state.value !== 'error') state.value = 'idle'
      }
    })
  }

  function disconnect() {
    cancelTurn()
    cleanupAudio()
    try {
      ws?.close()
    } catch {
      /* ignore */
    }
    ws = null
    state.value = 'idle'
    readyResolve = null
    readyReject = null
    activeTurnId = ''
  }

  function cancelTurn() {
    cleanupAudio()
    if (ws?.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify({ type: 'cancel', turn_id: activeTurnId }))
      } catch {
        /* ignore */
      }
    }
    turnResolve = null
    turnReject = null
    onTextDelta = null
    activeTurnId = ''
  }

  function buildPayload(opts: VoiceS2STurnOptions) {
    const turnId = opts.turnId || `t${Date.now()}`
    activeTurnId = turnId
    return {
      type: opts.provisional ? 'utterance_start' : 'utterance',
      turn_id: turnId,
      provisional: !!opts.provisional,
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

  async function runTurn(opts: VoiceS2STurnOptions): Promise<{ content: string; aborted: boolean }> {
    await connect()
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      throw new Error(lastError.value || 'S2S 未连接')
    }

    cleanupAudio()
    beginAudioTurn()
    state.value = 'streaming'
    onTextDelta = opts.onTextDelta

    return await new Promise<{ content: string; aborted: boolean }>((resolve, reject) => {
      turnResolve = (full) => resolve({ content: full || '（无回复）', aborted: false })
      turnReject = reject
      ws!.send(JSON.stringify(buildPayload(opts)))
    })
  }

  /** partial 稳定：提前开 LLM（provisional） */
  async function runTurnStart(opts: VoiceS2STurnOptions): Promise<void> {
    await connect()
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      throw new Error(lastError.value || 'S2S 未连接')
    }
    onTextDelta = opts.onTextDelta
    beginAudioTurn()
    state.value = 'streaming'
    ws.send(JSON.stringify(buildPayload({ ...opts, provisional: true })))
  }

  function sendUtteranceFinalize(text: string, turnId: string) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    ws.send(
      JSON.stringify({
        type: 'utterance_finalize',
        turn_id: turnId,
        text,
      }),
    )
  }

  function isPlaying(): boolean {
    return msePlayer.isPlaying || legacyPlaying || legacyAudioQueue.length > 0
  }

  async function whenAudioIdle(): Promise<void> {
    await msePlayer.whenIdle()
    while (legacyPlaying || legacyAudioQueue.length) {
      await new Promise((r) => setTimeout(r, 60))
    }
    if (state.value === 'speaking') {
      state.value = ws?.readyState === WebSocket.OPEN ? 'ready' : 'idle'
    }
  }

  return {
    state,
    lastError,
    connect,
    disconnect,
    runTurn,
    runTurnStart,
    sendUtteranceFinalize,
    cancelTurn,
    isPlaying,
    whenAudioIdle,
    stopAudio: cleanupAudio,
  }
}
