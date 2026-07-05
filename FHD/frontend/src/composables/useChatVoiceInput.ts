import { ref, computed, type Ref } from 'vue'
import { apiFetch } from '@/utils/apiBase'

const MIN_RECORD_MS = 300
const MAX_RECORD_MS = 60_000
const VOICE_PREFERRED_MIME_TYPES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/ogg;codecs=opus',
  'audio/ogg',
  'audio/mp4',
  'audio/wav',
]

type VoiceState = 'idle' | 'recording' | 'transcribing' | 'error'

export interface UseChatVoiceInputDeps {
  messageInput: Ref<string>
  isLoading: Ref<boolean>
}

export function useChatVoiceInput(deps: UseChatVoiceInputDeps) {
  const { messageInput, isLoading } = deps

  const voiceState = ref<VoiceState>('idle')
  const voiceErrorText = ref('')
  const voiceElapsedSecs = ref(0)

  let voiceMediaRecorder: MediaRecorder | null = null
  let voiceMediaStream: MediaStream | null = null
  let voiceChunks: Blob[] = []
  let voiceStartedAt = 0
  let voiceMimeType = ''
  let voiceCancelRequested = false
  let voiceMaxTimer: number | null = null
  let voiceTickTimer: number | null = null
  let voiceErrorClearTimer: number | null = null

  const voiceButtonDisabled = computed(() => {
    if (voiceState.value === 'transcribing') return true
    if (isLoading.value) return true
    return false
  })

  const voiceButtonClass = computed(() => ({
    'voice-input-btn-idle': voiceState.value === 'idle',
    'voice-input-btn-recording': voiceState.value === 'recording',
    'voice-input-btn-transcribing': voiceState.value === 'transcribing',
    'voice-input-btn-error': voiceState.value === 'error',
  }))

  const voiceButtonIcon = computed(() => {
    if (voiceState.value === 'recording') return 'fa-stop-circle'
    if (voiceState.value === 'transcribing') return 'fa-spinner fa-pulse'
    if (voiceState.value === 'error') return 'fa-exclamation-circle'
    return 'fa-microphone'
  })

  const voiceButtonText = computed(() => {
    if (voiceState.value === 'recording') {
      return `松开发送 ${voiceElapsedSecs.value.toFixed(1)}s`
    }
    if (voiceState.value === 'transcribing') return '识别中...'
    if (voiceState.value === 'error') return voiceErrorText.value || '语音失败'
    return '按住说话'
  })

  const voiceButtonTitle = computed(() => {
    if (voiceState.value === 'recording') return '松开立即识别并填入输入框；移出按钮可取消本次录音'
    if (voiceState.value === 'transcribing') return '正在把语音转成文字...'
    if (voiceState.value === 'error') return voiceErrorText.value || '语音识别失败'
    return '按住这里说话，松开后会自动转写成文字填入输入框'
  })

  const pickSupportedMimeType = (): string => {
    const MR = (window as unknown as { MediaRecorder?: typeof MediaRecorder }).MediaRecorder
    if (!MR || typeof MR.isTypeSupported !== 'function') return ''
    for (const mt of VOICE_PREFERRED_MIME_TYPES) {
      try {
        if (MR.isTypeSupported(mt)) return mt
      } catch {
        /* older browsers */
      }
    }
    return ''
  }

  const setVoiceError = (msg: string) => {
    voiceErrorText.value = msg
    voiceState.value = 'error'
    if (voiceErrorClearTimer) window.clearTimeout(voiceErrorClearTimer)
    voiceErrorClearTimer = window.setTimeout(() => {
      if (voiceState.value === 'error') {
        voiceState.value = 'idle'
        voiceErrorText.value = ''
      }
      voiceErrorClearTimer = null
    }, 4000)
  }

  const resetVoiceTimers = () => {
    if (voiceMaxTimer) {
      window.clearTimeout(voiceMaxTimer)
      voiceMaxTimer = null
    }
    if (voiceTickTimer) {
      window.clearInterval(voiceTickTimer)
      voiceTickTimer = null
    }
  }

  const releaseVoiceStream = () => {
    if (voiceMediaStream) {
      try {
        voiceMediaStream.getTracks().forEach((t) => t.stop())
      } catch {
        /* ignore */
      }
      voiceMediaStream = null
    }
    voiceMediaRecorder = null
  }

  const extractMimeExtension = (mime: string): string => {
    const m = String(mime || '').toLowerCase()
    if (m.includes('webm')) return 'webm'
    if (m.includes('ogg')) return 'ogg'
    if (m.includes('mp4') || m.includes('m4a')) return 'm4a'
    if (m.includes('wav') || m.includes('wave')) return 'wav'
    return 'bin'
  }

  const submitVoiceBlob = async (blob: Blob) => {
    voiceState.value = 'transcribing'
    try {
      const ext = extractMimeExtension(blob.type || voiceMimeType)
      const form = new FormData()
      form.append('file', blob, `chat-voice.${ext}`)
      const resp = await apiFetch('/api/voice/transcribe', { method: 'POST', body: form })
      const raw = await resp.text()
      let data: { success?: boolean; detail?: string; message?: string; error?: string; data?: { text?: string } } | null = null
      try {
        data = raw ? JSON.parse(raw) : null
      } catch {
        data = null
      }
      if (!resp.ok || !data || data.success === false) {
        const detail =
          (data && (data.detail || data.message || data.error)) || raw || `HTTP ${resp.status}`
        throw new Error(String(detail))
      }
      const text = String(data?.data?.text || '').trim()
      if (!text) {
        setVoiceError('未识别到内容，请靠近麦克风再试')
        return
      }
      const existing = (messageInput.value || '').trimEnd()
      messageInput.value = existing ? `${existing} ${text}` : text
      voiceState.value = 'idle'
      voiceErrorText.value = ''
      const domInput = document.getElementById('messageInput') as HTMLTextAreaElement | null
      if (domInput) {
        domInput.focus()
        try {
          const pos = domInput.value.length
          domInput.setSelectionRange(pos, pos)
        } catch {
          /* ignore */
        }
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '语音识别失败'
      setVoiceError(msg.length > 48 ? `${msg.slice(0, 48)}...` : msg)
    }
  }

  const startVoiceRecording = async () => {
    if (voiceButtonDisabled.value) return
    if (voiceState.value === 'recording' || voiceState.value === 'transcribing') return

    if (!navigator.mediaDevices || typeof navigator.mediaDevices.getUserMedia !== 'function') {
      setVoiceError('当前浏览器不支持麦克风采集')
      return
    }
    if (typeof (window as unknown as { MediaRecorder?: unknown }).MediaRecorder === 'undefined') {
      setVoiceError('当前浏览器不支持 MediaRecorder')
      return
    }

    voiceCancelRequested = false
    voiceChunks = []
    voiceElapsedSecs.value = 0

    try {
      voiceMediaStream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (err: unknown) {
      const e = err as { name?: string; message?: string }
      const name = e?.name ? String(e.name) : ''
      if (name === 'NotAllowedError' || name === 'SecurityError') {
        setVoiceError('麦克风权限被拒绝，请在浏览器地址栏授权后重试')
      } else if (name === 'NotFoundError' || name === 'OverconstrainedError') {
        setVoiceError('未检测到可用麦克风设备')
      } else {
        setVoiceError(`获取麦克风失败：${e?.message || name || '未知错误'}`)
      }
      return
    }

    const mime = pickSupportedMimeType()
    voiceMimeType = mime
    try {
      voiceMediaRecorder = mime
        ? new MediaRecorder(voiceMediaStream, { mimeType: mime })
        : new MediaRecorder(voiceMediaStream)
    } catch (err: unknown) {
      const e = err as { message?: string }
      setVoiceError(`无法创建录音器：${e?.message || '未知错误'}`)
      releaseVoiceStream()
      return
    }

    voiceMediaRecorder.addEventListener('dataavailable', (e: BlobEvent) => {
      if (e.data && e.data.size > 0) voiceChunks.push(e.data)
    })
    voiceMediaRecorder.addEventListener('stop', () => {
      resetVoiceTimers()
      releaseVoiceStream()

      const duration = Date.now() - voiceStartedAt
      if (voiceCancelRequested) {
        if (voiceState.value === 'recording') voiceState.value = 'idle'
        voiceChunks = []
        return
      }
      if (duration < MIN_RECORD_MS) {
        setVoiceError('录音太短（<0.3s），请稍微按久一点再松开')
        voiceChunks = []
        return
      }
      const blob = new Blob(voiceChunks, { type: voiceMimeType || 'audio/webm' })
      voiceChunks = []
      if (blob.size === 0) {
        setVoiceError('未采到音频数据，请检查麦克风')
        return
      }
      void submitVoiceBlob(blob)
    })
    voiceMediaRecorder.addEventListener('error', (evt: Event) => {
      const e = evt as { error?: { message?: string } }
      const msg = e?.error?.message || '录音失败'
      setVoiceError(String(msg))
      resetVoiceTimers()
      releaseVoiceStream()
    })

    try {
      voiceMediaRecorder.start()
    } catch (err: unknown) {
      const e = err as { message?: string }
      setVoiceError(`启动录音失败：${e?.message || '未知错误'}`)
      releaseVoiceStream()
      return
    }

    voiceStartedAt = Date.now()
    voiceState.value = 'recording'
    voiceErrorText.value = ''

    voiceMaxTimer = window.setTimeout(() => {
      stopVoiceRecording(false)
    }, MAX_RECORD_MS)

    voiceTickTimer = window.setInterval(() => {
      voiceElapsedSecs.value = (Date.now() - voiceStartedAt) / 1000
    }, 100)
  }

  const stopVoiceRecording = (cancel: boolean) => {
    if (voiceState.value !== 'recording') return
    if (!voiceMediaRecorder) return

    voiceCancelRequested = cancel
    try {
      if (voiceMediaRecorder.state !== 'inactive') {
        voiceMediaRecorder.stop()
      }
    } catch {
      /* ignore */
    }
  }

  function cleanupVoiceInput() {
    resetVoiceTimers()
    if (voiceMediaRecorder && voiceMediaRecorder.state !== 'inactive') {
      try {
        voiceCancelRequested = true
        voiceMediaRecorder.stop()
      } catch {
        /* ignore */
      }
    }
    releaseVoiceStream()
    if (voiceErrorClearTimer) {
      window.clearTimeout(voiceErrorClearTimer)
      voiceErrorClearTimer = null
    }
  }

  return {
    voiceButtonDisabled,
    voiceButtonClass,
    voiceButtonIcon,
    voiceButtonText,
    voiceButtonTitle,
    startVoiceRecording,
    stopVoiceRecording,
    cleanupVoiceInput,
  }
}
