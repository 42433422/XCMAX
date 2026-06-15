import { describe, expect, it, beforeEach } from 'vitest'
import {
  isStarredChatAutoRefreshOn,
  isProIntentExperienceOn,
  formatWorkflowHintTime,
  formatWorkflowClock,
  STAR_REFRESH_STORAGE_KEY,
  PRO_INTENT_STORAGE_KEY,
} from './coreWorkflowPrefs'

describe('coreWorkflowPrefs', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('reads starred refresh flag', () => {
    expect(isStarredChatAutoRefreshOn()).toBe(false)
    localStorage.setItem(STAR_REFRESH_STORAGE_KEY, '1')
    expect(isStarredChatAutoRefreshOn()).toBe(true)
  })

  it('reads pro intent flag', () => {
    expect(isProIntentExperienceOn()).toBe(false)
    localStorage.setItem(PRO_INTENT_STORAGE_KEY, '1')
    expect(isProIntentExperienceOn()).toBe(true)
  })

  it('formats workflow times', () => {
    const ts = new Date('2026-06-14T10:30:45').getTime()
    expect(formatWorkflowHintTime(ts)).toMatch(/\d{2}/)
    expect(formatWorkflowClock(ts)).toMatch(/10/)
  })
})
