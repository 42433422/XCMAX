import type { ASRBackend, ASRResult } from './types'
import { AudioCapture, resampleFloat32 } from './audioCapture'

type WorkerMsg =
  | { type: 'ready' }
  | { type: 'progress'; data: unknown }
  | { type: 'result'; jobId?: number; data: string }
  | { type: 'error'; jobId?: number; data: string }

const MODEL_READY_TIMEOUT_MS = 18000

export class WhisperWebBackend implements ASRBackend {
  id = 'whisper-web' as const
  label = '本地 Whisper 识别'
  private worker: Worker | null = null
  private capture: AudioCapture | null = null
  private _loading = true
  private _ready = false
  private _onResult: ((r: ASRResult) => void) | null = null
  private _onError: ((msg: string) => void) | null = null
  private audioBuffer: Float32Array[] = []
  private chunkTimer: ReturnType<typeof setInterval> | null = null
  private _lastText = ''
  private _stopped = false
  private _initError = ''
  /** 推理任务序号：flush 会 bump 以作废进行中的 chunk 推理 */
  private _jobSeq = 0
  private _activeJobId = 0

  isAvailable(): boolean {
    return typeof window !== 'undefined' && typeof Worker !== 'undefined'
  }

  isLoading(): boolean {
    return this._loading && !this._ready
  }

  private nextJobId(): number {
    this._jobSeq += 1
    this._activeJobId = this._jobSeq
    return this._activeJobId
  }

  private invalidatePendingJobs(): void {
    this._jobSeq += 1
    this._activeJobId = this._jobSeq
  }

  private ensureWorker(): Worker {
    if (this.worker) return this.worker
    this.worker = new Worker(
      new URL('../../workers/whisper-asr-worker.ts', import.meta.url),
      { type: 'module' },
    )
    this.worker.onmessage = (e: MessageEvent<WorkerMsg>) => {
      const msg = e.data
      if (msg.type === 'ready') {
        this._loading = false
        this._ready = true
      } else if (msg.type === 'progress') {
        // could emit progress
      } else if (msg.type === 'result') {
        if (msg.jobId != null && msg.jobId !== this._activeJobId) return
        const text = (msg.data || '').trim()
        if (text && !this._stopped) {
          this._lastText = text
          this._onResult?.({ text, isFinal: false })
        }
      } else if (msg.type === 'error') {
        this._loading = false
        this._initError = msg.data || 'Whisper 识别失败'
        if (msg.jobId != null && msg.jobId !== this._activeJobId) return
        if (msg.jobId != null) return
        if (this._ready && this._onError) {
          this._onError(this._initError)
        }
      }
    }
    this.worker.onerror = (e) => {
      this._loading = false
      this._initError = `Whisper Worker 错误：${e.message || '未知'}`
      if (this._onError) {
        this._onError(this._initError)
      }
    }
    this.worker.postMessage({ type: 'init' })
    return this.worker
  }

  private waitForModelReady(timeoutMs: number): Promise<boolean> {
    if (this._ready) return Promise.resolve(true)
    const worker = this.worker
    if (!worker) return Promise.resolve(false)

    return new Promise((resolve) => {
      let settled = false
      const finish = (ok: boolean) => {
        if (settled) return
        settled = true
        clearTimeout(timer)
        worker.removeEventListener('message', onMsg)
        worker.removeEventListener('error', onWorkerError)
        resolve(ok)
      }

      const timer = setTimeout(() => finish(false), timeoutMs)

      const onMsg = (e: MessageEvent<WorkerMsg>) => {
        if (e.data.type === 'ready') {
          this._loading = false
          this._ready = true
          finish(true)
        } else if (e.data.type === 'error' && e.data.jobId == null) {
          this._initError = e.data.data || this._initError || 'Whisper 模型加载失败'
          finish(false)
        }
      }

      const onWorkerError = () => {
        this._initError = this._initError || 'Whisper Worker 启动失败'
        finish(false)
      }

      worker.addEventListener('message', onMsg)
      worker.addEventListener('error', onWorkerError)
    })
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
    this._lastText = ''
    this._initError = ''
    this.audioBuffer = []
    this.ensureWorker()

    const modelReady = await this.waitForModelReady(MODEL_READY_TIMEOUT_MS)
    if (!modelReady) {
      onError(this._initError || 'Whisper 模型加载失败')
      return
    }

    this.capture = new AudioCapture()
    try {
      await this.capture.start({
        onAudioData: (pcm) => {
          const rate = this.capture?.sampleRate ?? 16000
          this.audioBuffer.push(resampleFloat32(pcm, rate, 16000))
        },
        onAudioLevel: onAudioLevel ?? undefined,
      })
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      onError('麦克风启动失败：' + msg)
      return
    }
    this.chunkTimer = setInterval(() => {
      this.processChunk()
    }, 3000)
    onReady?.()
  }

