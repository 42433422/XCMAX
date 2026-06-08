import { describe, expect, it } from 'vitest'
import { VOICE_ENDPOINT, VOICE_PHONE_ENDPOINT } from './useVoiceContinuousChat'

describe('VOICE_ENDPOINT', () => {
  it('uses conservative silence and partial stable thresholds', () => {
    expect(VOICE_ENDPOINT.silenceMs).toBe(700)
    expect(VOICE_ENDPOINT.partialStableMs).toBe(1100)
    expect(VOICE_ENDPOINT.partialMinChars).toBe(6)
    expect(VOICE_ENDPOINT.serverFinalDebounceMs).toBe(280)
  })

  it('phone endpoint is faster than default for call-like latency', () => {
    expect(VOICE_PHONE_ENDPOINT.silenceMs).toBeLessThan(VOICE_ENDPOINT.silenceMs)
    expect(VOICE_PHONE_ENDPOINT.partialStableS2sMs).toBeLessThan(VOICE_ENDPOINT.partialStableS2sMs)
  })
})
