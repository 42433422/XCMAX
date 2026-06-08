import type { ASRBackend, ASRResult } from './types'
import { AudioCapture, float32ToInt16, resampleFloat32 } from './audioCapture'
import { ensureSharedMicCapture, getSharedMicCapture } from './sharedMicCapture'
import { getAccessToken } from '../../infrastructure/storage/tokenStore'
import { isMobileVoiceDevice } from '../voiceDevice'

export type FunASRStartOptions = {
  /** 持续聆听：只重连 WS，不销毁麦克风流 */
  persistentMic?: boolean
}

function extractFunAsrText(msg: Record<string, unknown>): string {
  const direct = String(msg.text ?? '').trim()
  if (direct) return direct
  const sents = msg.stamp_sents as Array<{ text_seg?: string }> | undefined
  if (Array.isArray(sents) && sents.length) {
    return sents
      .map((s) => String(s.text_seg || '').replace(/\s+/g, ''))
      .join('')
      .trim()
  }
  return ''
}

export class FunASRBackend implements ASRBackend {
  id = 'funasr' as const
  label = 'FunASR 服务端'
  private ws: WebSocket | null = null
  private capture: AudioCapture | null = null
  private _onResult: ((r: ASRResult) => void) | null = null
  private _onError: ((msg: string) => void) | null = null
  private _onReady: (() => void) | null = null
  private _finalText = ''
  private _onlinePartial = ''
  private _offlineFinal = ''
  private _aborted = false
  private _flushWaiter: ((text: string) => void) | null = null
  private _flushing = false
  private _closeNotifyTimer: ReturnType<typeof setTimeout> | null = null
  private _gotServerMsg = false
  private _pcmChunksSent = 0
  /** 已发送 session 配置后才允许向 FunASR 送 PCM */
  private _sessionConfigured = false
  /** WS/配置未就绪时暂存原始 PCM，配置发送后一次性补发 */
  private _preConnectPcm: Float32Array[] = []
  private static wsOpenTimeoutMs(): number {
    return isMobileVoiceDevice() ? 18000 : 10000
  }
  private static serverReadyTimeoutMs(): number {
    return isMobileVoiceDevice() ? 20000 : 10000
  }
  private _audioBuffer: Float32Array[] = []
  private _audioBufferLen = 0
  private readonly _SEND_CHUNK_SAMPLES = 960
  private _persistentMic = false
  private _ownsCapture = true

  isAvailable(): boolean {
    return typeof window !== 'undefined' && typeof WebSocket !== 'undefined'
  }

  isLoading(): boolean {
    return false
  }

  async start(
    onResult: (r: ASRResult) => void,
    onError: (msg: string) => void,
    onAudioLevel?: (level: number) => void,
    onReady?: () => void,
    onMicReady?: () => void,
    mediaStream?: MediaStream,
    options?: FunASRStartOptions,
  ): Promise<void> {
    this._onResult = onResult
    this._onError = onError
    this._onReady = onReady ?? null
    this._aborted = false
    this._persistentMic = !!options?.persistentMic
    this._ownsCapture = !this._persistentMic
    this._finalText = ''
    this._onlinePartial = ''
    this._offlineFinal = ''
    this._gotServerMsg = false
    this._pcmChunksSent = 0
    this._sessionConfigured = false
    this._preConnectPcm = []
    this.clearCloseNotifyTimer()

    // 先开麦克风再连 WS，避免 FunASR 收到 is_speaking:true 后长时间无音频
    try {
      if (this._persistentMic) {
        this.capture = await ensureSharedMicCapture(
          {
            onAudioData: (pcm) => this.onPcm(pcm),
            onAudioLevel: onAudioLevel ?? undefined,
          },
          mediaStream,
        )
      } else {
        this.capture = new AudioCapture()
        await this.capture.start(
          {
            onAudioData: (pcm) => this.onPcm(pcm),
            onAudioLevel: onAudioLevel ?? undefined,
          },
          mediaStream,
        )
      }
    } catch (e: unknown) {
      this.cleanupWsOnly()
      const msg = e instanceof Error ? e.message : String(e)
      onError('麦克风启动失败：' + msg)
      return
    }
    if (this._aborted) {
      this.cleanupWsOnly()
      return
    }
    onMicReady?.()

    const connected = await this.connectWs(onError)
    if (!connected || this._aborted) {
      this.cleanupWsOnly()
      return
    }

    this._onReady?.()
  }

  private onPcm(pcm: Float32Array) {
    if (this._aborted) return
    if (!this._sessionConfigured) {
      this._preConnectPcm.push(pcm)
      if (this._preConnectPcm.length > 200) this._preConnectPcm.shift()
      return
    }
    this.sendPcmChunk(pcm)
  }

  private flushPreConnectPcm() {
    if (!this._preConnectPcm.length) return
    const pending = this._preConnectPcm
    this._preConnectPcm = []
    for (const pcm of pending) this.sendPcmChunk(pcm)
  }

  private clearCloseNotifyTimer() {
    if (this._closeNotifyTimer) {
      clearTimeout(this._closeNotifyTimer)
      this._closeNotifyTimer = null
    }
  }

