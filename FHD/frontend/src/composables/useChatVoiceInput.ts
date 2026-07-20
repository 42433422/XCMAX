import { ref, computed, type Ref } from 'vue'
import { apiFetch } from '@/utils/apiBase'
import { voiceApi, type VoiceCommandData } from '@/api/voice'

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
  /** 可选：会话 ID（ref 或 getter），用于 /api/voice/command 的 session_id 字段 */
  sessionId?: Ref<string> | (() => string)
  /** 可选：voiceCommand 自动执行成功时的回调，由调用方把结果注入对话区 */
  onVoiceCommandExecuted?: (data: VoiceCommandData) => void
  /** 可选：voiceCommand 未执行但识别到意图时的回调，调用方可显示"已识别意图"提示 */
  onVoiceIntentRecognized?: (data: VoiceCommandData) => void
}

export function useChatVoiceInput(deps: UseChatVoiceInputDeps) {
  const { messageInput, isLoading } = deps
  const onVoiceCommandExecuted = deps.onVoiceCommandExecuted
  const onVoiceIntentRecognized = deps.onVoiceIntentRecognized

  const voiceState = ref<VoiceState>('idle')
  const voiceErrorText = ref('')
  const voiceElapsedSecs = ref(0)
  /**
   * 语音指令模式（长按触发）：true 时按钮文案显示"语音指令模式·松开执行 Ns"，
   * 松开后调用 /api/voice/command 时 auto_execute=true。
   * 由调用方（如 ChatView.vue 的长按计时器）通过 setVoiceCommandMode 设置。
   */
  const voiceCommandMode = ref(false)

  let voiceMediaRecorder: MediaRecorder | null = null
  let voiceMediaStream: MediaStream | null = null
  let voiceChunks: Blob[] = []
  let voiceStartedAt = 0
  let voiceMimeType = ''
  let voiceCancelRequested = false
  /** 录音停止时携带的 auto_execute 标记，由 stopVoiceRecording 传入 */
  let voicePendingAutoExecute = false
  let voiceMaxTimer: number | null = null
  let voiceTickTimer: number | null = null
  let voiceErrorClearTimer: number | null = null

  /** 读取 sessionId（兼容 Ref 和 getter 两种形式） */
  const readSessionId = (): string => {
    const s = deps.sessionId
    if (!s) return ''
    if (typeof s === 'function') return s() || ''
    return s.value || ''
  }

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
    'voice-input-btn-command': voiceCommandMode.value,
  }))

  const voiceButtonIcon = computed(() => {
    if (voiceState.value === 'recording') return 'fa-stop-circle'
    if (voiceState.value === 'transcribing') return 'fa-spinner fa-pulse'
    if (voiceState.value === 'error') return 'fa-exclamation-circle'
    return 'fa-microphone'
  })

  const voiceButtonText = computed(() => {
    if (voiceState.value === 'recording') {
      const secs = voiceElapsedSecs.value.toFixed(1)
      return voiceCommandMode.value
        ? `语音指令模式·松开执行 ${secs}s`
        : `松开发送 ${secs}s`
    }
    if (voiceState.value === 'transcribing') {
      return voiceCommandMode.value ? '执行中...' : '识别中...'
    }
    if (voiceState.value === 'error') return voiceErrorText.value || '语音失败'
    return '按住说话'
  })

  const voiceButtonTitle = computed(() => {
    if (voiceState.value === 'recording') {
      return voiceCommandMode.value
        ? '语音指令模式：松开后会自动 ASR → 意图识别 → 直接执行低风险工具；高风险操作仍需二次确认'
        : '松开立即识别并填入输入框；移出按钮可取消本次录音'
    }
    if (voiceState.value === 'transcribing') {
      return voiceCommandMode.value ? '正在执行语音指令...' : '正在把语音转成文字...'
    }
    if (voiceState.value === 'error') return voiceErrorText.value || '语音识别失败'
    return '按住这里说话，松开后会自动转写成文字填入输入框；长按 1.5 秒以上切换为语音指令模式'
  })

  /** 独立于按钮文案的可访问反馈，避免识别失败后用户只看到按钮恢复原状。 */
  const voiceFeedbackText = computed(() => (
    voiceState.value === 'error' ? (voiceErrorText.value || '语音识别失败，请重试') : ''
  ))

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
        setVoiceError('未识别到语音，请靠近麦克风后重试')
        return
      }
      const existing = (messageInput.value || '').trimEnd()
      messageInput.value = existing ? `${existing} ${text}` : text
      voiceState.value = 'idle'
      voiceErrorText.value = ''
      focusMessageInputEnd()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '语音识别失败'
      setVoiceError(msg.length > 48 ? `${msg.slice(0, 48)}...` : msg)
    }
  }

  /** 把光标聚焦到 #messageInput 末尾，供 ASR 完成后立即编辑使用 */
  const focusMessageInputEnd = () => {
    const domInput = document.getElementById('messageInput') as HTMLTextAreaElement | null
    if (!domInput) return
    domInput.focus()
    try {
      const pos = domInput.value.length
      domInput.setSelectionRange(pos, pos)
    } catch {
      /* ignore */
    }
  }

  /**
   * 端到端语音指令：调用 /api/voice/command。
   *
   * - autoExecute=false（默认）：与 submitVoiceBlob 行为一致，把 text 填入输入框；
   *   额外通过 onVoiceIntentRecognized 回调告知调用方"已识别意图"，前端可显示提示
   * - autoExecute=true：后端按置信度 + 风险等级决定是否直接执行工具
   *   - executed=true：通过 onVoiceCommandExecuted 回调把结果交给调用方注入对话区
   *   - executed=false：仍把 text 填入输入框（高风险/低置信度/否定式等场景，由用户手动确认）
   */
  const submitVoiceCommand = async (blob: Blob, autoExecute: boolean = false) => {
    voiceState.value = 'transcribing'
    try {
      const resp = await voiceApi.voiceCommand(blob, {
        autoExecute,
        sessionId: readSessionId(),
      })
      const data = resp?.data
      if (!data) {
        setVoiceError('语音指令响应异常')
        return
      }
      const text = String(data.text || '').trim()
      if (!text) {
        setVoiceError('未识别到语音，请靠近麦克风后重试')
        return
      }

      if (data.executed) {
        // 工具已直接执行：把结果交给调用方注入对话区，不污染输入框
        try {
          onVoiceCommandExecuted?.(data)
        } catch (cbErr: unknown) {
          // 调用方回调失败不应阻塞状态恢复
          // eslint-disable-next-line no-console
          console.warn('[useChatVoiceInput] onVoiceCommandExecuted failed:', cbErr)
        }
        voiceState.value = 'idle'
        voiceErrorText.value = ''
        return
      }

      // 未执行：填入输入框供用户手动确认（保持与 submitVoiceBlob 一致的体验）
      const existing = (messageInput.value || '').trimEnd()
      messageInput.value = existing ? `${existing} ${text}` : text
      voiceState.value = 'idle'
      voiceErrorText.value = ''
      focusMessageInputEnd()

      // 仅在识别到意图且未执行时回调（让调用方显示"已识别意图：XX，可点击发送"等提示）
      if (
        data.intent &&
        data.reason !== 'asr_empty' &&
        data.reason !== 'auto_execute_disabled'
      ) {
        try {
          onVoiceIntentRecognized?.(data)
        } catch (cbErr: unknown) {
          // eslint-disable-next-line no-console
          console.warn('[useChatVoiceInput] onVoiceIntentRecognized failed:', cbErr)
        }
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '语音指令失败'
      setVoiceError(msg.length > 48 ? `${msg.slice(0, 48)}...` : msg)
    }
  }

  /**
   * 设置语音指令模式（长按 1.5s 触发）；录音中切换会即时影响按钮文案。
   * 同时同步更新 voicePendingAutoExecute，使 MAX_RECORD_MS 安全超时仍能保留长按判定。
   */
  const setVoiceCommandMode = (enabled: boolean) => {
    voiceCommandMode.value = !!enabled
    voicePendingAutoExecute = !!enabled
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
      // 录音结束时捕获本次的 auto_execute 标记，并复位指令模式（下次录音需重新长按触发）
      const autoExec = voicePendingAutoExecute
      voicePendingAutoExecute = false
      voiceCommandMode.value = false

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
      // 始终走 /api/voice/command：autoExecute=false 时行为与 /transcribe 等价（仅填入输入框），
      // autoExecute=true 时由后端按置信度+风险等级决定是否直接执行工具。
      void submitVoiceCommand(blob, autoExec)
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

  /**
   * 停止录音。
   *
   * @param cancel true=取消本次录音（不识别、不发送）；false=提交（识别并执行/填入输入框）
   * @param autoExecute 可选：覆盖语音指令模式。若不传则保留 setVoiceCommandMode 设定的当前值，
   *                    便于 MAX_RECORD_MS 安全超时仍能正确传递长按判定。
   */
  const stopVoiceRecording = (cancel: boolean, autoExecute?: boolean) => {
    if (voiceState.value !== 'recording') return
    if (!voiceMediaRecorder) return

    voiceCancelRequested = cancel
    if (typeof autoExecute === 'boolean') {
      voicePendingAutoExecute = autoExecute
    }
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
    voiceCommandMode.value = false
    voicePendingAutoExecute = false
  }

  return {
    voiceButtonDisabled,
    voiceButtonClass,
    voiceButtonIcon,
    voiceButtonText,
    voiceButtonTitle,
    voiceFeedbackText,
    voiceCommandMode,
    startVoiceRecording,
    stopVoiceRecording,
    setVoiceCommandMode,
    submitVoiceCommand,
    cleanupVoiceInput,
  }
}
