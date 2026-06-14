import { describe, expect, it } from 'vitest'
import { getTutorialTtsWarmupTexts } from './tutorial'

describe('tutorial store helpers', () => {
  it('returns warmup texts for pro mode', () => {
    const texts = getTutorialTtsWarmupTexts(true)
    expect(Array.isArray(texts)).toBe(true)
  })

  it('returns warmup texts for basic mode', () => {
    const texts = getTutorialTtsWarmupTexts(false)
    expect(Array.isArray(texts)).toBe(true)
  })
})
