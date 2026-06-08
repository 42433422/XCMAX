/** 语音打断：停 TTS、取消 LLM、恢复聆听 */

export type VoiceBargeInTargets = {
  stopS2s: () => void
  stopCascadeTts: () => void
  abortLlmStream: () => void
  setIdle: () => void
}

import { isMobileVoiceDevice } from './voiceDevice'

const BARGE_LEVEL_MULTIPLIER_DESKTOP = 2.8
const BARGE_LEVEL_MULTIPLIER_MOBILE = 3.4

export function shouldTriggerVoiceBargeIn(
  level: number,
  speechLevel: number,
  ttsPlaying: boolean,
): boolean {
  const mul = isMobileVoiceDevice() ? BARGE_LEVEL_MULTIPLIER_MOBILE : BARGE_LEVEL_MULTIPLIER_DESKTOP
  if (!ttsPlaying) return level >= speechLevel
  return level >= speechLevel * mul
}

export function executeVoiceBargeIn(targets: VoiceBargeInTargets): void {
  targets.stopS2s()
  targets.stopCascadeTts()
  targets.abortLlmStream()
  targets.setIdle()
}
