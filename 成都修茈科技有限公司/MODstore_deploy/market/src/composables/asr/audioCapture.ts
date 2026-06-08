type AudioCaptureCallbacks = {
  onAudioData: (pcm: Float32Array) => void
  onAudioLevel?: (level: number) => void
}

const BASE = import.meta.env.BASE_URL || '/'

function preferScriptProcessorCapture(): boolean {
  if (typeof navigator === 'undefined') return false
  const ua = navigator.userAgent
  const ios =
    /iPad|iPhone|iPod/.test(ua) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
  const android = /Android/i.test(ua)
  return ios || android
}

function pcmRms(pcm: Float32Array): number {
  if (!pcm.length) return 0
  let sum = 0
  for (let i = 0; i < pcm.length; i++) sum += pcm[i] * pcm[i]
  return Math.sqrt(sum / pcm.length)
}

export class AudioCapture {
  private stream: MediaStream | null = null
  private ownsStream = true
  private ctx: AudioContext | null = null
  private source: MediaStreamAudioSourceNode | null = null
  private workletNode: AudioWorkletNode | null = null
  private processor: ScriptProcessorNode | null = null
  private analyser: AnalyserNode | null = null
  private mute: GainNode | null = null
  private _active = false
  private rafId = 0
  private resumeTimer: ReturnType<typeof setInterval> | null = null
  private _useWorklet = false
  private _sampleRate = 16000
  private _pcmFrames = 0
  private _peakLevel = 0
  private _handlers: AudioCaptureCallbacks | null = null

  get sampleRate() {
    return this._sampleRate
  }

  get active() {
    return this._active
  }

  get pcmFrames() {
    return this._pcmFrames
  }

  get peakLevel() {
    return this._peakLevel
  }

  setHandlers(cb: AudioCaptureCallbacks) {
    this._handlers = cb
    if (cb.onAudioLevel && this._active) {
      this.restartLevelLoop()
    }
  }

  async wake() {
    await this.ensureContextRunning()
  }

  private async ensureContextRunning() {
    if (!this.ctx) return
    if (this.ctx.state === 'suspended') {
      try {
        await this.ctx.resume()
      } catch {
        /* ignore */
      }
    }
  }

  private _smoothLevel = 0
  private _lastLevelEmit = 0

  private emitLevelFromPcm(level: number) {
    this._smoothLevel = this._smoothLevel * 0.6 + level * 0.4
    const now = performance.now()
    if (now - this._lastLevelEmit < 32) return
    this._lastLevelEmit = now
    this._handlers?.onAudioLevel?.(this._smoothLevel)
  }

