import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/utils/xcagiStorageKeys', () => ({
  XCAGI_AI_DEVELOPER_MODE_KEY: 'xcagi_ai_developer_mode',
  XCAGI_AI_ELEVATED_TOKEN_KEY: 'xcagi_ai_elevated_token',
}))

import { getAiTierHttpHeaders } from './aiTierHeaders'

describe('aiTierHeaders', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('returns p1 tier by default', () => {
    const headers = getAiTierHttpHeaders()
    expect(headers).toEqual({ 'X-XCAGI-AI-Tier': 'p1' })
  })

  it('returns p1 tier when developer mode is off', () => {
    localStorage.setItem('xcagi_ai_developer_mode', '0')
    localStorage.setItem('xcagi_ai_elevated_token', 'my-token')
    const headers = getAiTierHttpHeaders()
    expect(headers).toEqual({ 'X-XCAGI-AI-Tier': 'p1' })
  })

  it('returns p1 tier when token is empty', () => {
    localStorage.setItem('xcagi_ai_developer_mode', '1')
    localStorage.setItem('xcagi_ai_elevated_token', '')
    const headers = getAiTierHttpHeaders()
    expect(headers).toEqual({ 'X-XCAGI-AI-Tier': 'p1' })
  })

  it('returns p2 tier when developer mode is on and token is set', () => {
    localStorage.setItem('xcagi_ai_developer_mode', '1')
    localStorage.setItem('xcagi_ai_elevated_token', 'my-secret-token')
    const headers = getAiTierHttpHeaders()
    expect(headers).toEqual({
      'X-XCAGI-AI-Tier': 'p2',
      'X-XCAGI-Elevated-Token': 'my-secret-token',
    })
  })

  it('trims whitespace from token', () => {
    localStorage.setItem('xcagi_ai_developer_mode', '1')
    localStorage.setItem('xcagi_ai_elevated_token', '  spaced-token  ')
    const headers = getAiTierHttpHeaders()
    expect(headers['X-XCAGI-Elevated-Token']).toBe('spaced-token')
  })

  it('handles localStorage error gracefully', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('Access denied')
    })
    const headers = getAiTierHttpHeaders()
    expect(headers).toEqual({ 'X-XCAGI-AI-Tier': 'p1' })
    vi.restoreAllMocks()
  })
})
