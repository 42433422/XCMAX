import { describe, expect, it } from 'vitest'
import { shouldFlushVoiceUtterance } from './voiceEndpointLogic'
import { VOICE_ENDPOINT as LIVE_ENDPOINT } from './useVoiceContinuousChat'

// re-export config alignment
const EP = {
  silenceMs: LIVE_ENDPOINT.silenceMs,
  speechLevel: LIVE_ENDPOINT.speechLevel,
  partialStableMs: LIVE_ENDPOINT.partialStableMs,
  partialMinChars: LIVE_ENDPOINT.partialMinChars,
}

describe('shouldFlushVoiceUtterance', () => {
  it('waits for silence threshold before flush', () => {
    const base = {
      audioSpeaking: false,
      lastSpeechAt: 1000,
      lastAsrContentChangeAt: 1000,
      lastAsrAt: 1000,
      hadSpeech: true,
      listenPartial: '你好世界测试语句够长',
      lastSubmittedText: '',
      lastSubmittedAt: 0,
    }
    expect(shouldFlushVoiceUtterance(base, EP, 1000 + EP.silenceMs - 100)).toBe(false)
    expect(shouldFlushVoiceUtterance(base, EP, 1000 + EP.silenceMs + 50)).toBe(true)
  })

  it('rejects fragments below partialMinChars', () => {
    expect(
      shouldFlushVoiceUtterance(
        {
          audioSpeaking: false,
          lastSpeechAt: 0,
          lastAsrContentChangeAt: 1000,
          lastAsrAt: 1000,
          hadSpeech: true,
          listenPartial: '短句',
          lastSubmittedText: '',
          lastSubmittedAt: 0,
        },
        EP,
        1000 + EP.silenceMs,
      ),
    ).toBe(false)
  })
})

describe('live VOICE_ENDPOINT alignment', () => {
  it('matches useVoiceContinuousChat constants', () => {
    expect(EP.silenceMs).toBe(700)
    expect(EP.partialMinChars).toBe(6)
    expect(LIVE_ENDPOINT.serverFinalDebounceMs).toBe(280)
  })
})
