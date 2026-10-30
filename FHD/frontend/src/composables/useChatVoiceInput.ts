import { ref, computed, watch, getCurrentScope, onScopeDispose, type Ref } from 'vue'
import { apiFetch } from '@/utils/apiBase'
import { resolveChatIdentity } from '@/utils/chatStorageKeys'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'

const MIN_RECORD_MS = 300
const MAX_RECORD_MS = 60_000
const VOICE_PREFERRED_MIME_TYPES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/ogg', 'audio/mp4', 'audio/wav']
type VoiceState = 'idle' | 'requesting' | 'recording' | 'transcribing' | 'error'

export interface UseChatVoiceInputDeps {
  messageInput: Ref<string>
  isLoading: Ref<boolean>
  sessionId?: Ref<string>
}

export function useChatVoiceInput({ messageInput, isLoading, sessionId }: UseChatVoiceInputDeps) {
  const voiceState = ref<VoiceState>('idle')
  const voiceErrorText = ref('')
  const voiceElapsedSecs = ref(0)
  /** First ASR in this session often pays faster-whisper load cost (~6–7s). */
  const voiceModelWarm = ref(false)
  const voiceColdHint = ref(false)
  let recorder: MediaRecorder | null = null
  let stream: MediaStream | null = null
  let transcription: AbortController | null = null
  let generation = 0
  let maxTimer: number | undefined, tickTimer: number | undefined, errorTimer: number | undefined
  const scopeKey = () => JSON.stringify([sessionId?.value, resolveChatIdentity(), productReadAccountEpoch.value])

  // Keep the requesting button enabled so a release can cancel a pending permission prompt.
  const voiceButtonDisabled = computed(() => voiceState.value === 'transcribing' || isLoading.value)
  const voiceButtonClass = computed(() => ({
    'voice-input-btn-idle': voiceState.value === 'idle' || voiceState.value === 'requesting',
    'voice-input-btn-recording': voiceState.value === 'recording',
    'voice-input-btn-transcribing': voiceState.value === 'transcribing',
    'voice-input-btn-error': voiceState.value === 'error',
  }))
  const voiceButtonIcon = computed(() => {
    if (voiceState.value === 'recording') return 'fa-stop-circle'
    if (voiceState.value === 'requesting' || voiceState.value === 'transcribing') return 'fa-spinner fa-pulse'
    return voiceState.value === 'error' ? 'fa-exclamation-circle' : 'fa-microphone'
  })
  const voiceButtonText = computed(() => {
    if (voiceState.value === 'requesting') return '等待麦克风授权…'
    if (voiceState.value === 'recording') return `松开发送 ${voiceElapsedSecs.value.toFixed(1)}s`
    if (voiceState.value === 'transcribing') {
      return voiceColdHint.value || !voiceModelWarm.value ? '首次识别需加载模型…' : '识别中...'
    }
    return voiceState.value === 'error' ? voiceErrorText.value || '语音失败' : '按住说话'
  })
  const voiceButtonTitle = computed(() => {
    if (voiceState.value === 'requesting') return '正在等待麦克风权限；松开或移出按钮可取消'
    if (voiceState.value === 'recording') return '松开立即识别并填入输入框；移出按钮可取消本次录音'
    if (voiceState.value === 'transcribing') {
      return voiceColdHint.value || !voiceModelWarm.value
        ? '首次识别需加载语音模型，可能需要数秒；这不是服务断开'
        : '正在把语音转成文字...'
    }
    return voiceState.value === 'error' ? voiceErrorText.value || '语音识别失败' : '按住这里说话，松开后会自动转写成文字填入输入框'
  })
  const voiceFeedbackText = computed(() => {
    if (voiceState.value === 'error') return voiceErrorText.value || '语音识别失败，请重试'
    if (voiceState.value === 'transcribing' && (voiceColdHint.value || !voiceModelWarm.value)) {
      return '首次识别需加载模型，请稍候（通常数秒）；语音可用时不代表业务健康检查失败'
    }
    return ''
  })

  function notifyApiReachable(source: string) {
    try {
      window.dispatchEvent(new CustomEvent('xcagi:api-reachable', { detail: { source } }))
    } catch {
      /* ignore */
    }
  }

  function setVoiceError(message: string) {
    voiceErrorText.value = message
    voiceState.value = 'error'
    window.clearTimeout(errorTimer)
    errorTimer = window.setTimeout(() => {
      if (voiceState.value === 'error') { voiceState.value = 'idle'; voiceErrorText.value = '' }
    }, 4000)
  }

  function resetTimers() {
    window.clearTimeout(maxTimer)
    window.clearInterval(tickTimer)
    maxTimer = tickTimer = undefined
  }

  function releaseStream(target: MediaStream | null) {
    target?.getTracks().forEach(track => track.stop())
    if (stream === target) { stream = null; recorder = null }
  }

  function cleanupVoiceInput() {
    generation += 1
    transcription?.abort()
    transcription = null
    resetTimers()
    window.clearTimeout(errorTimer)
    const active = recorder, activeStream = stream
    try { if (active && active.state !== 'inactive') active.stop() } catch { /* already stopped */ }
    releaseStream(activeStream)
    voiceState.value = 'idle'
    voiceErrorText.value = ''
    voiceElapsedSecs.value = 0
  }
  watch([scopeKey, isLoading], cleanupVoiceInput, { flush: 'sync' })
  if (getCurrentScope()) onScopeDispose(cleanupVoiceInput)

  async function submitVoiceBlob(blob: Blob, isCurrent: () => boolean) {
    const controller = new AbortController()
    transcription = controller
    const timeout = window.setTimeout(() => controller.abort(), MAX_RECORD_MS)
    voiceColdHint.value = !voiceModelWarm.value
    voiceState.value = 'transcribing'
    try {
      const mime = blob.type.toLowerCase()
      const ext = mime.includes('webm') ? 'webm' : mime.includes('ogg') ? 'ogg' : /mp4|m4a/.test(mime) ? 'm4a' : /wav|wave/.test(mime) ? 'wav' : 'bin'
      const form = new FormData()
      form.append('file', blob, `chat-voice.${ext}`)
      const response = await apiFetch('/api/voice/transcribe', { method: 'POST', body: form, signal: controller.signal })
      const raw = await response.text()
      if (!isCurrent()) return
      if (controller.signal.aborted) throw new DOMException('请求已中断', 'AbortError')
      let data: { success?: boolean; detail?: string; message?: string; error?: string; data?: { text?: string; elapsed_ms?: number; cold_start?: boolean; model_loaded?: boolean } } | null = null
      try { data = raw ? JSON.parse(raw) : null } catch { /* report invalid response below */ }
      if (!response.ok || !data || data.success === false) throw new Error(String(data?.detail || data?.message || data?.error || raw || `HTTP ${response.status}`))
      // Successful voice proves API is reachable — clear false「服务连接中断」from sidebar health.
      notifyApiReachable('voice-transcribe')
      const elapsed = Number(data.data?.elapsed_ms || 0)
      const cold = data.data?.cold_start === true || (!voiceModelWarm.value && elapsed >= 2500)
      voiceColdHint.value = cold
      voiceModelWarm.value = true
      const text = String(data.data?.text || '').trim()
      if (!text) { setVoiceError('未识别到语音，请靠近麦克风后重试'); return }
      const existing = messageInput.value.trimEnd()
      messageInput.value = existing ? `${existing} ${text}` : text
      voiceState.value = 'idle'
      voiceErrorText.value = ''
      voiceColdHint.value = false
      const input = document.getElementById('messageInput') as HTMLTextAreaElement | null
      input?.focus()
      try { input?.setSelectionRange(input.value.length, input.value.length) } catch { /* unsupported input */ }
    } catch (error) {
      if (!isCurrent()) return
      const message = controller.signal.aborted ? '语音识别超时，请重试' : error instanceof Error ? error.message : '语音识别失败'
      setVoiceError(message.length > 48 ? `${message.slice(0, 48)}...` : message)
    } finally {
      window.clearTimeout(timeout)
      if (transcription === controller) transcription = null
    }
  }

  async function startVoiceRecording() {
    if (voiceButtonDisabled.value || !['idle', 'error'].includes(voiceState.value)) return
    if (!navigator.mediaDevices?.getUserMedia) { setVoiceError('当前浏览器不支持麦克风采集'); return }
    if (typeof window.MediaRecorder === 'undefined') { setVoiceError('当前浏览器不支持 MediaRecorder'); return }
    cleanupVoiceInput()
    const token = generation, scope = scopeKey()
    const isCurrent = () => token === generation && scope === scopeKey()
    voiceState.value = 'requesting'
    let granted: MediaStream
    try {
      granted = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (error) {
      if (!isCurrent()) return
      const e = error as { name?: string; message?: string }
      setVoiceError(['NotAllowedError', 'SecurityError'].includes(e.name || '')
        ? '麦克风权限被拒绝，请在浏览器地址栏授权后重试'
        : ['NotFoundError', 'OverconstrainedError'].includes(e.name || '') ? '未检测到可用麦克风设备' : `获取麦克风失败：${e.message || e.name || '未知错误'}`)
      return
    }
    if (!isCurrent()) { releaseStream(granted); return }
    stream = granted
    let active: MediaRecorder
    let mime = ''
    try {
      mime = VOICE_PREFERRED_MIME_TYPES.find(value => {
        try { return MediaRecorder.isTypeSupported?.(value) } catch { return false }
      }) || ''
      active = mime ? new MediaRecorder(granted, { mimeType: mime }) : new MediaRecorder(granted)
      recorder = active
    } catch (error) {
      releaseStream(granted)
      setVoiceError(`无法创建录音器：${error instanceof Error ? error.message : '未知错误'}`)
      return
    }
    const chunks: Blob[] = []
    const startedAt = Date.now()
    active.addEventListener('dataavailable', event => { if (isCurrent() && event.data.size) chunks.push(event.data) })
    active.addEventListener('stop', () => {
      releaseStream(granted)
      if (!isCurrent()) return
      resetTimers()
      if (Date.now() - startedAt < MIN_RECORD_MS) { setVoiceError('录音太短（<0.3s），请稍微按久一点再松开'); return }
      const blob = new Blob(chunks, { type: mime || active.mimeType || 'audio/webm' })
      if (!blob.size) { setVoiceError('未采到音频数据，请检查麦克风'); return }
      void submitVoiceBlob(blob, isCurrent)
    })
    active.addEventListener('error', event => {
      if (!isCurrent()) return
      cleanupVoiceInput()
      setVoiceError(String((event as Event & { error?: Error }).error?.message || '录音失败'))
    })
    try { active.start() } catch (error) {
      cleanupVoiceInput()
      setVoiceError(`启动录音失败：${error instanceof Error ? error.message : '未知错误'}`)
      return
    }
    voiceState.value = 'recording'
    maxTimer = window.setTimeout(() => stopVoiceRecording(false), MAX_RECORD_MS)
    tickTimer = window.setInterval(() => { voiceElapsedSecs.value = (Date.now() - startedAt) / 1000 }, 100)
  }

  function stopVoiceRecording(cancel: boolean) {
    if (voiceState.value === 'requesting') { cleanupVoiceInput(); return }
    if (voiceState.value !== 'recording' || !recorder) return
    if (cancel) { cleanupVoiceInput(); return }
    voiceColdHint.value = !voiceModelWarm.value
    voiceState.value = 'transcribing'
    try { if (recorder.state !== 'inactive') recorder.stop() } catch {
      cleanupVoiceInput()
      setVoiceError('录音停止失败，请重试')
    }
  }

  async function warmVoiceModel() {
    if (voiceModelWarm.value) return
    try {
      const response = await apiFetch('/api/voice/warm', { method: 'POST', timeoutMs: 120_000 })
      if (response.ok) {
        voiceModelWarm.value = true
        notifyApiReachable('voice-warm')
      }
    } catch {
      /* warm is best-effort; first transcribe still works with cold hint */
    }
  }

  return { voiceButtonDisabled, voiceButtonClass, voiceButtonIcon, voiceButtonText, voiceButtonTitle, voiceFeedbackText, startVoiceRecording, stopVoiceRecording, cleanupVoiceInput, warmVoiceModel, voiceModelWarm }
}