  private async connectWs(onError: (msg: string) => void): Promise<boolean> {
    const fail = (msg: string) => {
      onError(msg)
      return false
    }
    const wsUrl = this.buildWsUrl()
    if (!wsUrl) {
      return fail('请先登录后再使用语音识别。')
    }
    try {
      this.ws = new WebSocket(wsUrl)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      return fail('FunASR 连接失败：' + msg)
    }
    this.ws.binaryType = 'arraybuffer'

    const wsOpen = await new Promise<boolean>((resolve) => {
      const timer = setTimeout(() => { resolve(false) }, FunASRBackend.wsOpenTimeoutMs())
      this.ws!.onopen = () => { clearTimeout(timer); resolve(true) }
      this.ws!.onerror = () => { clearTimeout(timer); resolve(false) }
    })

    if (!wsOpen || !this.ws || this.ws.readyState !== WebSocket.OPEN) {
      return fail('FunASR 服务未启动')
    }

    const serverReady = await new Promise<boolean>((resolve) => {
      const timer = setTimeout(() => { resolve(false) }, FunASRBackend.serverReadyTimeoutMs())
      const ws = this.ws!

      const finish = (ok: boolean) => {
        clearTimeout(timer)
        resolve(ok)
      }

      ws.onmessage = (ev) => {
        if (this._aborted) return
        try {
          const msg = typeof ev.data === 'string' ? JSON.parse(ev.data) : ev.data
          if (msg.type === 'error') {
            onError(String(msg.message || 'FunASR 服务错误'))
            finish(false)
            return
          }
          if (msg.type === 'connected') finish(true)
        } catch { /* wait */ }
      }
      ws.onerror = () => finish(false)
      ws.onclose = () => finish(false)
    })

    if (!serverReady || !this.ws || this.ws.readyState !== WebSocket.OPEN) {
      if (!this._aborted) return fail('FunASR 服务未启动')
      return false
    }

    this.ws.onmessage = (ev) => {
      if (this._aborted) return
      this._gotServerMsg = true
      this.clearCloseNotifyTimer()
      try {
        const msg = typeof ev.data === 'string' ? JSON.parse(ev.data) : ev.data
        this.handleServerMessage(msg)
      } catch (e) {
        console.warn('[FunASR] parse error:', e, 'data:', ev.data)
      }
    }

    this.ws.onclose = () => {
      if (this._aborted || this._flushing) return
      this.clearCloseNotifyTimer()
      this._closeNotifyTimer = setTimeout(() => {
        this._closeNotifyTimer = null
        if (this._aborted || this._flushing) return
        if (this.ws?.readyState === WebSocket.OPEN) return
        this._onError?.('FunASR 服务连接中断')
      }, 2000)
    }

    this.ws.onerror = () => {
      if (this._aborted) return
      try { this.ws?.close() } catch { /* */ }
    }

    this.sendSessionConfig()
    return true
  }

  private sendSessionConfig() {
    this._audioBuffer = []
    this._audioBufferLen = 0
    this.ws?.send(
      JSON.stringify({
        mode: '2pass',
        chunk_size: [5, 10, 5],
        chunk_interval: 10,
        encoder_chunk_look_back: 4,
        decoder_chunk_look_back: 0,
        wav_name: 'mic',
        wav_format: 'pcm',
        audio_fs: 16000,
        is_speaking: true,
        hotwords: '流式对话 流失 修茈 工作台 豆包 MODstore',
        itn: true,
      }),
    )
    this._sessionConfigured = true
    this.flushPreConnectPcm()
  }

  private sendPcmChunk(pcm: Float32Array) {
    if (this.ws?.readyState !== WebSocket.OPEN) return
    const rate = this.capture?.sampleRate ?? 16000
    const resampled = resampleFloat32(pcm, rate, 16000)
    this._audioBuffer.push(resampled)
    this._audioBufferLen += resampled.length
    while (this._audioBufferLen >= this._SEND_CHUNK_SAMPLES) {
      const merged = new Float32Array(this._SEND_CHUNK_SAMPLES)
      let offset = 0
      while (offset < this._SEND_CHUNK_SAMPLES && this._audioBuffer.length > 0) {
        const buf = this._audioBuffer[0]
        const need = this._SEND_CHUNK_SAMPLES - offset
        if (buf.length <= need) {
          merged.set(buf, offset)
          offset += buf.length
          this._audioBuffer.shift()
        } else {
          merged.set(buf.subarray(0, need), offset)
          this._audioBuffer[0] = buf.subarray(need)
          offset += need
        }
      }
      this._audioBufferLen = this._audioBuffer.reduce((sum, b) => sum + b.length, 0)
      const i16 = float32ToInt16(merged)
      this.ws!.send(i16.buffer.slice(i16.byteOffset, i16.byteOffset + i16.byteLength))
      this._pcmChunksSent += 1
    }
  }

  private bestSegmentText(): string {
    return (this._offlineFinal || this._onlinePartial || this._finalText).trim()
  }

