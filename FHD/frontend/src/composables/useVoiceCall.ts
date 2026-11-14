/**
 * 桌面端 AI 语音通话（半双工轮次）：聆听 → 转写 → 对话 → 朗读 → 继续聆听。
 *
 * 与手机端 voice_call_screen 行为对齐：自动断句、静音/免提/挂断、
 * 实时字幕与通话计时。语音识别复用现有 /api/voice/transcribe，
 * 对话复用当前会话的 sendMessage，朗读复用统一 TTS 入口。
 */
import { computed, getCurrentScope, onScopeDispose, ref, type Ref } from 'vue'
import { apiFetch, apiUrl } from '@/utils/apiBase'
import {
  speakText,
  stopSpeaking,
  createChineseUtterance,
  pauseSpeaking,
  resumeSpeaking,
} from '@/utils/tts'
import { plainTextFromChatHtml } from '@/utils/sanitizeHtml'
import {
  hasTranscriptContent,
  isDuplicateTranscript,
  isLowInformationTranscript,
  normalizeVoiceTranscript,
  type TranscriptMemory,
} from '@/utils/voiceTranscript'
import {
  getVoiceSupport,
  recordVoiceCount,
  recordVoiceEvent,
  recordVoiceTiming,
} from '@/utils/voiceDiagnostics'
import { effectivePendingMaxMs, effectiveTurnThreshold } from './voiceTurnSettings'
import type { ChatMessage } from './useChatMessages'

export type VoiceCallStage =
  | 'connecting'
  | 'listening'
  | 'recognizing'
  | 'thinking'
  | 'speaking'
  | 'muted'
  | 'ended'

interface UseVoiceCallDeps {
  sendMessage: (message: string) => Promise<void>
  messages: Ref<ChatMessage[]>
  title?: Ref<string> | string
  /** 语音轮失败后回读服务端会话，避免把「已成功但前端没收到」误报成失败。 */
  refreshMessages?: () => Promise<void>
}

const SILENCE_MS = 800
/** 朗读结束后留一点余量，避免扬声器尾音被麦克风当成新一轮开口。 */
const SPEAK_TAIL_MS = 250
const FAILURE_NOTICE = /请求超时|尚未收到完成回执|连接中断|未标记为成功|请核对原任务|服务暂不可用|处理失败|network error|Network Error|服务暂时不可用/
const SPOKEN_RETRY_HINT = '网络有点慢，我没收到回复，请再说一次。'
/** 思考超过这个时长才补一句口头确认，回复快的时候不打扰。 */
const ACK_DELAY_MS = 1_200
const ACK_LINE = '嗯，我看看。'
const MAX_UTTERANCE_MS = 30_000
const MIN_UTTERANCE_MS = 700
/** 连续有声帧数达到该值才认为真的开口，避免环境噪声单帧触发一轮对话。 */
const VOICED_FRAMES_TO_START = 3
const CALIBRATION_MS = 500
const TRANSCRIPTION_TIMEOUT_MS = 90_000
const MIME_CANDIDATES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value))
}

/** ASR 偶发把语种标签当正文输出（<chinese> 等），由 voiceTranscript 统一清洗。 */

/** 纯语气词/附和词：只挂起等待后续，不单独发起一轮对话。 */
const FILLER_ONLY_RE =
  /^(?:(?:嗯|啊|哦|呃|额|唉|诶|好|行|是|对|喂|收到|明白|知道|哈哈|呵呵|ok|okay)[。.!！?？…，,\s]*)+$/i
/** 句尾是连接词/未完成结构：大概率还没说完，先等用户继续。 */
const INCOMPLETE_TAIL_RE =
  /(?:就是|然后|那个|这个|我想|我要|因为|所以|但是|而且|还有|以及|帮我|给你|跟|和|的|地|得)[。.!！?？…，,\s]*$/
/** 有明确目的的信号（提问、动作、查询等）。 */
const INTENT_HINT_RE =
  /[?？]|帮我|给我|请|麻烦|查|找|搜索|提交|创建|新建|打开|生成|导出|删除|修改|添加|设置|查看|统计|计算|多少|什么|怎么|为什么|哪里|哪个|能不能|可不可以|想|需要|要/
/** 插话持续超过该时长即视为真打断，不再等 ASR 分类。 */
const BARGE_CONFIRM_MS = 1_200
const STREAM_READY_TIMEOUT_MS = 1_500
const STREAM_FINAL_TIMEOUT_MS = 1_800
const TURN_UNKNOWN_LINE = '这次我已经提交了，正在核对执行结果，请先不要重复操作。'
/** 同一句转写在该窗口内重复出现视为回声/抖动，直接丢弃。 */
const DUPLICATE_TRANSCRIPT_MS = 3_000

function compactText(text: string): string {
  return text.replace(/[。．.!！?？，,、；;：:…~（）()\s]/g, '')
}

function isFillerOnly(text: string): boolean {
  return FILLER_ONLY_RE.test(text.trim())
}

function looksIncomplete(text: string): boolean {
  return INCOMPLETE_TAIL_RE.test(text.trim())
}

function hasIntent(text: string): boolean {
  return INTENT_HINT_RE.test(text)
}