  private processChunk() {
    if (!this.audioBuffer.length || !this._ready || this._stopped) return
    const merged = this.mergeBuffers()
    this.audioBuffer = []
    if (merged.length < 1600) return
    const jobId = this.nextJobId()
    this.worker?.postMessage({
      type: 'transcribe',
      jobId,
      data: { audio: merged },
    })
  }

  private mergeBuffers(): Float32Array {
    let len = 0
    for (const b of this.audioBuffer) len += b.length
    const out = new Float32Array(len)
    let offset = 0
    for (const b of this.audioBuffer) {
      out.set(b, offset)
      offset += b.length
    }
    return out
  }

  private transcribeBuffer(merged: Float32Array, jobId: number): Promise<string> {
    return new Promise<string>((resolve) => {
      const handler = (e: MessageEvent<WorkerMsg>) => {
        if (e.data.jobId != null && e.data.jobId !== jobId) return
        if (e.data.type === 'result') {
          this.worker?.removeEventListener('message', handler)
          resolve((e.data.data || '').trim())
        } else if (e.data.type === 'error') {
          this.worker?.removeEventListener('message', handler)
          resolve('')
        }
      }
      this.worker?.addEventListener('message', handler)
      this.worker?.postMessage({
        type: 'transcribe',
        jobId,
        data: { audio: merged },
      })
      setTimeout(() => {
        this.worker?.removeEventListener('message', handler)
        resolve('')
      }, 10000)
    })
  }

  async flushUtterance(): Promise<string> {
    if (this.chunkTimer) {
      clearInterval(this.chunkTimer)
      this.chunkTimer = null
    }
    this.invalidatePendingJobs()
    let text = this._lastText.trim()
    if (this.audioBuffer.length > 0 && this._ready) {
      const merged = this.mergeBuffers()
      this.audioBuffer = []
      if (merged.length >= 1600) {
        const flushJobId = this.nextJobId()
        const flushed = (await this.transcribeBuffer(merged, flushJobId)).trim()
        if (flushed) text = flushed
      }
    }
    if (text) {
      this._lastText = text
      this._onResult?.({ text, isFinal: true })
    }
    this._lastText = ''
    if (!this._stopped && this._ready) {
      this.chunkTimer = setInterval(() => {
        this.processChunk()
      }, 3000)
    }
    return text
  }

  async stop(): Promise<string> {
    this._stopped = true
    this.invalidatePendingJobs()
    if (this.chunkTimer) {
      clearInterval(this.chunkTimer)
      this.chunkTimer = null
    }
    if (this.audioBuffer.length > 0 && this._ready) {
      const merged = this.mergeBuffers()
      this.audioBuffer = []
      if (merged.length >= 1600) {
        const stopJobId = this.nextJobId()
        const text = await this.transcribeBuffer(merged, stopJobId)
        const finalText = text.trim() || this._lastText
        this._onResult?.({ text: finalText, isFinal: true })
        this.capture?.stop()
        this.capture = null
        return finalText
      }
    }
    if (this._lastText) {
      this._onResult?.({ text: this._lastText, isFinal: true })
    }
    this.capture?.stop()
    this.capture = null
    return this._lastText
  }

  abort(): void {
    this._stopped = true
    this.invalidatePendingJobs()
    if (this.chunkTimer) {
      clearInterval(this.chunkTimer)
      this.chunkTimer = null
    }
    this.capture?.stop()
    this.capture = null
    this.audioBuffer = []
    this._onResult = null
    this._onError = null
    this.worker?.terminate()
    this.worker = null
    this._ready = false
    this._loading = true
  }
}
