import { ref, type Ref } from 'vue'
import { requestStreamBlob, requestStreamResponse, ApiError } from '../infrastructure/http/client'
import { splitSentences, createStreamSplitter, subtractEmittedSegments, type SplitOptions } from '../utils/ttsSentenceSplit'
import { cleanTextForTts } from '../utils/ttsTextClean'

export type TtsState = 'idle' | 'synthesizing' | 'playing'

export interface StreamingTtsConfig {
  engine: 'edge-online' | 'browser'
  edgeVoice: string
  browserVoiceName: string
  rate: number
  /** 单句超过此长度时走 /tts/edge/stream（0 = 始终流式） */
  streamThreshold?: number
  /** 预取队列中后续几句的音频 */
  prefetchDepth?: number
  /** edge 模式下首句用浏览器 TTS 占位，edge 音频就绪后切换 */
  browserLeadIn?: boolean
}

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
  /** edge TTS 429 冷却：此时间戳之前不再请求 edge，改走浏览器 TTS */
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

  private canUseEdge(): boolean {
    if (this.getConfig().engine === 'browser') return false
    return Date.now() >= this.edgeBlockedUntil
  }

  private noteEdgeError(e: unknown) {
    if (e instanceof ApiError && e.status === 429) {
      this.markEdgeRateLimited()
    }
  }

  /** 进入语音模式时预热 TTS 链路（TLS + 鉴权 + edge-tts 连接）。 */
  warmUp(): void {
    const cfg = this.getConfig()
    if (cfg.engine === 'browser') return
    if (this.warmInFlight) return
    if (!this.canUseEdge()) return
    if (Date.now() - this.lastWarmUpAt < 30_000) return
    this.lastWarmUpAt = Date.now()
    const payload = JSON.stringify({
      text: '你好，我在。',
      voice: cfg.edgeVoice || 'zh-CN-XiaoxiaoNeural',
      rate: cfg.rate,
    })
    this.warmInFlight = requestStreamBlob(TTS_STREAM_PATH, { method: 'POST', body: payload })
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
    const cfg = this.getConfig()
    this.enqueuedSentences = []
    if (cfg.engine === 'browser') {
      await this.speakBrowser(cleaned, gen)
      return
    }
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

  private shouldBrowserLeadIn(): boolean {
    const cfg = this.getConfig()
    return (
      cfg.engine === 'edge-online' &&
      cfg.browserLeadIn !== false &&
      this.streamFirstSentencePending &&
      typeof window !== 'undefined' &&
      'speechSynthesis' in window
    )
  }

  private cancelBrowserLeadIn() {
    if (this.leadInCancel) {
      this.leadInCancel()
      this.leadInCancel = null
    } else if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      try {
        window.speechSynthesis.cancel()
      } catch {
        /* ignore */
      }
    }
  }

  private startBrowserLeadIn(sentence: string, gen: number) {
    if (!this.shouldBrowserLeadIn() || gen !== this.generation) return
    this.streamFirstSentencePending = false
    this.cancelBrowserLeadIn()
    const synth = window.speechSynthesis
    const cfg = this.getConfig()
    const u = new SpeechSynthesisUtterance(sentence)
    const voice = this.pickBrowserVoice()
    if (voice) u.voice = voice
    u.lang = 'zh-CN'
    u.rate = Math.max(0.6, Math.min(1.6, cfg.rate))
    this.state.value = 'playing'
    synth.speak(u)
    this.leadInCancel = () => {
      try {
        synth.cancel()
      } catch {
        /* ignore */
      }
      this.leadInCancel = null
    }
  }

  private handoffLeadInToEdge(gen: number) {
    if (gen !== this.generation) return
    this.cancelBrowserLeadIn()
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

  private buildPayload(sentence: string): string {
    const cfg = this.getConfig()
    return JSON.stringify({
      text: sentence,
      voice: cfg.edgeVoice || 'zh-CN-XiaoxiaoNeural',
      rate: cfg.rate,
    })
  }

  private schedulePrefetch(gen: number, fromIndex: number) {
    if (!this.canUseEdge()) return
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

      if (!this.canUseEdge()) {
        this.state.value = 'playing'
        await this.speakBrowserSentence(sentence, gen)
        continue
      }

      this.state.value = 'synthesizing'
      let blobPromise = this.prefetchMap.get(sentence)
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
          const res = await requestStreamResponse(TTS_STREAM_PATH, {
            method: 'POST',
            body: this.buildPayload(sentence),
            signal,
          })
          if (gen !== this.generation) break
          this.state.value = 'playing'
          const ok = await this.playStreamResponse(res, gen)
          if (!ok) {
            await this.speakBrowserSentence(sentence, gen)
          } else {
            this.stopCurrentAudio()
          }
        } catch (e) {
          this.noteEdgeError(e)
          if (gen === this.generation) {
            await this.speakBrowserSentence(sentence, gen)
          }
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
    if (gen !== this.generation || !this.canUseEdge()) return null
    try {
      return await requestStreamBlob(TTS_STREAM_PATH, {
        method: 'POST',
        body: this.buildPayload(sentence),
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
          const buf = value.buffer.slice(value.byteOffset, value.byteOffset + value.byteLength)
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

  private pickBrowserVoice(): SpeechSynthesisVoice | null {
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) return null
    const synth = window.speechSynthesis
    const cfg = this.getConfig()
    const all = synth.getVoices()
    if (cfg.browserVoiceName) {
      const named = all.find((v) => v.name === cfg.browserVoiceName)
      if (named) return named
    }
    return all.find((v) => /^zh/i.test(v.lang)) || all[0] || null
  }

  private async speakBrowser(text: string, gen: number): Promise<void> {
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) return
    const sentences = splitSentences(text)
    for (const sentence of sentences) {
      if (gen !== this.generation) break
      await this.speakBrowserSentence(sentence, gen)
    }
    if (gen === this.generation) this.state.value = 'idle'
  }

  private speakBrowserSentence(sentence: string, gen: number): Promise<void> {
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) return Promise.resolve()
    if (gen !== this.generation) return Promise.resolve()
    const synth = window.speechSynthesis
    const cfg = this.getConfig()
    return new Promise<void>((resolve) => {
      const u = new SpeechSynthesisUtterance(sentence)
      const voice = this.pickBrowserVoice()
      if (voice) u.voice = voice
      u.lang = 'zh-CN'
      u.rate = Math.max(0.6, Math.min(1.6, cfg.rate))
      u.onend = () => resolve()
      u.onerror = () => resolve()
      this.state.value = 'playing'
      synth.speak(u)
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

/** 从个性化设置构建 TTS 配置。 */
export function ttsConfigFromPersonalSettings(ps: {
  ttsEngine: 'edge-online' | 'browser'
  ttsEdgeVoice: string
  ttsVoiceName: string
  ttsRate: number
}): StreamingTtsConfig {
  return {
    engine: ps.ttsEngine,
    edgeVoice: ps.ttsEdgeVoice || 'zh-CN-XiaoxiaoNeural',
    browserVoiceName: ps.ttsVoiceName || '',
    rate: ps.ttsRate,
    streamThreshold: 0,
    prefetchDepth: 1,
    browserLeadIn: false,
  }
}
