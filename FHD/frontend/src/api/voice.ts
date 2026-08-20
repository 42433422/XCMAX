import { api, primeCsrfCookie } from './core'
import { readCsrfTokenFromCookie, shouldAttachCsrfHeader } from '@/utils/csrfCookie'
import { buildFullApiUrl } from './core'
import type { ApiResponse } from '@/types/api'

/**
 * 语音 API：封装 /api/voice/transcribe（纯 ASR）与 /api/voice/command（端到端指令）。
 *
 * 与 chat.ts/auth.ts 同风格：FormData 上传走 api.post（自动跳过 JSON Content-Type），
 * 错误经 ApiError 抛出。voice.ts 不依赖 chat store，可在任意 composable 中复用。
 */

/** ASR 转写返回的工具元数据（与后端 _run_transcribe 输出对齐） */
export interface VoiceTranscribeData {
  text: string
  language?: string
  audio_seconds?: number
  elapsed_ms?: number
  bytes?: number
}

/**
 * 语音指令未执行原因代码（与后端 voice_command.reason 字段对齐）
 * - asr_empty: ASR 无文本
 * - no_intent: 未识别到意图
 * - low_confidence: 置信度低于阈值
 * - high_risk_needs_confirmation: 高风险意图需二次确认
 * - negated: 否定式意图
 * - auto_execute_disabled: auto_execute=false
 * - execution_failed: 执行抛异常
 * - executed: 执行成功
 */
export type VoiceCommandReason =
  | 'asr_empty'
  | 'no_intent'
  | 'low_confidence'
  | 'high_risk_needs_confirmation'
  | 'negated'
  | 'auto_execute_disabled'
  | 'execution_failed'
  | 'executed'
  | 'no_tool_key'
  | string

/** /api/voice/command 返回的 data 字段形状 */
export interface VoiceCommandData {
  text: string
  intent: string | null
  primary_intent?: string | null
  confidence: number
  executed: boolean
  result: {
    response?: string
    toolCall?: unknown
    data?: unknown
    error?: string
  } | null
  reason: VoiceCommandReason
  session_id?: string
  slots?: Record<string, unknown>
  intent_hints?: string[]
  is_negated?: boolean
  is_high_risk?: boolean
  elapsed_ms_asr?: number
}

/** 普通文件名后缀推断（与 useChatVoiceInput 中的 extractMimeExtension 同义） */
function guessAudioExtension(blob: Blob): string {
  const mime = String(blob.type || '').toLowerCase()
  if (mime.includes('webm')) return 'webm'
  if (mime.includes('ogg')) return 'ogg'
  if (mime.includes('mp4') || mime.includes('m4a')) return 'm4a'
  if (mime.includes('wav') || mime.includes('wave')) return 'wav'
  return 'bin'
}

export const voiceApi = {
  /**
   * 调用 /api/voice/transcribe：仅做 ASR，返回纯文本（用户仍需手动点发送）。
   * 保留与 useChatVoiceInput.submitVoiceBlob 原行为一致的接口形态。
   */
  async transcribeVoice(file: Blob, options: { language?: string; timeoutMs?: number } = {}): Promise<ApiResponse<VoiceTranscribeData>> {
    await primeCsrfCookie()
    const form = new FormData()
    form.append('file', file, `chat-voice.${guessAudioExtension(file)}`)
    if (options.language) form.append('language', options.language)
    return api.post<ApiResponse<VoiceTranscribeData>>('/api/voice/transcribe', form, {
      timeoutMs: options.timeoutMs ?? 60_000,
    })
  },

  /**
   * 调用 /api/voice/command：ASR → 意图识别 → 可选自动执行，端到端语音指令。
   *
   * 与 transcribeVoice 的差异：
   * - 后端额外做意图识别并按 auto_execute + 置信度 + 风险等级决定是否直接执行工具
   * - executed=true 时 result 已包含工具执行结果，前端可直接渲染到对话区
   * - executed=false 时 text 仍可填入输入框由用户手动确认
   *
   * 注意：此端点走原生 fetch（与 chat.sendChatStream 同风格），因为需要显式控制
   * multipart FormData 的 CSRF 头注入，避免 api.post 在某些代理下重复 Content-Type。
   */
  async voiceCommand(
    file: Blob,
    options: {
      autoExecute?: boolean
      sessionId?: string
      language?: string
      timeoutMs?: number
    } = {},
  ): Promise<ApiResponse<VoiceCommandData>> {
    await primeCsrfCookie()
    const { autoExecute = false, sessionId = '', language, timeoutMs = 60_000 } = options

    const form = new FormData()
    form.append('file', file, `chat-voice.${guessAudioExtension(file)}`)
    form.append('auto_execute', String(autoExecute === true))
    if (sessionId) form.append('session_id', sessionId)
    if (language) form.append('language', language)

    const headers: Record<string, string> = {}
    if (shouldAttachCsrfHeader('POST', headers)) {
      const tok = readCsrfTokenFromCookie()
      if (tok) headers['X-CSRF-Token'] = tok
    }

    const controller = new AbortController()
    const timer = typeof timeoutMs === 'number' && timeoutMs > 0 ? window.setTimeout(() => controller.abort(), timeoutMs) : null

    try {
      const resp = await fetch(buildFullApiUrl('/api/voice/command'), {
        method: 'POST',
        body: form,
        credentials: 'include',
        headers,
        signal: controller.signal,
      })
      const raw = await resp.text()
      let payload: ApiResponse<VoiceCommandData> | null = null
      try {
        payload = raw ? (JSON.parse(raw) as ApiResponse<VoiceCommandData>) : null
      } catch {
        payload = null
      }
      if (!resp.ok || !payload || payload.success === false) {
        const detail =
          (payload && (payload as unknown as { detail?: string; message?: string }).detail) ||
          (payload && (payload as unknown as { message?: string }).message) ||
          raw ||
          `HTTP ${resp.status}`
        throw new Error(String(detail))
      }
      return payload
    } finally {
      if (timer) window.clearTimeout(timer)
    }
  },
}

export default voiceApi
