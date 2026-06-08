/**
 * S2S TTS 播放：按句合并 MP3 后，用 Web Audio 时间轴无缝排队，避免句间空隙。
 */

import { unlockVoiceAudioPlayback } from './voiceDevice'

type SentenceAccum = {
  chunks: Uint8Array[]
  scheduled: boolean
}

export class S2sMseAudioPlayer {
  private ctx: AudioContext | null = null
  /** 下一段音频应开始的时间（AudioContext 时钟） */
  private scheduleCursor = 0
  private sentences = new Map<string, SentenceAccum>()
  private order: string[] = []
  private activeSources = 0
  private turnOpen = false
  private scheduleChain: Promise<void> = Promise.resolve()
  private generation = 0

  get isPlaying(): boolean {
    return this.activeSources > 0 || this.sentences.size > 0
  }

  private async ensureCtx(): Promise<AudioContext> {
    if (!this.ctx) {
      this.ctx = new AudioContext()
      this.scheduleCursor = this.ctx.currentTime
    }
    if (this.ctx.state === 'suspended') {
      try {
        await this.ctx.resume()
      } catch {
        /* ignore */
      }
    }
    return this.ctx
  }

  reset(): void {
    this.generation += 1
    try {
      this.ctx?.close()
    } catch {
      /* ignore */
    }
    this.ctx = null
    this.scheduleCursor = 0
    this.sentences.clear()
    this.order.length = 0
    this.activeSources = 0
    this.turnOpen = false
    this.scheduleChain = Promise.resolve()
  }

  beginTurn(): void {
    this.turnOpen = true
    const gen = this.generation
    void unlockVoiceAudioPlayback()
    void this.ensureCtx().then((ctx) => {
      if (gen !== this.generation) return
      this.scheduleCursor = Math.max(this.scheduleCursor, ctx.currentTime + 0.02)
    })
  }

  appendChunk(sentenceId: string, data: Uint8Array): void {
    if (!this.turnOpen) this.beginTurn()
    let acc = this.sentences.get(sentenceId)
    if (!acc) {
      acc = { chunks: [], scheduled: false }
      this.sentences.set(sentenceId, acc)
      this.order.push(sentenceId)
    }
    acc.chunks.push(data)
  }

  endSentence(sentenceId: string): void {
    const acc = this.sentences.get(sentenceId)
    if (!acc || acc.scheduled) return
    acc.scheduled = true
    const chunks = acc.chunks
    const gen = this.generation
    this.scheduleChain = this.scheduleChain.then(() => this.scheduleSentence(sentenceId, chunks, gen))
  }

  endTurn(): void {
    this.turnOpen = false
    for (const sid of [...this.order]) {
      const acc = this.sentences.get(sid)
      if (acc && !acc.scheduled && acc.chunks.length) {
        acc.scheduled = true
        const chunks = acc.chunks
        const gen = this.generation
        this.scheduleChain = this.scheduleChain.then(() => this.scheduleSentence(sid, chunks, gen))
      }
    }
  }

  private mergeChunks(chunks: Uint8Array[]): ArrayBuffer {
    const total = chunks.reduce((n, c) => n + c.length, 0)
    const merged = new Uint8Array(total)
    let off = 0
    for (const c of chunks) {
      merged.set(c, off)
      off += c.length
    }
    return merged.buffer.slice(merged.byteOffset, merged.byteOffset + merged.byteLength)
  }

  private chunksToBlobParts(chunks: Uint8Array[]): BlobPart[] {
    return chunks.map((chunk) => {
      const copy = new Uint8Array(chunk.byteLength)
      copy.set(chunk)
      return copy.buffer
    })
  }

  private async scheduleSentence(sentenceId: string, chunks: Uint8Array[], gen: number): Promise<void> {
    if (gen !== this.generation) return
    if (!chunks.length) {
      this.sentences.delete(sentenceId)
      return
    }
    const ctx = await this.ensureCtx()
    if (gen !== this.generation) return
    const ab = this.mergeChunks(chunks)
    try {
      const audioBuffer = await ctx.decodeAudioData(ab.slice(0))
      if (gen !== this.generation) return
      const source = ctx.createBufferSource()
      source.buffer = audioBuffer
      source.connect(ctx.destination)
      const startAt = Math.max(ctx.currentTime + 0.02, this.scheduleCursor)
      source.start(startAt)
      this.scheduleCursor = startAt + audioBuffer.duration
      this.activeSources += 1
      source.onended = () => {
        if (gen !== this.generation) return
        this.activeSources = Math.max(0, this.activeSources - 1)
        this.sentences.delete(sentenceId)
      }
    } catch {
      /* MP3 解码失败时降级：整句 blob + Audio */
      try {
        const blob = new Blob(this.chunksToBlobParts(chunks), { type: 'audio/mpeg' })
        const url = URL.createObjectURL(blob)
        const audio = new Audio(url)
        const startAt = Math.max(0, (this.scheduleCursor - ctx.currentTime) * 1000)
        this.activeSources += 1
        audio.onended = () => {
          URL.revokeObjectURL(url)
          this.activeSources = Math.max(0, this.activeSources - 1)
          this.sentences.delete(sentenceId)
        }
        const playPromise = startAt > 50
          ? new Promise<void>((r) => setTimeout(r, startAt))
          : Promise.resolve()
        await playPromise
        if (gen !== this.generation) {
          URL.revokeObjectURL(url)
          this.activeSources = Math.max(0, this.activeSources - 1)
          this.sentences.delete(sentenceId)
          return
        }
        this.scheduleCursor = ctx.currentTime + (audio.duration || 2)
        await audio.play()
      } catch {
        this.sentences.delete(sentenceId)
      }
    }
  }

  async whenIdle(): Promise<void> {
    while (this.isPlaying) {
      await new Promise((r) => setTimeout(r, 40))
    }
  }
}
