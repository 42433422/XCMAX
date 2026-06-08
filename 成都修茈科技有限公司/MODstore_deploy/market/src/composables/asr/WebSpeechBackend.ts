import type { ASRBackend, ASRResult } from './types'
import { AudioCapture } from './audioCapture'

const ERR_MAP: Record<string, string> = {
  network: '语音服务连接失败，正在尝试其他方案…',
  'not-allowed': '麦克风权限被拒绝，请在浏览器设置中允许。',
  'no-speech': '未检测到语音，请再试一次或使用文字输入。',
  'audio-capture': '未找到麦克风，请检查设备。',
  aborted: '语音识别已取消。',
}

function isIosSafari(): boolean {
  if (typeof navigator === 'undefined') return false
  const ua = navigator.userAgent
  return /iPad|iPhone|iPod/.test(ua) || (ua.includes('Mac') && 'ontouchend' in document)
}

export class WebSpeechBackend implements ASRBackend {
  id = 'webspeech' as const
  label = '浏览器语音识别'
  private rec: any = null
  private levelCapture: AudioCapture | null = null
  private _onResult: ((r: ASRResult) => void) | null = null
  private _onError: ((msg: string) => void) | null = null
  private _onAudioLevel: ((level: number) => void) | null = null
  private _finalText = ''
  private _lastInterim = ''
  private _stopped = false
  private _continuous = true
  private _restartTimer: ReturnType<typeof setTimeout> | null = null
  private _restartCount = 0
  private _restartFailures = 0
  private static readonly IOS_RESTART_DELAY_MS = 280
  private static readonly MAX_IOS_RESTARTS = 200
  private static readonly MAX_IOS_RESTART_FAILURES = 8

  isAvailable(): boolean {
    if (typeof window === 'undefined') return false
    const w = window as any
    return !!(w.SpeechRecognition || w.webkitSpeechRecognition)
  }

  isLoading(): boolean {
    return false
  }

  async start(
    onResult: (r: ASRResult) => void,
    onError: (msg: string) => void,
    onAudioLevel?: (level: number) => void,
    onReady?: () => void,
  ): Promise<void> {
    this._onResult = onResult
    this._onError = onError
    this._onAudioLevel = onAudioLevel ?? null
    this._finalText = ''
    this._lastInterim = ''
    this._stopped = false
    this._restartCount = 0
    this._restartFailures = 0
    this.clearRestartTimer()
    const w = window as any
    const Ctor = w.SpeechRecognition || w.webkitSpeechRecognition
    if (!Ctor) {
      onError('当前浏览器不支持语音识别，请使用其他识别方案。')
      return
    }

    // Web Speech API 自行占用麦克风；再开 AudioCapture 会在移动端导致权限冲突
    const rec = new Ctor()
    rec.lang = 'zh-CN'
    rec.interimResults = true
    this._continuous = !isIosSafari()
    rec.continuous = this._continuous
    rec.onresult = (event: any) => {
      if (this._stopped) return
      let text = ''
      for (let i = event.resultIndex; i < event.results.length; i++) {
        text += event.results[i][0]?.transcript || ''
      }
      const trimmed = text.trim()
      if (trimmed) {
        this._lastInterim = trimmed
        this._onAudioLevel?.(0.08)
      }
      const lastSeg = event.results[event.results.length - 1]
      if (lastSeg?.isFinal) {
        this._finalText = trimmed
        onResult({ text: trimmed, isFinal: true })
      } else if (trimmed) {
        onResult({ text: trimmed, isFinal: false })
      }
    }
    rec.onerror = (event: any) => {
      if (this._stopped) return
      const code = event?.error
      if (code === 'no-speech' || code === 'aborted') return
      const msg = code
        ? ERR_MAP[code] || `语音识别失败：${code}`
        : '语音识别失败'
      onError(msg)
    }
    rec.onend = () => {
      if (this._stopped) return
      const text = (this._finalText || this._lastInterim).trim()
      if (text && !this._finalText) {
        this._finalText = text
        onResult({ text, isFinal: true })
      }
      this._onAudioLevel?.(0)
      // iOS Safari 每句结束会停 recognition，需节流重启以保持持续聆听
      if (!this._continuous && this.rec === rec && !this._stopped) {
        this.scheduleIosRestart(rec)
      }
    }
    this.rec = rec
    try {
      // 桌面端：先开音量轨再 start recognition，避免双开麦克风时 level 轨失败导致波形全平
      if (!isIosSafari() && onAudioLevel) {
        try {
          this.levelCapture = new AudioCapture()
          await this.levelCapture.start({
            onAudioData: () => {},
            onAudioLevel: (level) => {
              if (!this._stopped) onAudioLevel(level)
            },
          })
        } catch {
          this.levelCapture = null
        }
      }
      rec.start()
      onReady?.()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      onError(msg)
    }
  }

  private clearRestartTimer() {
    if (this._restartTimer) {
      clearTimeout(this._restartTimer)
      this._restartTimer = null
    }
  }

  private scheduleIosRestart(rec: any) {
    if (this._restartTimer) return
    if (this._restartCount >= WebSpeechBackend.MAX_IOS_RESTARTS) return
    if (this._restartFailures >= WebSpeechBackend.MAX_IOS_RESTART_FAILURES) return
    const backoff = Math.min(this._restartFailures * 120, 1200)
    this._restartTimer = setTimeout(() => {
      this._restartTimer = null
      if (this._stopped || this.rec !== rec) return
      try {
        rec.start()
        this._restartCount += 1
        this._restartFailures = 0
      } catch {
        this._restartFailures += 1
      }
    }, WebSpeechBackend.IOS_RESTART_DELAY_MS + backoff)
  }

  async flushUtterance(): Promise<string> {
    const text = (this._finalText || this._lastInterim).trim()
    if (text && !this._finalText) {
      this._finalText = text
      this._onResult?.({ text, isFinal: true })
    }
    this._finalText = ''
    this._lastInterim = ''
    return text
  }

  async stop(): Promise<string> {
    this._stopped = true
    this.levelCapture?.stop()
    this.levelCapture = null
    try {
      this.rec?.stop?.()
    } catch { /* */ }
    const text = this._finalText || this._lastInterim
    this.rec = null
    this._onAudioLevel = null
    return text
  }

  abort(): void {
    this._stopped = true
    this.clearRestartTimer()
    this.levelCapture?.stop()
    this.levelCapture = null
    try {
      this.rec?.abort?.()
    } catch { /* */ }
    this.rec = null
    this._onAudioLevel = null
  }
}
