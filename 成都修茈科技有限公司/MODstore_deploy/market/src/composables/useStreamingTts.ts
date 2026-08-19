import { ref, type Ref } from 'vue'
import { requestStreamBlob, requestStreamResponse, ApiError } from '../infrastructure/http/client'
import { splitSentences, createStreamSplitter, subtractEmittedSegments, type SplitOptions } from '../utils/ttsSentenceSplit'
import { cleanTextForTts } from '../utils/ttsTextClean'

export type TtsState = 'idle' | 'synthesizing' | 'playing'

export interface StreamingTtsConfig {
  /** auto/mimo-edge：统一 MiMo→Edge；edge-online：仅 Edge 流；browser 已废弃（映射到 auto） */
  engine: 'auto' | 'mimo-edge' | 'edge-online' | 'browser'
  edgeVoice: string
  browserVoiceName: string
  rate: number
  /** 单句超过此长度时走 /tts/edge/stream（0 = 始终流式） */
  streamThreshold?: number
  /** 预取队列中后续几句的音频 */
  prefetchDepth?: number
  /** 已废弃：不再使用浏览器 TTS 占位 */
  browserLeadIn?: boolean
}

/** 统一 TTS：服务端 MiMo → Edge */
const TTS_UNIFIED_PATH = '/api/workbench/tts'
const TTS_STREAM_PATH = '/api/workbench/tts/edge/stream'
const MSE_MIME = 'audio/mpeg'

export class StreamingTtsPlayer {
  readonly state: Ref<TtsState> = ref('idle')

  private queue: string[] = []
  private splitter = createStreamSplitter()
  private feedOpts: SplitOptions | undefined
  private streamSoFar = ''
  private enqueuedSentences: string[] = []
  private generation = 0
  private running = false
  private abortController: AbortController | null = null
  private currentAudio: HTMLAudioElement | null = null
  private objectUrls: string[] = []
  private prefetchMap = new Map<string, Promise<Blob | null>>()
  private warmInFlight: Promise<void> | null = null
  private streamFirstSentencePending = true
  private leadInCancel: (() => void) | null = null
  /** edge TTS 429 冷却：此时间戳之前暂缓 edge 流，仍可走统一 /tts（MiMo） */
  private edgeBlockedUntil = 0
  private lastWarmUpAt = 0

  constructor(private getConfig: () => StreamingTtsConfig) {}

  private markEdgeRateLimited(retryAfterSec?: number) {
    const backoffMs =
      typeof retryAfterSec === 'number' && retryAfterSec > 0
        ? retryAfterSec * 1000
        : 60_000
    this.edgeBlockedUntil = Date.now() + backoffMs
  }

  private preferUnified(): boolean {
    const eng = this.getConfig().engine
    return eng !== 'edge-online'
  }

  private canUseEdge(): boolean {
    return Date.now() >= this.edgeBlockedUntil
  }

  private noteEdgeError(e: unknown) {
    if (e instanceof ApiError && e.status === 429) {
      this.markEdgeRateLimited()
    }
  }

  /** 进入语音模式时预热 TTS 链路（统一 /tts：MiMo→Edge）。 */
  warmUp(): void {
    if (this.warmInFlight) return
    if (Date.now() - this.lastWarmUpAt < 30_000) return
    this.lastWarmUpAt = Date.now()
    const cfg = this.getConfig()
    const payload = JSON.stringify(
      this.preferUnified()
        ? {
            text: '你好，我在。',
            edge_voice: cfg.edgeVoice || 'zh-CN-XiaoxiaoNeural',
            rate: cfg.rate,
          }
        : {
            text: '你好，我在。',
            voice: cfg.edgeVoice || 'zh-CN-XiaoxiaoNeural',
            rate: cfg.rate,
          },
    )
    const path = this.preferUnified() ? TTS_UNIFIED_PATH : TTS_STREAM_PATH
    this.warmInFlight = requestStreamBlob(path, { method: 'POST', body: payload })
      .then(() => {})
      .catch((e) => { this.noteEdgeError(e) })
      .finally(() => {
        this.warmInFlight = null
      })
  }