/** Float32 → 16-bit PCM 单声道 WAV（Smart Turn / ASR 的输入格式）。 */
function encodeWav(samples: Float32Array, sampleRate = 16000): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2)
  const view = new DataView(buffer)
  const write = (offset: number, text: string) => {
    for (let i = 0; i < text.length; i += 1) view.setUint8(offset + i, text.charCodeAt(i))
  }
  write(0, 'RIFF')
  view.setUint32(4, 36 + samples.length * 2, true)
  write(8, 'WAVEfmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  write(36, 'data')
  view.setUint32(40, samples.length * 2, true)
  for (let i = 0; i < samples.length; i += 1) {
    const s = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true)
  }
  return new Blob([buffer], { type: 'audio/wav' })
}

/** 把 MediaRecorder 的压缩录音解码成 16 kHz WAV，供本地判停模型使用。 */
async function blobToWav16k(blob: Blob): Promise<Blob | null> {
  const ctx = new AudioContext()
  try {
    const decoded = await ctx.decodeAudioData(await blob.arrayBuffer())
    const targetRate = 16000
    const frames = Math.max(1, Math.ceil(decoded.duration * targetRate))
    const offline = new OfflineAudioContext(1, frames, targetRate)
    const source = offline.createBufferSource()
    source.buffer = decoded
    source.connect(offline.destination)
    source.start()
    const rendered = await offline.startRendering()
    return encodeWav(rendered.getChannelData(0), targetRate)
  } catch {
    return null
  } finally {
    void ctx.close()
  }
}

/** 复刻 Pipecat Smart Turn：本地判断这段语音是否已经说完。失败时按“已说完”继续。 */
async function requestTurnComplete(wav: Blob, threshold: number): Promise<boolean> {
  try {
    const form = new FormData()
    form.append('file', wav, 'turn.wav')
    form.append('threshold', String(threshold))
    const response = await apiFetch('/api/voice/turn-detect', { method: 'POST', body: form })
    if (!response.ok) return true
    const payload = (await response.json()) as { data?: { complete?: boolean } }
    return payload?.data?.complete !== false
  } catch {
    return true
  }
}

function floatToPcm16(samples: Float32Array): ArrayBuffer {
  const buffer = new ArrayBuffer(samples.length * 2)
  const view = new DataView(buffer)
  for (let i = 0; i < samples.length; i += 1) {
    const s = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true)
  }
  return buffer
}

/** 任意采样率 → 16 kHz PCM16（平台 FunASR 流式输入格式）。 */
function downsampleToPcm16(samples: Float32Array, sampleRate: number): ArrayBuffer {
  const targetRate = 16000
  if (!sampleRate || sampleRate === targetRate) return floatToPcm16(samples)
  const ratio = sampleRate / targetRate
  const length = Math.max(1, Math.floor(samples.length / ratio))
  const out = new Float32Array(length)
  for (let i = 0; i < length; i += 1) {
    const pos = i * ratio
    const index = Math.floor(pos)
    const fraction = pos - index
    const a = samples[index] ?? 0
    const b = samples[index + 1] ?? a
    out[i] = a + (b - a) * fraction
  }
  return floatToPcm16(out)
}