  /** 用户停说：立即送尾包 + is_speaking:false，不阻塞等待 offline（由后续 offline 或 finishUtterance 收尾） */
  signalEndOfSpeech(): void {
    if (this._aborted || this._flushing) return
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return
    if (this._pcmChunksSent < 3 && !this.bestSegmentText()) return
    try {
      this.sendRemainingAudio()
      this.ws.send(JSON.stringify({ is_speaking: false }))
    } catch {
      /* ignore */
    }
  }

  async flushUtterance(): Promise<string> {
    const cached = this.bestSegmentText()
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return cached
    // 无音频、无 partial 时不发 is_speaking:false，避免打断 FunASR 会话
    if (this._pcmChunksSent < 3 && !cached) return ''

    this._flushing = true
    const priorOnline = this._onlinePartial
    try {
      this.sendRemainingAudio()
      const segmentText = await this.waitOfflineAfterSpeaking(false)
      try {
        this.ws.send(JSON.stringify({ is_speaking: true }))
      } catch { /* */ }
      const text = (segmentText || this._offlineFinal || priorOnline).trim()
      this._finalText = ''
      this._onlinePartial = ''
      this._offlineFinal = ''
      return text
    } finally {
      this._flushing = false
    }
  }

  async stop(): Promise<string> {
    if (this._ownsCapture) {
      this.capture?.stop()
      this.capture = null
    }
    if (this.ws?.readyState === WebSocket.OPEN && this._pcmChunksSent > 0) {
      this.sendRemainingAudio()
      const text = await this.waitOfflineAfterSpeaking(true)
      this.cleanupWsOnly()
      return text || this._finalText
    }
    const text = this._finalText
    this.cleanupWsOnly()
    return text
  }

  private handleServerMessage(msg: Record<string, unknown>) {
    if (msg.type === 'error') {
      this._onError?.(msg.message as string || 'FunASR 服务错误')
      return
    }
    if (msg.type === 'connected') return
    const text = extractFunAsrText(msg)
    const mode = String(msg.mode || '')
    const isOffline = mode.includes('2pass-offline') || mode === 'offline'
    const isOnline = mode.includes('2pass-online') || mode === 'online'
    // online partial 的 is_final 不能触发客户端整句提交，否则半句就 dispatch
    const isFinal = isOffline
    const segmentMode = isOffline ? 'offline' : isOnline ? 'online' : 'other'
    if (text) {
      if (isOffline) {
        this._offlineFinal = text
        this._finalText = text
      } else {
        this._onlinePartial = text
        if (!this._flushing) this._finalText = text
      }
      this._onResult?.({ text, isFinal, segmentMode })
    }
    if (isOffline || isFinal) {
      const waiter = this._flushWaiter
      if (waiter) {
        this._flushWaiter = null
        waiter(text || this._offlineFinal || this._onlinePartial || this._finalText)
      }
    }
  }

  private sendRemainingAudio() {
    if (this._audioBufferLen <= 0 || this.ws?.readyState !== WebSocket.OPEN) return
    const remaining = new Float32Array(this._audioBufferLen)
    let offset = 0
    for (const buf of this._audioBuffer) {
      remaining.set(buf, offset)
      offset += buf.length
    }
    this._audioBuffer = []
    this._audioBufferLen = 0
    const i16 = float32ToInt16(remaining)
    try {
      this.ws.send(i16.buffer.slice(i16.byteOffset, i16.byteOffset + i16.byteLength))
      if (remaining.length >= this._SEND_CHUNK_SAMPLES) {
        this._pcmChunksSent += Math.floor(remaining.length / this._SEND_CHUNK_SAMPLES)
      }
    } catch { /* */ }
  }

  private waitOfflineAfterSpeaking(fromStop: boolean): Promise<string> {
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        this._flushWaiter = null
        resolve(this.bestSegmentText())
      }, fromStop ? 10000 : 8000)
      this._flushWaiter = (text: string) => {
        clearTimeout(timer)
        resolve((text || this.bestSegmentText()).trim())
      }
      try {
        this.ws?.send(JSON.stringify({ is_speaking: false }))
      } catch {
        clearTimeout(timer)
        this._flushWaiter = null
        resolve(this.bestSegmentText())
      }
    })
  }

  abort(): void {
    this._aborted = true
    this._flushWaiter = null
    this.clearCloseNotifyTimer()
    this.cleanupWsOnly()
  }

  private cleanupWsOnly() {
    this.clearCloseNotifyTimer()
    this._flushWaiter = null
    this._preConnectPcm = []
    this._sessionConfigured = false
    this._audioBuffer = []
    this._audioBufferLen = 0
    if (this._ownsCapture) {
      this.capture?.stop()
    } else if (this._persistentMic) {
      // 保留共享 capture，仅断开回调引用
      this.capture = getSharedMicCapture()
    } else {
      this.capture = null
    }
    if (this._ownsCapture) this.capture = null
    try { this.ws?.close() } catch { /* */ }
    this.ws = null
  }

  private cleanup() {
    this.cleanupWsOnly()
  }

  private buildWsUrl(): string {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const raw = getAccessToken()
    if (!raw) return ''
    return `${proto}://${location.host}/api/asr/funasr?token=${encodeURIComponent(raw)}`
  }
}