  async speak(text: string): Promise<void> {
    this.stop()
    const cleaned = cleanTextForTts(text)
    if (!cleaned) return
    const gen = ++this.generation
    this.enqueuedSentences = []
    this.queue = splitSentences(cleaned)
    this.streamFirstSentencePending = true
    this.schedulePrefetch(gen, 0)
    await this.runQueue(gen)
  }

  feed(soFar: string) {
    const cleaned = cleanTextForTts(soFar)
    if (!cleaned) return
    this.streamSoFar = cleaned
    const newSentences = this.splitter.feed(cleaned)
    for (const s of newSentences) this.enqueue(s)
  }

  finish(soFar?: string) {
    const text = cleanTextForTts(soFar ?? this.streamSoFar)
    const remaining = this.splitter.finish(text)
    for (const s of remaining) this.enqueue(s)
    this.streamSoFar = ''
    this.splitter.reset()
  }

  resetStream(feedOpts?: SplitOptions) {
    this.feedOpts = feedOpts
    this.splitter = createStreamSplitter(feedOpts)
    this.streamSoFar = ''
    this.enqueuedSentences = []
    this.streamFirstSentencePending = true
    this.resetEdgeBackoff()
  }

  stop() {
    this.generation += 1
    this.queue = []
    this.prefetchMap.clear()
    this.enqueuedSentences = []
    this.running = false
    this.cancelBrowserLeadIn()
    if (this.abortController) {
      this.abortController.abort()
      this.abortController = null
    }
    this.stopCurrentAudio()
    this.revokeUrls()
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel()
    }
    this.streamFirstSentencePending = true
    this.state.value = 'idle'
  }

  private resetEdgeBackoff() {
    this.edgeBlockedUntil = 0
  }

  private cancelBrowserLeadIn() {
    if (this.leadInCancel) {
      this.leadInCancel()
      this.leadInCancel = null
    }
  }

  private enqueue(sentence: string) {
    const s = sentence.trim()
    if (!s) return
    const fresh = subtractEmittedSegments([s], this.enqueuedSentences)
    if (!fresh.length) return
    this.enqueuedSentences.push(...fresh)
    for (const part of fresh) {
      this.queue.push(part)
    }
    if (!this.running) void this.runQueue(this.generation)
  }

  /** LLM 流结束后等待队列播完；用于恢复麦克风前同步。 */
  whenIdle(timeoutMs = 120_000): Promise<void> {
    if (this.state.value === 'idle' && !this.running && this.queue.length === 0) {
      return Promise.resolve()
    }
    return new Promise((resolve) => {
      const started = Date.now()
      const tick = () => {
        if (this.state.value === 'idle' && !this.running && this.queue.length === 0) {
          resolve()
          return
        }
        if (Date.now() - started >= timeoutMs) {
          resolve()
          return
        }
        setTimeout(tick, 40)
      }
      tick()
    })
  }

  private buildUnifiedPayload(sentence: string): string {
    const cfg = this.getConfig()
    return JSON.stringify({
      text: sentence,
      edge_voice: cfg.edgeVoice || 'zh-CN-XiaoxiaoNeural',
      rate: cfg.rate,
    })
  }

  private buildEdgePayload(sentence: string): string {
    const cfg = this.getConfig()
    return JSON.stringify({
      text: sentence,
      voice: cfg.edgeVoice || 'zh-CN-XiaoxiaoNeural',
      rate: cfg.rate,
    })
  }

  private schedulePrefetch(gen: number, fromIndex: number) {
    const cfg = this.getConfig()
    const depth = Math.max(1, cfg.prefetchDepth ?? 1)
    const signal = this.abortController?.signal
    if (!signal) return
    let scheduled = 0
    for (let i = fromIndex; i < this.queue.length && scheduled < depth; i++) {
      const sentence = this.queue[i]
      if (!sentence || this.prefetchMap.has(sentence)) continue
      this.prefetchMap.set(sentence, this.prefetchBlob(sentence, signal, gen))
      scheduled += 1
    }
  }

  private async runQueue(gen: number) {
    if (this.running) return
    this.running = true
    this.abortController = new AbortController()
    const signal = this.abortController.signal

    while (this.queue.length > 0 && gen === this.generation) {
      const sentence = this.queue.shift()!
      this.schedulePrefetch(gen, 0)

      this.state.value = 'synthesizing'
      const blobPromise = this.prefetchMap.get(sentence)
      if (blobPromise) {
        this.prefetchMap.delete(sentence)
      }

      let played = false
      if (blobPromise) {
        let blob: Blob | null = null
        try {
          blob = await blobPromise
        } catch {
          blob = null
        }
        if (gen !== this.generation) break
        if (blob && blob.size > 0) {
          this.state.value = 'playing'
          await this.playBlob(blob, gen)
          played = true
        }
      }

      if (!played && gen === this.generation) {
        try {
          if (this.preferUnified()) {
            const blob = await requestStreamBlob(TTS_UNIFIED_PATH, {
              method: 'POST',
              body: this.buildUnifiedPayload(sentence),
              signal,
            })
            if (gen !== this.generation) break
            if (blob && blob.size > 0) {
              this.state.value = 'playing'
              await this.playBlob(blob, gen)
              played = true
            }
          }
          if (!played && this.canUseEdge()) {
            const res = await requestStreamResponse(TTS_STREAM_PATH, {
              method: 'POST',
              body: this.buildEdgePayload(sentence),
              signal,
            })
            if (gen !== this.generation) break
            this.state.value = 'playing'
            played = await this.playStreamResponse(res, gen)
            if (played) this.stopCurrentAudio()
          }
        } catch (e) {
          this.noteEdgeError(e)
          // 不回退系统 TTS：跳过本句
        }
      }
    }

    this.running = false
    this.abortController = null
    if (gen === this.generation) this.state.value = 'idle'
  }

  private async prefetchBlob(
    sentence: string,
    signal: AbortSignal,
    gen: number,
  ): Promise<Blob | null> {
    if (gen !== this.generation) return null
    try {
      if (this.preferUnified()) {
        return await requestStreamBlob(TTS_UNIFIED_PATH, {
          method: 'POST',
          body: this.buildUnifiedPayload(sentence),
          signal,
        })
      }
      if (!this.canUseEdge()) return null
      return await requestStreamBlob(TTS_STREAM_PATH, {
        method: 'POST',
        body: this.buildEdgePayload(sentence),
        signal,
      })
    } catch (e: unknown) {
      if (e instanceof DOMException && e.name === 'AbortError') return null
      this.noteEdgeError(e)
      return null
    }
  }

  private canUseMse(): boolean {
    return (
      typeof window !== 'undefined' &&
      typeof MediaSource !== 'undefined' &&
      MediaSource.isTypeSupported(MSE_MIME)
    )
  }

  /** MSE 边下边播；失败时读完整流后 playBlob。 */
  private async playStreamResponse(res: Response, gen: number): Promise<boolean> {
    const body = res.body
    if (!body) return false
    if (this.canUseMse()) {
      try {
        await this.playMseStream(body, gen)
        return true
      } catch {
        /* fall through to full-buffer play */
      }
    }

    const reader = body.getReader()
    const chunks: BlobPart[] = []
    try {
      while (true) {
        const { done, value } = await reader.read()
        if (gen !== this.generation) return true
        if (done) break
        if (value?.byteLength) chunks.push(value)
      }
    } finally {
      reader.releaseLock()
    }
    if (gen !== this.generation || !chunks.length) return false
    await this.playBlob(new Blob(chunks, { type: MSE_MIME }), gen)
    return true
  }

  private playMseStream(body: ReadableStream<Uint8Array>, gen: number): Promise<void> {
    return new Promise((resolve, reject) => {
      const ms = new MediaSource()
      const url = URL.createObjectURL(ms)
      this.objectUrls.push(url)
      const audio = new Audio()
      audio.preload = 'auto'
      this.currentAudio = audio
      audio.src = url

      ms.addEventListener(
        'sourceopen',
        () => {
          void this.pumpMse(body, ms, audio, gen)
            .then(() => {
              if (gen !== this.generation) {
                resolve()
                return
              }
              if (audio.ended) {
                resolve()
                return
              }
              audio.addEventListener('ended', () => resolve(), { once: true })
              audio.addEventListener('error', () => resolve(), { once: true })
            })
            .catch(reject)
        },
        { once: true },
      )
    })
  }

  private async pumpMse(
    body: ReadableStream<Uint8Array>,
    ms: MediaSource,
    audio: HTMLAudioElement,
    gen: number,
  ): Promise<void> {
    const reader = body.getReader()
    const sb = ms.addSourceBuffer(MSE_MIME)
    sb.mode = 'sequence'
    let started = false

    const append = (buf: ArrayBuffer): Promise<void> =>
      new Promise((resolve, reject) => {
        const onEnd = () => {
          sb.removeEventListener('updateend', onEnd)
          sb.removeEventListener('error', onErr)
          resolve()
        }
        const onErr = () => {
          sb.removeEventListener('updateend', onEnd)
          sb.removeEventListener('error', onErr)
          reject(new Error('SourceBuffer error'))
        }
        sb.addEventListener('updateend', onEnd, { once: true })
        sb.addEventListener('error', onErr, { once: true })
        try {
          sb.appendBuffer(buf)
        } catch (e) {
          reject(e)
        }
      })

    try {
      while (true) {
        if (gen !== this.generation) {
          await reader.cancel()
          return
        }
        const { done, value } = await reader.read()
        if (value?.byteLength) {
          const copy = new Uint8Array(value.byteLength)
          copy.set(new Uint8Array(value.buffer, value.byteOffset, value.byteLength))
          const buf = copy.buffer
          await append(buf)
          if (!started && sb.buffered.length > 0) {
            started = true
            void audio.play().catch(() => {})
          }
        }
        if (done) {
          if (ms.readyState === 'open') {
            try {
              ms.endOfStream()
            } catch {
              /* ignore */
            }
          }
          break
        }
      }
    } finally {
      reader.releaseLock()
    }
  }

  private stopCurrentAudio() {
    if (!this.currentAudio) return
    try {
      this.currentAudio.pause()
      this.currentAudio.removeAttribute('src')
      this.currentAudio.load()
    } catch {
      /* ignore */
    }
    this.currentAudio = null
  }

  private revokeUrls() {
    for (const url of this.objectUrls) {
      try {
        URL.revokeObjectURL(url)
      } catch {
        /* ignore */
      }
    }
    this.objectUrls = []
  }

  private async playBlob(blob: Blob, gen: number): Promise<void> {
    if (gen !== this.generation) return
    const url = URL.createObjectURL(blob)
    this.objectUrls.push(url)
    const audio = new Audio(url)
    this.currentAudio = audio
    await new Promise<void>((resolve) => {
      const done = () => {
        this.stopCurrentAudio()
        resolve()
      }
      audio.addEventListener('ended', done, { once: true })
      audio.addEventListener('error', done, { once: true })
      void audio.play().catch(done)
    })
  }

}