  async start(cb: AudioCaptureCallbacks, prefetchedStream?: MediaStream): Promise<void> {
    if (this._active) {
      this.setHandlers(cb)
      await this.wake()
      return
    }
    this._handlers = cb
    if (prefetchedStream) {
      this.stream = prefetchedStream
      this.ownsStream = false
    } else {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error('当前浏览器不支持麦克风采集，请使用 HTTPS 访问。')
      }
      try {
        this.stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            channelCount: 1,
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
        })
      } catch {
        this.stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      }
      this.ownsStream = true
    }

    if (!this.stream?.getAudioTracks().some((t) => t.readyState === 'live')) {
      throw new Error('麦克风不可用，请检查权限或是否被其他应用占用。')
    }

    this.ctx = new AudioContext()
    await this.ensureContextRunning()
    this._sampleRate = this.ctx.sampleRate || 16000
    this._pcmFrames = 0
    this._peakLevel = 0
    this.source = this.ctx.createMediaStreamSource(this.stream)
    this.analyser = this.ctx.createAnalyser()
    this.analyser.fftSize = 256
    this.mute = this.ctx.createGain()
    this.mute.gain.value = 0
    this.mute.connect(this.ctx.destination)

    const onPcm = (pcm: Float32Array) => {
      if (!this._active) return
      void this.ensureContextRunning()
      this._pcmFrames += 1
      const rms = pcmRms(pcm)
      const level = Math.min(1, rms * 5)
      if (level > this._peakLevel) this._peakLevel = level
      this.emitLevelFromPcm(level)
      this._handlers?.onAudioData(pcm)
    }

    const attachScriptProcessor = () => {
      const bufLen = 4096
      this.processor = this.ctx!.createScriptProcessor(bufLen, 1, 1)
      this.processor.onaudioprocess = (e) => {
        onPcm(new Float32Array(e.inputBuffer.getChannelData(0)))
      }
      this.source!.connect(this.processor)
      this.processor.connect(this.analyser!)
      this.analyser!.connect(this.mute!)
      this._useWorklet = false
    }

    if (preferScriptProcessorCapture()) {
      attachScriptProcessor()
    } else {
      try {
        await this.ctx.audioWorklet.addModule(`${BASE}vosk/pcm-processor.worklet.js`)
        this.workletNode = new AudioWorkletNode(this.ctx, 'pcm-processor')
        this.workletNode.port.onmessage = (e) => {
          onPcm(e.data as Float32Array)
        }
        this.source.connect(this.workletNode)
        this.workletNode.connect(this.analyser!)
        this.analyser!.connect(this.mute!)
        this._useWorklet = true
      } catch {
        attachScriptProcessor()
      }
    }

    this._active = true
    this.resumeTimer = setInterval(() => {
      void this.ensureContextRunning()
    }, 800)

    if (cb.onAudioLevel) {
      this.restartLevelLoop()
    }

    await new Promise((r) => setTimeout(r, 500))
    await this.ensureContextRunning()
    if (this._pcmFrames < 1) {
      throw new Error('麦克风已打开但未收到音频数据，请检查权限后重试。')
    }
  }

  private restartLevelLoop() {
    if (this.rafId) {
      cancelAnimationFrame(this.rafId)
      this.rafId = 0
    }
    if (!this._handlers?.onAudioLevel || !this._active) return
    const loop = () => {
      if (!this._active) {
        this.rafId = 0
        return
      }
      if (this.analyser) {
        void this.ensureContextRunning()
        const data = new Uint8Array(this.analyser.frequencyBinCount)
        this.analyser.getByteTimeDomainData(data)
        let sum = 0
        for (let i = 0; i < data.length; i++) {
          const v = (data[i] - 128) / 128
          sum += v * v
        }
        const rms = Math.sqrt(sum / data.length)
        const level = Math.min(1, rms * 5)
        if (level > this._peakLevel) this._peakLevel = level
        this.emitLevelFromPcm(level)
      }
      this.rafId = requestAnimationFrame(loop)
    }
    this.rafId = requestAnimationFrame(loop)
  }

  private startLevelLoop() {
    this.restartLevelLoop()
  }

  stop() {
    this._active = false
    if (this.resumeTimer) {
      clearInterval(this.resumeTimer)
      this.resumeTimer = null
    }
    if (this.rafId) {
      cancelAnimationFrame(this.rafId)
      this.rafId = 0
    }
    try { this.workletNode?.disconnect() } catch { /* */ }
    try { this.processor?.disconnect() } catch { /* */ }
    try { this.analyser?.disconnect() } catch { /* */ }
    try { this.mute?.disconnect() } catch { /* */ }
    try { this.source?.disconnect() } catch { /* */ }
    try { this.ctx?.close() } catch { /* */ }
    if (this.ownsStream) {
      try {
        this.stream?.getTracks().forEach((t) => t.stop())
      } catch { /* */ }
    }
    this.workletNode = null
    this.processor = null
    this.source = null
    this.analyser = null
    this.mute = null
    this.ctx = null
    this.stream = null
    this._pcmFrames = 0
    this._peakLevel = 0
    this._smoothLevel = 0
    this._lastLevelEmit = 0
    this._handlers = null
  }
}

export function float32ToInt16(f32: Float32Array): Int16Array {
  const i16 = new Int16Array(f32.length)
  for (let i = 0; i < f32.length; i++) {
    const s = Math.max(-1, Math.min(1, f32[i]))
    i16[i] = s < 0 ? s * 0x8000 : s * 0x7fff
  }
  return i16
}

/** 将 PCM 重采样到目标采样率（FunASR/Vosk 需要 16kHz） */
export function resampleFloat32(
  input: Float32Array,
  fromRate: number,
  toRate = 16000,
): Float32Array {
  if (!input.length || fromRate === toRate) return input
  const ratio = fromRate / toRate
  const outLen = Math.max(1, Math.floor(input.length / ratio))
  const out = new Float32Array(outLen)
  for (let i = 0; i < outLen; i++) {
    const src = i * ratio
    const i0 = Math.floor(src)
    const i1 = Math.min(i0 + 1, input.length - 1)
    const t = src - i0
    out[i] = input[i0] * (1 - t) + input[i1] * t
  }
  return out
}
