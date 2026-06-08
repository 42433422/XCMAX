import { describe, expect, it } from 'vitest'
import { speculativeTextsMatch } from './voiceSpeculativeMatch'

describe('speculativeTextsMatch', () => {
  it('matches identical text', () => {
    expect(speculativeTextsMatch('你好世界', '你好世界')).toBe(true)
  })

  it('matches when final extends partial', () => {
    expect(speculativeTextsMatch('你好世界啊', '你好世界')).toBe(true)
  })

  it('rejects unrelated text', () => {
    expect(speculativeTextsMatch('完全不同的句子', '你好世界')).toBe(false)
  })

  it('matches when final is prefix of partial', () => {
    expect(speculativeTextsMatch('今天天气', '今天天气很好')).toBe(true)
  })
})