export function useVoiceCall({ sendMessage, messages, title = '通用助手', refreshMessages }: UseVoiceCallDeps) {
  const open = ref(false)
  const stage = ref<VoiceCallStage>('connecting')
  const seconds = ref(0)
  const heardText = ref('')
  /** 流式识别的中间结果：只做字幕预览，不进入对话。 */
  const partialText = ref('')
  const replyText = ref('')
  const errorText = ref('')
  /** 非致命降级提示（流式识别不可用、朗读失败等）。 */
  const noticeText = ref('')
  const muted = ref(false)
  const speakerOn = ref(true)
  const speechPaused = ref(false)

  let stream: MediaStream | null = null
  let recorder: MediaRecorder | null = null
  let audioCtx: AudioContext | null = null
  let analyser: AnalyserNode | null = null
  let monitorTimer: number | undefined
  let tickTimer: number | undefined
  let chunks: Blob[] = []
  let cycleToken = 0
  let handlingTurn = false
  let speechStartedAt = 0
  let lastVoiceAt = 0
  let calibratedUntil = 0
  let noiseFloor = 0.012
  let threshold = 0.03
  let voicedRun = 0
  let stopping = false

  /** 插话打断：TTS 播放期间用 Silero VAD（@ricky0123/vad-web）识别用户开口。 */
  interface BargeInVad {
    listening: boolean
    start: () => Promise<void>
    pause: () => Promise<void>
    destroy: () => Promise<void>
  }
  let bargeVad: BargeInVad | null = null
  let bargeArmed = false
  let bargeLoading: Promise<BargeInVad | null> | null = null
  let bargeArmedAt = 0
  /** 插话候选：先用 ASR 文本判断是附和还是真打断，再决定是否停止朗读。 */
  let bargeCandidate = false
  let bargeForceTimer: number | undefined
  /** 用户插话时，这段语音直接由 VAD 音频转写，避免“打断的那句话”丢失。 */
  let bargeUtteranceActive = false
  /** 判停等待：语气词或明显没说完的内容先挂起，等用户继续说。 */
  let pendingTranscript = ''
  let pendingSince = 0
  /** 上一次已发送的转写，用于抑制回声与 ASR 重发。 */
  let lastDispatched: TranscriptMemory | null = null
  /** 本轮静音判定时刻，用于统计识别耗时。 */
  let asrStartedAt = 0

  interface VoiceStreamSession {
    ws: WebSocket | null
    ready: boolean
    unavailable: boolean
    partial: string
    finalText: string
    finished: Promise<string>
    resolveFinished: (text: string) => void
  }
  let voiceStream: VoiceStreamSession | null = null
  let streamArmed = false
  let pcmProcessor: ScriptProcessorNode | null = null

  interface BargeDebug {
    state: 'idle' | 'loading' | 'ready' | 'error'
    error: string
    armed: boolean
    speechStarts: number
    interrupts: number
    frames: number
  }
  const bargeDebug: BargeDebug = { state: 'idle', error: '', armed: false, speechStarts: 0, interrupts: 0, frames: 0 }

  function publishBargeDebug() {
    try {
      ;(window as Window & { __xcagiVoice?: BargeDebug }).__xcagiVoice = { ...bargeDebug, armed: bargeArmed }
    } catch { /* ignore */ }
  }

  function triggerBargeIn() {
    bargeDebug.speechStarts += 1
    // 朗读刚开始的 250ms 内忽略（可能是扬声器起播的自身声音）。
    if (!bargeArmed || !open.value || muted.value || Date.now() - bargeArmedAt < 250) {
      publishBargeDebug()
      return
    }
    // 不立刻 stopSpeaking：先标记候选，等这段语音转写出来再判断是附和还是真打断。
    bargeCandidate = true
    bargeUtteranceActive = true
    bargeDebug.interrupts += 1
    recordVoiceCount('barge_start')
    publishBargeDebug()
    window.clearTimeout(bargeForceTimer)
    bargeForceTimer = window.setTimeout(() => {
      // 用户持续说话超过确认窗口，视为真打断，先停下朗读以降低回授。
      if (bargeCandidate && stage.value === 'speaking') stopSpeaking()
    }, BARGE_CONFIRM_MS)
  }

  /** Float32(16k) → 16bit PCM WAV，供插话语音直接走 ASR / 判停。 */
  function encodeWav16k(samples: Float32Array): Blob {
    return encodeWav(samples, 16000)
  }

  /**
   * 发送闸门：先合入挂起片段，再判断是否值得发起一轮对话。
   * 规则来自 AssemblyAI/LiveKit 的 backchannel 过滤实践，判停由 Pipecat Smart Turn v3.2 本地模型给出。
   */
  async function dispatchUtterance(
    text: string,
    wav: Blob | null,
    turnCompletePromise?: Promise<boolean> | null,
  ): Promise<void> {
    const now = Date.now()
    const merged = `${pendingTranscript}${text}`.trim()
    if (!merged) {
      beginListening()
      return
    }
    // 同一句在短时间内重复到达（回声、VAD 抖动、ASR 重发）：不重复发起新一轮。
    if (isDuplicateTranscript(merged, lastDispatched, DUPLICATE_TRANSCRIPT_MS, now)) {
      recordVoiceCount('transcript_duplicate')
      recordVoiceEvent('transcript_duplicate')
      beginListening()
      return
    }
    if (isLowInformationTranscript(merged) && !hasIntent(merged)) {
      recordVoiceCount('transcript_low_info')
      beginListening()
      return
    }
    if (!pendingSince) pendingSince = now
    const pendingMaxMs = effectivePendingMaxMs(noiseFloor)
    const expired = now - pendingSince >= pendingMaxMs
    const hold = (next: string) => {
      pendingTranscript = next
      heardText.value = next
      if (open.value && !muted.value) beginListening()
    }
    // 语气词、附和词、未说完的连接结构：先不发，继续听用户补全。
    if (isFillerOnly(merged) && !expired) {
      hold(merged)
      return
    }
    if (looksIncomplete(merged) && !hasIntent(merged) && !expired) {
      hold(merged)
      return
    }
    // Smart Turn 判停：模型认为没说完且没有明确目的词时，再等一轮。
    if (wav && !expired) {
      const complete = turnCompletePromise
        ? await turnCompletePromise
        : await requestTurnComplete(wav, effectiveTurnThreshold(noiseFloor))
      if (!complete && !hasIntent(merged) && compactText(merged).length < 40) {
        hold(merged)
        return
      }
    }
    pendingTranscript = ''
    pendingSince = 0
    partialText.value = ''
    lastDispatched = { text: merged, at: now }
    heardText.value = merged
    if (asrStartedAt) {
      recordVoiceTiming('asr_total', Date.now() - asrStartedAt)
      asrStartedAt = 0
    }
    await handleUtterance(merged)
  }

  async function handleBargeUtterance(audio: Float32Array) {
    window.clearTimeout(bargeForceTimer)
    try {
      const controller = new AbortController()
      const timer = window.setTimeout(() => controller.abort(), TRANSCRIPTION_TIMEOUT_MS)
      const wav = encodeWav16k(audio)
      const text = await requestTranscript(wav, 'wav', controller.signal).finally(() => window.clearTimeout(timer))
      if (!open.value || muted.value) return
      const cleaned = normalizeVoiceTranscript(text)
      if (!cleaned || !hasTranscriptContent(cleaned)) {
        bargeUtteranceActive = false
        bargeCandidate = false
        beginListening()
        return
      }
      // 附和/语气词（嗯、对、好的…）：不清空当前朗读，也不发起新一轮。
      if (isFillerOnly(cleaned) && !hasIntent(cleaned)) {
        recordVoiceCount('barge_backchannel')
        bargeUtteranceActive = false
        bargeCandidate = false
        publishBargeDebug()
        return
      }
      // 真打断：这时才停止朗读，并把这句话当作新一轮输入。
      bargeCandidate = false
      recordVoiceCount('barge_interrupt')
      if (stage.value === 'speaking') {
        stopSpeaking()
        speechPaused.value = false
      }
      // 等上一轮 finally 收尾，避免两轮同时占用 handlingTurn。
      for (let i = 0; i < 60 && handlingTurn; i += 1) {
        await new Promise(resolve => window.setTimeout(resolve, 100))
      }
      if (!open.value || muted.value) return
      heardText.value = cleaned
      await dispatchUtterance(cleaned, wav)
    } catch {
      bargeUtteranceActive = false
      bargeCandidate = false
      if (open.value && !muted.value) beginListening()
    } finally {
      bargeUtteranceActive = false
      bargeCandidate = false
      // 插话轮结束了上一轮朗读时，上一轮的 finally 会主动跳过续听；这里补回聆听。
      if (open.value && !muted.value && !handlingTurn && !recorder) {
        await new Promise(resolve => window.setTimeout(resolve, SPEAK_TAIL_MS))
        if (open.value && !muted.value && !handlingTurn && !recorder) beginListening()
      }
    }
  }

  async function ensureBargeDetector(): Promise<BargeInVad | null> {
    if (bargeVad) return bargeVad
    if (!bargeLoading) {
      bargeDebug.state = 'loading'
      publishBargeDebug()
      bargeLoading = (async () => {
        try {
          const { MicVAD } = await import('@ricky0123/vad-web')
          // Electron 页面没有 COOP/COEP，禁用多线程 wasm，避免 SharedArrayBuffer 不可用。
          const ort = await import('onnxruntime-web')
          ort.env.wasm.numThreads = 1
          const base = `${import.meta.env.BASE_URL || '/'}assets/vad/`
          const vad = await MicVAD.new({
            baseAssetPath: base,
            onnxWASMBasePath: `${base}ort/`,
            model: 'v5',
            startOnLoad: false,
            getStream: () => ensureMicrophone(),
            pauseStream: async () => {},
            resumeStream: async (media: MediaStream) => media,
            // 用 speechStart 更快响应；250ms 起播保护避免把扬声器起播当成插话。
            onSpeechStart: () => triggerBargeIn(),
            onSpeechRealStart: () => triggerBargeIn(),
            onSpeechEnd: (audio: Float32Array) => {
              if (bargeUtteranceActive) void handleBargeUtterance(audio)
            },
            onVADMisfire: () => {},
            onFrameProcessed: (probabilities: { isSpeech?: number }) => {
              bargeDebug.frames += 1
              if (bargeDebug.frames % 25 === 0) publishBargeDebug()
              void probabilities
            },
          }) as BargeInVad
          bargeDebug.state = 'ready'
          publishBargeDebug()
          return vad
        } catch (error) {
          bargeDebug.state = 'error'
          bargeDebug.error = error instanceof Error ? error.message : String(error)
          publishBargeDebug()
          // 打断能力不可用时退化为原有半双工通话
          return null
        } finally {
          bargeLoading = null
        }
      })()
    }
    return bargeLoading
  }

  /** 通话开始即预热 VAD，避免首句朗读时还在下载模型。 */
  async function prepareBargeIn() {
    if (!open.value) return
    if (!bargeVad) bargeVad = await ensureBargeDetector()
    if (!bargeVad) return
    if (!bargeVad.listening) {
      try { await bargeVad.start() } catch (error) {
        bargeDebug.state = 'error'
        bargeDebug.error = error instanceof Error ? error.message : String(error)
        publishBargeDebug()
      }
    }
  }

  async function armBargeIn() {
    if (!open.value || muted.value) return
    bargeArmed = true
    bargeArmedAt = Date.now()
    publishBargeDebug()
    if (!bargeVad) bargeVad = await ensureBargeDetector()
    if (!bargeVad) return
    if (!bargeVad.listening) {
      try { await bargeVad.start() } catch { /* 保持原通话逻辑 */ }
    }
  }

  function disarmBargeIn() {
    bargeArmed = false
    window.clearTimeout(bargeForceTimer)
    bargeForceTimer = undefined
    bargeCandidate = false
    publishBargeDebug()
  }

  function teardownBargeIn() {
    bargeArmed = false
    window.clearTimeout(bargeForceTimer)
    bargeForceTimer = undefined
    bargeCandidate = false
    bargeUtteranceActive = false
    bargeDebug.state = 'idle'
    publishBargeDebug()
    const vad = bargeVad
    bargeVad = null
    if (vad) void vad.destroy().catch(() => {})
  }

  const callTitle = computed(() => (typeof title === 'string' ? title : title.value))
  const durationText = computed(() => {
    const m = Math.floor(seconds.value / 60).toString().padStart(2, '0')
    const s = (seconds.value % 60).toString().padStart(2, '0')
    return `${m}:${s}`
  })
  const statusText = computed(() => {
    switch (stage.value) {
      case 'connecting': return '正在接通…'
      case 'listening': return partialText.value ? '正在识别…' : '正在聆听…'
      case 'recognizing': return '正在识别…'
      case 'thinking': return '正在思考…'
      case 'speaking': return speechPaused.value ? '朗读已暂停' : '正在说话…'
      case 'muted': return '已静音'
      default: return errorText.value || '通话已结束'
    }
  })

  function setError(message: string) {
    errorText.value = message
  }

  function clearError() {
    errorText.value = ''
  }

  function releaseAudio() {
    window.clearInterval(monitorTimer)
    monitorTimer = undefined
    if (recorder && recorder.state !== 'inactive') {
      try { recorder.stop() } catch { /* already stopped */ }
    }
    recorder = null
    stream?.getTracks().forEach(track => track.stop())
    stream = null
    try { void audioCtx?.close() } catch { /* ignore */ }
    audioCtx = null
    analyser = null
    pcmProcessor = null
    cancelVoiceStream()
  }

  function voiceStreamUrl(): string {
    const path = apiUrl('/api/voice/stream')
    if (/^wss?:\/\//i.test(path)) return path
    if (/^https?:\/\//i.test(path)) return path.replace(/^http/i, 'ws')
    const origin = typeof window !== 'undefined' ? window.location.origin : ''
    return `${origin.replace(/^http/i, 'ws')}${path}`
  }

  /** 平台 FunASR 2pass 流式识别；任何环节不可用时返回 null，由整段上传兜底。 */
  function openVoiceStream(): VoiceStreamSession | null {
    if (typeof WebSocket === 'undefined') return null
    let resolveFinished: (text: string) => void = () => {}
    const session: VoiceStreamSession = {
      ws: null,
      ready: false,
      unavailable: false,
      partial: '',
      finalText: '',
      finished: new Promise<string>(resolve => { resolveFinished = resolve }),
      resolveFinished: (text: string) => resolveFinished(text),
    }
    try {
      const ws = new WebSocket(voiceStreamUrl())
      ws.binaryType = 'arraybuffer'
      session.ws = ws
      const readyTimer = window.setTimeout(() => {
        if (!session.ready) {
          session.unavailable = true
          session.resolveFinished(session.partial)
        }
      }, STREAM_READY_TIMEOUT_MS)
      ws.onmessage = (event: MessageEvent) => {
        let payload: { type?: string; text?: string; reason?: string } = {}
        try { payload = JSON.parse(String(event.data || '{}')) } catch { return }
        if (payload.type === 'ready') {
          window.clearTimeout(readyTimer)
          session.ready = true
          recordVoiceCount('stream_ready')
        } else if (payload.type === 'partial') {
          session.partial = String(payload.text || '')
          const preview = normalizeVoiceTranscript(session.partial)
          if (preview && !heardText.value) partialText.value = preview
        } else if (payload.type === 'final') {
          window.clearTimeout(readyTimer)
          session.finalText = String(payload.text || session.partial)
          session.resolveFinished(session.finalText)
        } else if (payload.type === 'unavailable' || payload.type === 'error') {
          window.clearTimeout(readyTimer)
          session.unavailable = true
          recordVoiceCount(`stream_${payload.type}`)
          recordVoiceEvent('stream_fallback', payload.reason || payload.type)
          noticeText.value = '流式识别不可用，已改用整段识别'
          session.resolveFinished(session.partial)
        }
      }
      ws.onerror = () => {
        session.unavailable = true
        recordVoiceEvent('stream_error')
        session.resolveFinished(session.partial)
      }
      ws.onclose = () => {
        window.clearTimeout(readyTimer)
        session.resolveFinished(session.finalText || session.partial)
      }
    } catch {
      return null
    }
    return session
  }

  function ensurePcmProcessor(): void {
    if (pcmProcessor || !audioCtx || !analyser) return
    const factory = (audioCtx as AudioContext & { createScriptProcessor?: AudioContext['createScriptProcessor'] })
      .createScriptProcessor
    if (typeof factory !== 'function') return
    try {
      const node = factory.call(audioCtx, 4096, 1, 1)
      const silent = audioCtx.createGain()
      silent.gain.value = 0
      node.onaudioprocess = (event: AudioProcessingEvent) => {
        const session = voiceStream
        if (!streamArmed || !session?.ready || !session.ws || session.ws.readyState !== WebSocket.OPEN) return
        const pcm = downsampleToPcm16(event.inputBuffer.getChannelData(0), audioCtx?.sampleRate || 16000)
        if (pcm.byteLength) session.ws.send(pcm)
      }
      // analyser → processor → 静音增益 → destination：保证节点被驱动且不产生回声。
      analyser.connect(node)
      node.connect(silent)
      silent.connect(audioCtx.destination)
      pcmProcessor = node
    } catch {
      pcmProcessor = null
    }
  }

  /** 用户开口时启动流式识别；失败由整段上传兜底。 */
  function startVoiceStream(): void {
    if (voiceStream) return
    ensurePcmProcessor()
    const session = openVoiceStream()
    voiceStream = session
    streamArmed = Boolean(session)
  }

  /** 静音后结束流式识别；返回最终文本（无流式通道时返回 null）。 */
  function finishVoiceStream(): Promise<string> | null {
    const session = voiceStream
    streamArmed = false
    if (!session) return null
    voiceStream = null
    const ws = session.ws
    if (!session.unavailable && ws && ws.readyState === WebSocket.OPEN) {
      try { ws.send(JSON.stringify({ type: 'end' })) } catch { /* ignore */ }
    }
    return Promise.race([
      session.finished,
      new Promise<string>(resolve => {
        window.setTimeout(() => resolve(session.finalText || session.partial), STREAM_FINAL_TIMEOUT_MS)
      }),
    ]).then((text) => {
      try { ws?.close() } catch { /* ignore */ }
      return text
    })
  }

  function cancelVoiceStream(): void {
    streamArmed = false
    const session = voiceStream
    voiceStream = null
    if (!session) return
    try { session.ws?.close() } catch { /* ignore */ }
    session.resolveFinished(session.finalText || session.partial)
  }

  async function ensureMicrophone(): Promise<MediaStream> {
    if (stream && stream.getAudioTracks().some(track => track.readyState === 'live')) return stream
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('当前环境不支持麦克风采集')
    if (typeof window.MediaRecorder === 'undefined') throw new Error('当前环境不支持录音')
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    })
    audioCtx = audioCtx || new AudioContext()
    try { await audioCtx.resume() } catch { /* ignore */ }
    const source = audioCtx.createMediaStreamSource(stream)
    // 部分 USB 麦克风增益偏低，放大后再做能量判断，避免把正常说话当成静音。
    const gain = audioCtx.createGain()
    gain.gain.value = 2.5
    analyser = audioCtx.createAnalyser()
    analyser.fftSize = 1024
    source.connect(gain)
    gain.connect(analyser)
    ensurePcmProcessor()
    return stream
  }

  function readLevel(): number {
    if (!analyser) return 0
    const buffer = new Float32Array(analyser.fftSize)
    analyser.getFloatTimeDomainData(buffer)
    let sum = 0
    for (let i = 0; i < buffer.length; i += 1) sum += buffer[i] * buffer[i]
    return Math.sqrt(sum / buffer.length)
  }

  function preferredMime(): string {
    try {
      return MIME_CANDIDATES.find(value => MediaRecorder.isTypeSupported?.(value)) || ''
    } catch {
      return ''
    }
  }

  function stopCycle() {
    stopping = true
    window.clearInterval(monitorTimer)
    monitorTimer = undefined
    if (recorder && recorder.state !== 'inactive') {
      try { recorder.stop() } catch { /* ignore */ }
    }
  }

  function beginListening() {
    if (!open.value || muted.value || stage.value === 'ended' || handlingTurn) return
    const token = ++cycleToken
    clearError()
    stage.value = 'listening'
    cancelVoiceStream()
    chunks = []
    speechStartedAt = 0
    lastVoiceAt = 0
    calibratedUntil = Date.now() + CALIBRATION_MS
    noiseFloor = 0.012
    threshold = 0.03
    voicedRun = 0
    stopping = false
    void (async () => {
      try {
        const media = await ensureMicrophone()
        if (token !== cycleToken || !open.value || muted.value) return
        const mime = preferredMime()
        const active = mime ? new MediaRecorder(media, { mimeType: mime }) : new MediaRecorder(media)
        recorder = active
        active.addEventListener('dataavailable', event => {
          if (token === cycleToken && event.data.size) chunks.push(event.data)
        })
        active.addEventListener('stop', () => {
          if (token === cycleToken) void finishUtterance(token, active)
        })
        active.start(200)
        const startedAt = Date.now()
        monitorTimer = window.setInterval(() => {
          if (token !== cycleToken) return
          const now = Date.now()
          const level = readLevel()
          if (now < calibratedUntil) {
            noiseFloor = noiseFloor * 0.7 + level * 0.3
            threshold = clamp(noiseFloor * 2.0, 0.008, 0.06)
            return
          }
          const voiced = level > threshold
          voicedRun = voiced ? voicedRun + 1 : 0
          if (voiced && voicedRun >= VOICED_FRAMES_TO_START) {
            lastVoiceAt = now
            if (!speechStartedAt) {
              speechStartedAt = now
              // 开口即开始流式转写：等用户说完时文本基本已经就绪。
              startVoiceStream()
            }
          }
          // 运行时诊断（可被 DevTools 读取；不影响正常通话逻辑）。
          ;(window as unknown as { __voiceCallDebug?: unknown }).__voiceCallDebug = {
            level, threshold, speechStartedAt, voiced, token, cycleToken,
          }
          if (speechStartedAt && now - lastVoiceAt >= SILENCE_MS) {
            stopCycle()
            return
          }
          if (now - startedAt >= MAX_UTTERANCE_MS) stopCycle()
        }, 100)
      } catch (error) {
        if (token !== cycleToken) return
        setError(error instanceof Error && error.name === 'NotAllowedError'
          ? '麦克风权限被拒绝，请在系统设置中允许后重试'
          : error instanceof Error ? error.message : '麦克风不可用')
        // 保留通话界面显示具体原因，用户可点「挂断」退出后重试。
        stage.value = 'ended'
      }
    })()
  }

  async function finishUtterance(token: number, finished: MediaRecorder) {
    window.clearInterval(monitorTimer)
    monitorTimer = undefined
    if (token !== cycleToken || !open.value) return
    const duration = speechStartedAt ? Date.now() - speechStartedAt : 0
    const mime = finished.mimeType || preferredMime() || 'audio/webm'
    const blob = new Blob(chunks, { type: mime })
    chunks = []
    recorder = null
    const streamFinal = finishVoiceStream()
    if (stopping && (duration < MIN_UTTERANCE_MS || !speechStartedAt || !blob.size)) {
      beginListening()
      return
    }
    if (!speechStartedAt || duration < MIN_UTTERANCE_MS || !blob.size) {
      beginListening()
      return
    }
    if (streamFinal) {
      asrStartedAt = Date.now()
      stage.value = 'recognizing'
      // 转写与判停并行：等流式文本的同时就把 Smart Turn 跑起来。
      const wav = await blobToWav16k(blob)
      if (token !== cycleToken || !open.value) return
      const turnPromise = wav ? requestTurnComplete(wav, effectiveTurnThreshold(noiseFloor)) : null
      const streamText = normalizeVoiceTranscript(await streamFinal)
      if (token !== cycleToken || !open.value) return
      if (streamText && hasTranscriptContent(streamText)) {
        heardText.value = streamText
        await dispatchUtterance(streamText, wav, turnPromise)
        return
      }
      if (turnPromise) void turnPromise.catch(() => undefined)
    }
    await transcribeAndReply(blob, mime, token)
  }

  async function requestTranscript(blob: Blob, ext: string, signal: AbortSignal): Promise<string> {
    const form = new FormData()
    form.append('file', blob, `voice-call.${ext}`)
    const response = await apiFetch('/api/voice/transcribe', {
      method: 'POST',
      body: form,
      signal,
    })
    const raw = await response.text()
    let data: { success?: boolean; detail?: string; message?: string; error?: string; data?: { text?: string } } | null = null
    try { data = raw ? JSON.parse(raw) : null } catch { /* invalid json */ }
    if (!response.ok || !data || data.success === false) {
      throw new Error(String(data?.detail || data?.message || data?.error || raw || `HTTP ${response.status}`))
    }
    return normalizeVoiceTranscript(String(data.data?.text || ''))
  }

  async function transcribeAndReply(blob: Blob, mime: string, token: number) {
    asrStartedAt = Date.now()
    stage.value = 'recognizing'
    const ext = mime.includes('webm') ? 'webm' : mime.includes('ogg') ? 'ogg' : /mp4|m4a/.test(mime) ? 'm4a' : 'wav'
    const controller = new AbortController()
    const timer = window.setTimeout(() => controller.abort(), TRANSCRIPTION_TIMEOUT_MS)
    try {
      // 空转写、纯占位 token 或识别报错都视为失败：同一段录音自动重试一次。
      let text = ''
      for (let attempt = 0; attempt < 2 && !text; attempt += 1) {
        try {
          text = await requestTranscript(blob, ext, controller.signal)
        } catch (error) {
          if (controller.signal.aborted || attempt === 1) throw error
        }
      }
      if (token !== cycleToken || !open.value) return
      if (!text || !hasTranscriptContent(text)) {
        recordVoiceCount('transcript_empty')
        partialText.value = ''
        beginListening()
        return
      }
      if (isLowInformationTranscript(text) && !hasIntent(text)) {
        recordVoiceCount('transcript_low_info')
        partialText.value = ''
        beginListening()
        return
      }
      heardText.value = text
      await dispatchUtterance(text, await blobToWav16k(blob))
    } catch (error) {
      if (token !== cycleToken || !open.value) return
      setError(controller.signal.aborted ? '语音识别超时，请再说一次' : (error instanceof Error ? error.message : '语音识别失败'))
      beginListening()
    } finally {
      window.clearTimeout(timer)
    }
  }

  async function handleUtterance(text: string) {
    handlingTurn = true
    stage.value = 'thinking'
    const before = messages.value.length
    // 模型思考常常要好几秒，纯静音会让人以为断线：超过 1.2s 还没回复就先垫一句口头确认。
    let ack: Promise<unknown> | null = null
    const ackTimer = speakerOn.value
      ? window.setTimeout(() => { ack = speakText(ACK_LINE) }, ACK_DELAY_MS)
      : null
    try {
      // 模型/网络偶发失败：同一句自动重发一次，仍失败再播报“再说一次”。
      let reply = ''
      let failed = true
      for (let attempt = 0; attempt < 2; attempt += 1) {
        await sendMessage(text)
        if (!open.value) return
        const candidate = latestAssistantReply(before)
        if (candidate && !FAILURE_NOTICE.test(candidate)) {
          reply = candidate
          failed = false
          break
        }
        reply = candidate || ''
        if (attempt === 0) {
          clearError()
          await new Promise(resolve => window.setTimeout(resolve, 500))
          if (!open.value) return
        }
      }
      // 文本轮失败时会回读服务端再判断；语音轮复用同一闭环：
      // 先确认后端是否其实已经成功（只是前端没收到），再决定要不要让用户重说。
      if (failed && refreshMessages) {
        try { await refreshMessages() } catch { /* 回读失败时按原判断处理 */ }
        if (!open.value) return
        const refreshed = latestAssistantReply(before)
        if (refreshed && !FAILURE_NOTICE.test(refreshed)) {
          reply = refreshed
          failed = false
        }
      }
      if (ackTimer) window.clearTimeout(ackTimer)
      if (ack) await ack
      if (!open.value) return
      // 已执行但结果未知：不要让用户重复提交，也不要说「再说一次」。
      const outcomeUnknown = failed && lastAssistantOutcome(before) === 'unknown'
      if (failed) {
        replyText.value = outcomeUnknown ? TURN_UNKNOWN_LINE : '这次没拿到回复，请再说一次'
        setError(outcomeUnknown ? '本轮结果待核对' : '网络有点慢，请再说一次')
      } else {
        replyText.value = reply
      }
      if (speakerOn.value) {
        const line = failed ? (outcomeUnknown ? TURN_UNKNOWN_LINE : SPOKEN_RETRY_HINT) : reply
        stage.value = 'speaking'
        speechPaused.value = false
        // 不阻塞朗读：VAD 模型加载期间先正常播报，加载完成后自动生效。
        void armBargeIn()
        let speakFailed = false
        await speakText(line, { onError: () => { speakFailed = true } })
        disarmBargeIn()
        if (speakFailed && open.value) {
          recordVoiceCount('tts_online_failed')
          recordVoiceEvent('tts_fallback')
          const speech = getVoiceSupport().speechSynthesis
          await speakWithSystemVoice(line)
          if (!speech) {
            recordVoiceCount('tts_unavailable')
            noticeText.value = '当前环境不支持朗读，可在语音设置中检查'
          }
        }
      }
    } catch (error) {
      if (ackTimer) window.clearTimeout(ackTimer)
      if (open.value) setError(error instanceof Error ? error.message.slice(0, 60) : '通话暂时不可用')
    } finally {
      disarmBargeIn()
      speechPaused.value = false
      partialText.value = ''
      handlingTurn = false
      // 插话轮由 VAD 音频独立转写，旧轮不再抢占麦克风。
      if (!bargeUtteranceActive && open.value && !muted.value) {
        await new Promise(resolve => window.setTimeout(resolve, SPEAK_TAIL_MS))
        if (open.value && !muted.value && !handlingTurn) {
          stage.value = 'listening'
          beginListening()
        }
      }
    }
  }

  function latestAssistantReply(fromIndex: number): string {
    const list = messages.value
    for (let i = list.length - 1; i >= Math.max(0, fromIndex); i -= 1) {
      const item = list[i]
      if (item?.role !== 'ai' || item.streamingShell) continue
      const plain = plainTextFromChatHtml(String(item.content || '')).trim()
      if (plain) return plain
    }
    return ''
  }

  /** 本轮 AI 回执是否标记为「已执行结果未知」，用于区分「重说」和「勿重复提交」。 */
  function lastAssistantOutcome(fromIndex: number): string {
    const list = messages.value
    for (let i = list.length - 1; i >= Math.max(0, fromIndex); i -= 1) {
      const item = list[i]
      if (item?.role !== 'ai' || item.streamingShell) continue
      if (item.workflowAction === 'unknown') return 'unknown'
      return String(item.execution?.outcome || '')
    }
    return ''
  }

  function speakWithSystemVoice(text: string): Promise<void> {
    const plain = String(text || '').trim()
    if (!plain || !('speechSynthesis' in window)) return Promise.resolve()
    return new Promise<void>(resolve => {
      try {
        window.speechSynthesis.cancel()
        const utterance = createChineseUtterance(plain)
        const done = () => resolve()
        utterance.onend = done
        utterance.onerror = done
        window.speechSynthesis.speak(utterance)
      } catch {
        resolve()
      }
    })
  }

  function start() {
    if (open.value) return
    const support = getVoiceSupport()
    recordVoiceEvent('call_start')
    cancelVoiceStream()
    open.value = true
    stage.value = 'connecting'
    seconds.value = 0
    heardText.value = ''
    partialText.value = ''
    replyText.value = ''
    noticeText.value = support.streaming ? '' : '当前环境不支持流式识别，将使用整段识别'
    speechPaused.value = false
    pendingTranscript = ''
    pendingSince = 0
    lastDispatched = null
    asrStartedAt = 0
    clearError()
    muted.value = false
    handlingTurn = false
    bargeDebug.speechStarts = 0
    bargeDebug.interrupts = 0
    bargeDebug.frames = 0
    bargeUtteranceActive = false
    // 能力缺失时仍打开通话界面并说明原因，避免点「语音通话」像没反应。
    if (!support.microphone || !support.recorder) {
      recordVoiceEvent('unsupported', !support.microphone ? 'microphone' : 'recorder')
      stage.value = 'ended'
      setError(!support.microphone
        ? '当前环境不支持麦克风采集，请检查系统与浏览器权限'
        : '当前环境不支持录音，请升级浏览器或客户端')
      return
    }
    void prepareBargeIn()
    window.clearInterval(tickTimer)
    tickTimer = window.setInterval(() => {
      if (open.value && stage.value !== 'ended') seconds.value += 1
    }, 1000)
    window.setTimeout(() => {
      if (open.value) beginListening()
    }, 400)
  }

  function hangUp() {
    if (open.value) recordVoiceEvent('call_end', `${seconds.value}s`)
    open.value = false
    stage.value = 'ended'
    pendingTranscript = ''
    pendingSince = 0
    partialText.value = ''
    speechPaused.value = false
    asrStartedAt = 0
    cycleToken += 1
    window.clearInterval(tickTimer)
    tickTimer = undefined
    teardownBargeIn()
    releaseAudio()
    stopSpeaking()
  }

  function toggleMute() {
    if (!open.value) return
    if (muted.value) {
      muted.value = false
      beginListening()
      return
    }
    muted.value = true
    stage.value = 'muted'
    cycleToken += 1
    releaseAudio()
    stopSpeaking()
    speechPaused.value = false
  }

  function toggleSpeaker() {
    speakerOn.value = !speakerOn.value
    if (!speakerOn.value) {
      stopSpeaking()
      speechPaused.value = false
      return
    }
    // 重新打开免提时继续被暂停的朗读，而不是从头再说一遍。
    if (speechPaused.value) {
      resumeSpeaking()
      speechPaused.value = false
    }
  }

  /** 暂停/继续当前朗读；打断或挂断时自动恢复未暂停状态。 */
  function toggleSpeechPause() {
    if (!open.value || !speakerOn.value) return
    if (speechPaused.value) {
      resumeSpeaking()
      speechPaused.value = false
      recordVoiceEvent('tts_resume')
      return
    }
    if (pauseSpeaking()) {
      speechPaused.value = true
      recordVoiceEvent('tts_pause')
    }
  }

  if (getCurrentScope()) onScopeDispose(hangUp)

  return {
    open,
    stage,
    seconds,
    durationText,
    statusText,
    callTitle,
    heardText,
    partialText,
    replyText,
    errorText,
    noticeText,
    muted,
    speakerOn,
    speechPaused,
    start,
    hangUp,
    toggleMute,
    toggleSpeaker,
    toggleSpeechPause,
  }
}
