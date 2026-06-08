/** 语音断句纯逻辑（供单测与冒烟脚本对齐） */
export type VoiceEndpointConfig = {
  silenceMs: number
  speechLevel: number
  partialStableMs: number
  partialMinChars: number
}

export type VoiceCaptureSnapshot = {
  audioSpeaking: boolean
  lastSpeechAt: number
  lastAsrContentChangeAt: number
  lastAsrAt: number
  hadSpeech: boolean
  listenPartial: string
  voiceTranscript?: string
  voiceDraft?: string
  lastSubmittedText: string
  lastSubmittedAt: number
}

export function silenceIdleMs(s: VoiceCaptureSnapshot, now: number): number {
  if (s.audioSpeaking) return 0
  if (s.lastSpeechAt > 0) return now - s.lastSpeechAt
  const text =
    s.listenPartial.trim() ||
    String(s.voiceTranscript || '').trim() ||
    String(s.voiceDraft || '').trim()
  if (text && s.lastAsrContentChangeAt > 0) {
    return now - s.lastAsrContentChangeAt
  }
  const asrAnchor = s.lastAsrContentChangeAt || s.lastAsrAt
  return asrAnchor > 0 ? now - asrAnchor : 0
}

export function hasFreshVoiceCapture(s: VoiceCaptureSnapshot, text: string): boolean {
  const t = text.trim()
  if (!t) return false
  if (t !== s.lastSubmittedText) return true
  return s.lastAsrAt > s.lastSubmittedAt
}

export function shouldFlushVoiceUtterance(
  s: VoiceCaptureSnapshot,
  ep: VoiceEndpointConfig,
  now: number,
): boolean {
  if (s.audioSpeaking) return false
  if (silenceIdleMs(s, now) < ep.silenceMs - 80) return false
  const text =
    String(s.voiceTranscript || '').trim() ||
    String(s.voiceDraft || '').trim() ||
    s.listenPartial.trim()
  if (!text) return false
  if (text.length < ep.partialMinChars) return false
  if (hasFreshVoiceCapture(s, text)) return true
  if (s.lastAsrContentChangeAt > 0 || s.hadSpeech) return true
  return false
}
