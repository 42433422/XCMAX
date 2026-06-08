import { describe, expect, it } from 'vitest'
import { normalizeVoiceAsrText } from './normalizeVoiceAsrText'

describe('normalizeVoiceAsrText', () => {
  it('fixes streaming dialogue homophones', () => {
    expect(normalizeVoiceAsrText('现在这个流失对话有很多问题')).toBe(
      '现在这个流式对话有很多问题',
    )
    expect(normalizeVoiceAsrText('个流市对')).toBe('个流式对话')
  })
})