export function useStreamingTts(getConfig: () => StreamingTtsConfig) {
  const player = new StreamingTtsPlayer(getConfig)
  return {
    state: player.state,
    speak: (text: string) => player.speak(text),
    feed: (soFar: string) => player.feed(soFar),
    finish: (soFar?: string) => player.finish(soFar),
    resetStream: (feedOpts?: SplitOptions) => player.resetStream(feedOpts),
    warmUp: () => player.warmUp(),
    whenIdle: (timeoutMs?: number) => player.whenIdle(timeoutMs),
    stop: () => player.stop(),
  }
}

/** 从个性化设置构建 TTS 配置。历史 browser 选项映射为 auto（MiMo→Edge）。 */
export function ttsConfigFromPersonalSettings(ps: {
  ttsEngine: 'edge-online' | 'browser' | 'auto' | 'mimo-edge'
  ttsEdgeVoice: string
  ttsVoiceName: string
  ttsRate: number
}): StreamingTtsConfig {
  const raw = ps.ttsEngine
  const engine: StreamingTtsConfig['engine'] =
    raw === 'edge-online' ? 'edge-online' : 'auto'
  return {
    engine,
    edgeVoice: ps.ttsEdgeVoice || 'zh-CN-XiaoxiaoNeural',
    browserVoiceName: '',
    rate: ps.ttsRate,
    streamThreshold: 0,
    prefetchDepth: 1,
    browserLeadIn: false,
  }
}
