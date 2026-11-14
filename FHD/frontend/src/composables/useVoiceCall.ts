/**
 * 桌面端 AI 语音通话（半双工轮次）：聆听 → 转写 → 对话 → 朗读 → 继续聆听。
 *
 * 与手机端 voice_call_screen 行为对齐：自动断句、静音/免提/挂断、
 * 实时字幕与通话计时。语音识别复用现有 /api/voice/transcribe，
 * 对话复用当前会话的 sendMessage，朗读复用统一 TTS 入口。
 */
import { computed, getCurrentScope, onScopeDispose, ref, type Ref } from 'vue'
import { apiFetch } from '@/utils/apiBase'
import { speakText, stopSpeaking, createChineseUtterance } from '@/utils/tts'
import { plainTextFromChatHtml } from '@/utils/sanitizeHtml'
import type { ChatMessage } from './useChatMessages'

export type VoiceCallStage = 'connecting' | 'listening' | 'thinking' | 'speaking' | 'muted' | 'ended'

interface UseVoiceCallDeps {
  sendMessage: (message: string) => Promise<void>
  messages: Ref<ChatMessage[]>
  title?: Ref<string> | string
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

export function useVoiceCall({ sendMessage, messages, title = '通用助手' }: UseVoiceCallDeps) {
  const open = ref(false)
  const stage = ref<VoiceCallStage>('connecting')
  const seconds = ref(0)
  const heardText = ref('')
  const replyText = ref('')
  const errorText = ref('')
  const muted = ref(false)
  const speakerOn = ref(true)

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

  const callTitle = computed(() => (typeof title === 'string' ? title : title.value))
  const durationText = computed(() => {
    const m = Math.floor(seconds.value / 60).toString().padStart(2, '0')
    const s = (seconds.value % 60).toString().padStart(2, '0')
    return `${m}:${s}`
  })
  const statusText = computed(() => {
    switch (stage.value) {
      case 'connecting': return '正在接通…'
      case 'listening': return '正在聆听…'
      case 'thinking': return '正在思考…'
      case 'speaking': return '正在说话…'
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
  }

  async function ensureMicrophone(): Promise<MediaStream> {
    if (stream && stream.getAudioTracks().some(track => track.readyState === 'live')) return stream
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('当前环境不支持麦克风采集')
    if (typeof window.MediaRecorder === 'undefined') throw new Error('当前环境不支持录音')
    stream = await navigator.mediaDevices.getUserMedia({ audio: true })
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
            if (!speechStartedAt) speechStartedAt = now
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
    if (stopping && (duration < MIN_UTTERANCE_MS || !speechStartedAt || !blob.size)) {
      beginListening()
      return
    }
    if (!speechStartedAt || duration < MIN_UTTERANCE_MS || !blob.size) {
      beginListening()
      return
    }
    await transcribeAndReply(blob, mime, token)
  }

  async function transcribeAndReply(blob: Blob, mime: string, token: number) {
    stage.value = 'thinking'
    const ext = mime.includes('webm') ? 'webm' : mime.includes('ogg') ? 'ogg' : /mp4|m4a/.test(mime) ? 'm4a' : 'wav'
    const controller = new AbortController()
    const timer = window.setTimeout(() => controller.abort(), TRANSCRIPTION_TIMEOUT_MS)
    try {
      const form = new FormData()
      form.append('file', blob, `voice-call.${ext}`)
      const response = await apiFetch('/api/voice/transcribe', {
        method: 'POST',
        body: form,
        signal: controller.signal,
      })
      const raw = await response.text()
      let data: { success?: boolean; detail?: string; message?: string; error?: string; data?: { text?: string } } | null = null
      try { data = raw ? JSON.parse(raw) : null } catch { /* invalid json */ }
      if (token !== cycleToken || !open.value) return
      if (!response.ok || !data || data.success === false) {
        throw new Error(String(data?.detail || data?.message || data?.error || raw || `HTTP ${response.status}`))
      }
      const text = String(data.data?.text || '').trim()
      if (!text) {
        beginListening()
        return
      }
      heardText.value = text
      await handleUtterance(text)
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
    let ack: Promise<void> | null = null
    const ackTimer = speakerOn.value
      ? window.setTimeout(() => { ack = speakText(ACK_LINE) }, ACK_DELAY_MS)
      : null
    try {
      await sendMessage(text)
      if (ackTimer) window.clearTimeout(ackTimer)
      if (ack) await ack
      if (!open.value) return
      const reply = latestAssistantReply(before)
      // 失败回执（超时/连接中断）是一段技术告警，朗读出来非常出戏：
      // 改为一句口语提示，并直接回到聆听，让用户重说。
      const failed = !reply || FAILURE_NOTICE.test(reply)
      replyText.value = failed ? '' : reply
      if (failed) setError('网络有点慢，请再说一次')
      if (speakerOn.value) {
        const line = failed ? SPOKEN_RETRY_HINT : reply
        stage.value = 'speaking'
        let speakFailed = false
        await speakText(line, { onError: () => { speakFailed = true } })
        if (speakFailed && open.value) await speakWithSystemVoice(line)
      }
    } catch (error) {
      if (ackTimer) window.clearTimeout(ackTimer)
      if (open.value) setError(error instanceof Error ? error.message.slice(0, 60) : '通话暂时不可用')
    } finally {
      handlingTurn = false
      if (open.value && !muted.value) {
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
    open.value = true
    stage.value = 'connecting'
    seconds.value = 0
    heardText.value = ''
    replyText.value = ''
    clearError()
    muted.value = false
    handlingTurn = false
    window.clearInterval(tickTimer)
    tickTimer = window.setInterval(() => {
      if (open.value && stage.value !== 'ended') seconds.value += 1
    }, 1000)
    window.setTimeout(() => {
      if (open.value) beginListening()
    }, 400)
  }

  function hangUp() {
    open.value = false
    stage.value = 'ended'
    cycleToken += 1
    window.clearInterval(tickTimer)
    tickTimer = undefined
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
  }

  function toggleSpeaker() {
    speakerOn.value = !speakerOn.value
    if (!speakerOn.value) stopSpeaking()
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
    replyText,
    errorText,
    muted,
    speakerOn,
    start,
    hangUp,
    toggleMute,
    toggleSpeaker,
  }
}
