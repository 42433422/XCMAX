/** 语音链路延迟埋点（DevTools / 运维排查） */

export type VoiceLatencyMark = 'speech_end' | 'asr_final' | 'llm_first_token' | 'tts_first_audio'

const marks = new Map<VoiceLatencyMark, number>()

export function markVoiceLatency(name: VoiceLatencyMark): void {
  marks.set(name, performance.now())
  if (typeof window !== 'undefined') {
    try {
      performance.mark(`voice_${name}`)
    } catch {
      /* ignore */
    }
  }
}

export function clearVoiceLatencyMarks(): void {
  marks.clear()
}

export function reportVoiceLatencyIfComplete(): Record<string, number> | null {
  const end = marks.get('speech_end')
  const asr = marks.get('asr_final')
  const llm = marks.get('llm_first_token')
  const tts = marks.get('tts_first_audio')
  if (!end || !tts) return null
  const report: Record<string, number> = {
    speech_to_asr_ms: asr ? Math.round(asr - end) : -1,
    speech_to_llm_ms: llm ? Math.round(llm - end) : -1,
    speech_to_tts_ms: Math.round(tts - end),
  }
  if (import.meta.env?.DEV) {
    console.info('[voice_latency]', report)
  }
  return report
}
