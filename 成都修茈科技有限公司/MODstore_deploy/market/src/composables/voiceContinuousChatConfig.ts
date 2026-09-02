// 语音端点配置：桌面/移动/电话式判停参数与设备自适应（自 useVoiceContinuousChat 原样迁移）。
import type { Ref } from 'vue'
import type { useSpeechRecognition } from './useSpeechRecognition'
import { isIOSVoiceDevice, isMobileVoiceDevice } from './voiceDevice'

export const VOICE_ENDPOINT = {
  /** 说完后的静音窗口：桌面约 700ms；过短易切碎句 */
  silenceMs: 700,
  speechLevel: 0.012,
  /** 推测式 LLM 需 partial 稳定更久，避免半句就「嗯，你说」 */
  partialStableMs: 1100,
  /** S2S：partial 稳定后发 utterance_start（早于 speculative） */
  partialStableS2sMs: 500,
  /** 中文短句常 <10 字；过低易半句误发，6 字可覆盖「听得到吗」类问句 */
  partialMinChars: 6,
  /** FunASR offline 段确认后的提交防抖 */
  serverFinalDebounceMs: 280,
} as const

/** unified / s2s 电话式：更短判停、更早开答（对标豆包动态判停） */
export const VOICE_PHONE_ENDPOINT = {
  silenceMs: 520,
  speechLevel: 0.011,
  partialStableMs: 950,
  partialStableS2sMs: 380,
  partialMinChars: 4,
  serverFinalDebounceMs: 220,
} as const

export function voiceEndpointForDevice() {
  if (!isMobileVoiceDevice()) return VOICE_ENDPOINT
  const ios = isIOSVoiceDevice()
  return {
    silenceMs: ios ? 900 : 1000,
    speechLevel: ios ? 0.028 : 0.024,
    partialStableMs: ios ? 1200 : 1300,
    partialStableS2sMs: ios ? 550 : 600,
    partialMinChars: VOICE_ENDPOINT.partialMinChars,
    serverFinalDebounceMs: VOICE_ENDPOINT.serverFinalDebounceMs,
  } as const
}

let activeEndpoint = voiceEndpointForDevice()

export function refreshVoiceEndpoint() {
  activeEndpoint = voiceEndpointForDevice()
}

export interface VoiceContinuousChatDeps {
  asr: ReturnType<typeof useSpeechRecognition>
  isAsrReady?: () => boolean
  autoSend: Ref<boolean>
  voiceState: Ref<string>
  voiceChatPhase: Ref<string>
  isVoiceTargetActive: () => boolean
  setVoiceTarget: () => void
  clearVoiceTarget: () => void
  beforeStartListening?: () => void
  onUtteranceReady: (text: string, ctx: { speculativePartial: string | null }) => Promise<void>
  onSpeculativeStart: (partialText: string) => void
  onSpeculativeCancel: () => void
  onBargeIn: () => void
  /** TTS 正在合成/播放时为 true */
  isTtsPlaying?: () => boolean
  /** TTS 播放中检测到用户说话；返回 true 表示已触发打断 */
  onAsrDuringTts?: (level: number) => boolean
  canSpeculate: (partialText: string) => boolean
  isChatBusy: () => boolean
  getAsrBackendId?: () => string
  /** FunASR：用户停说时立即通知服务端（is_speaking:false） */
  signalAsrEndOfSpeech?: () => void
  /** unified/s2s：partial 稳定后提前开 LLM（不等 offline） */
  onS2SPartialStable?: (text: string, turnId: string) => void
  /** unified/s2s：offline 到达后 finalize / 纠错 */
  onS2SUtteranceFinalize?: (text: string, turnId: string) => void
  /** unified 或 s2s 电话式管线 */
  voiceUsePhonePipeline?: () => boolean
  /** @deprecated 使用 voiceUsePhonePipeline */
  voiceUseS2S?: () => boolean
  /** 电话式：更短判停与更早 provisional */
  usePhoneLatency?: () => boolean
}

export function createVoiceEndpointResolver(d: Pick<VoiceContinuousChatDeps, 'usePhoneLatency'>) {
  return function endpoint() {
    if (d.usePhoneLatency?.()) {
      const base = activeEndpoint
      return {
        ...base,
        silenceMs: Math.min(base.silenceMs, VOICE_PHONE_ENDPOINT.silenceMs),
        partialStableS2sMs: Math.min(base.partialStableS2sMs ?? VOICE_ENDPOINT.partialStableS2sMs, VOICE_PHONE_ENDPOINT.partialStableS2sMs),
        partialMinChars: Math.min(base.partialMinChars, VOICE_PHONE_ENDPOINT.partialMinChars),
        serverFinalDebounceMs: Math.min(
          base.serverFinalDebounceMs ?? VOICE_ENDPOINT.serverFinalDebounceMs,
          VOICE_PHONE_ENDPOINT.serverFinalDebounceMs,
        ),
        speechLevel: Math.min(base.speechLevel, VOICE_PHONE_ENDPOINT.speechLevel),
      }
    }
    return activeEndpoint
  }
}

export type VoiceEndpointResolver = ReturnType<typeof createVoiceEndpointResolver>
