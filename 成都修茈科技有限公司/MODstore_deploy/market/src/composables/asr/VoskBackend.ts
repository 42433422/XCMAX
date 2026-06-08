import type { ASRBackend, ASRResult } from './types'
import { AudioCapture } from './audioCapture'

const BASE = import.meta.env.BASE_URL || '/'

let _voskClient: any = null
let _voskLoading = false
let _voskFailed = false

async function getVoskClient(): Promise<any> {
  if (_voskClient) return _voskClient
  if (_voskLoading) return null
  if (_voskFailed) return null
  _voskLoading = true
  try {
    const { createVoskClient } = await import('@lichess-org/vosk-browser')
    const client = await createVoskClient({
      workerUrl: `${BASE}vosk.worker.js`,
      wasmUrl: `${BASE}vosk.wasm`,
      modelUrl: `${BASE}vosk/model.tar.gz`,
    })
    _voskClient = client
    return client
  } catch (e: any) {
    _voskFailed = true
    throw e
  } finally {
    _voskLoading = false
  }
}

getVoskClient().catch(() => {})

export function invalidateVoskCache() {
  _voskFailed = false
  _voskClient = null
  _voskLoading = false
}

export class VoskBackend implements ASRBackend {
  id = 'vosk' as const
  label = 'Vosk 离线识别'
  private capture: AudioCapture | null = null
  private recognizer: any = null
  private _onResult: ((r: ASRResult) => void) | null = null
  private _onError: ((msg: string) => void) | null = null
  private _finalText = ''
  private _stopped = false

  isAvailable(): boolean {
    if (typeof window === 'undefined') return false
    if (_voskFailed) return false
    return true
  }

  isLoading(): boolean {
    return _voskLoading
  }

  async start(
    onResult: (r: ASRResult) => void,
    onError: (msg: string) => void,
    onAudioLevel?: (level: number) => void,
    onReady?: () => void,
  ): Promise<void> {
    this._onResult = onResult
    this._onError = onError
    this._stopped = false
    this._finalText = ''

    const client = await getVoskClient()
    if (!client) {
      onError('Vosk 模型加载失败，请使用其他识别方案。')
      return
    }
    if (this._stopped) return

    this.recognizer = new client.KaldiRecognizer(16000)
    this.recognizer.on('result', (msg: any) => {
      const text = (msg?.result?.text || '').trim()
      if (text && !this._stopped) {
        this._finalText = text
        onResult({ text, isFinal: true })
      }
    })
    this.recognizer.on('partialresult', (msg: any) => {
      const text = (msg?.result?.partial || '').trim()
      if (text && !this._stopped) {
        onResult({ text, isFinal: false })
      }
    })

    this.capture = new AudioCapture()
    try {
      await this.capture.start({
        onAudioData: (pcm) => {
          if (this.recognizer && !this._stopped) {
            try {
              this.recognizer.acceptWaveformFloat(pcm, 16000)
            } catch { /* */ }
          }
        },
        onAudioLevel: onAudioLevel ?? undefined,
      })
      onReady?.()
    } catch (e: any) {
      onError('麦克风启动失败：' + (e?.message || String(e)))
    }
  }

  async stop(): Promise<string> {
    this._stopped = true
    if (this.recognizer) {
      try {
        const final = this.recognizer.retrieveFinalResult?.()
        if (final?.result?.text) {
          this._finalText = final.result.text.trim()
        }
      } catch { /* */ }
      try { this.recognizer.remove?.() } catch { /* */ }
      this.recognizer = null
    }
    this.capture?.stop()
    this.capture = null
    return this._finalText
  }

  abort(): void {
    this._stopped = true
    try { this.recognizer?.remove?.() } catch { /* */ }
    this.recognizer = null
    this.capture?.stop()
    this.capture = null
  }
}
