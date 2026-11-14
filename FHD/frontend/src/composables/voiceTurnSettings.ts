/**
 * 语音判停设置：Smart Turn 阈值与「语气词/半句话」最长挂起时间。
 *
 * 阈值和挂起上限原先写死，环境一变就过严（一直不发）或过松（半句话就发）。
 * 这里做成可持久化设置，并按麦克风噪声自动微调。
 */
import { ref } from 'vue'

export interface VoiceTurnSettings {
  /** Smart Turn 判停阈值（0.2–0.9）；越低越容易认为这句话已经说完。 */
  smartTurnThreshold: number
  /** 语气词/未说完内容的最长挂起时间（毫秒）。 */
  pendingMaxMs: number
  /** 按麦克风噪声自适应调整阈值与挂起上限。 */
  adaptive: boolean
}

const STORAGE_KEY = 'xcagi_voice_turn_settings'
const DEFAULT_NOISE_FLOOR = 0.012

export const VOICE_TURN_DEFAULTS: VoiceTurnSettings = {
  smartTurnThreshold: 0.5,
  pendingMaxMs: 7_000,
  adaptive: true,
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value))
}

export function normalizeVoiceTurnSettings(raw: Partial<VoiceTurnSettings> | null | undefined): VoiceTurnSettings {
  const threshold = Number(raw?.smartTurnThreshold)
  const pending = Number(raw?.pendingMaxMs)
  return {
    smartTurnThreshold: Number.isFinite(threshold)
      ? clamp(threshold, 0.2, 0.9)
      : VOICE_TURN_DEFAULTS.smartTurnThreshold,
    pendingMaxMs: Number.isFinite(pending)
      ? clamp(pending, 2_000, 20_000)
      : VOICE_TURN_DEFAULTS.pendingMaxMs,
    adaptive: raw?.adaptive !== false,
  }
}

function load(): VoiceTurnSettings {
  try {
    return normalizeVoiceTurnSettings(JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null'))
  } catch {
    return { ...VOICE_TURN_DEFAULTS }
  }
}

export const voiceTurnSettings = ref<VoiceTurnSettings>(load())

export function saveVoiceTurnSettings(patch: Partial<VoiceTurnSettings>): void {
  voiceTurnSettings.value = normalizeVoiceTurnSettings({ ...voiceTurnSettings.value, ...patch })
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(voiceTurnSettings.value))
  } catch {
    // 本机存储不可用时仍保留本次会话内的设置
  }
}

/** 噪声越大，判停越容易通过（避免在嘈杂环境里一直等不到“说完了”）。 */
export function effectiveTurnThreshold(noiseFloor: number): number {
  const settings = voiceTurnSettings.value
  if (!settings.adaptive) return settings.smartTurnThreshold
  const noiseRatio = clamp((noiseFloor - DEFAULT_NOISE_FLOOR) / 0.03, 0, 1)
  return clamp(settings.smartTurnThreshold - noiseRatio * 0.08, 0.3, 0.9)
}

/** 噪声越大，挂起上限越短（避免环境噪声把一轮对话无限期拖住）。 */
export function effectivePendingMaxMs(noiseFloor: number): number {
  const settings = voiceTurnSettings.value
  if (!settings.adaptive) return settings.pendingMaxMs
  const noiseRatio = clamp((noiseFloor - DEFAULT_NOISE_FLOOR) / 0.03, 0, 1)
  return Math.round(clamp(settings.pendingMaxMs - noiseRatio * 1_500, 2_000, settings.pendingMaxMs))
}
