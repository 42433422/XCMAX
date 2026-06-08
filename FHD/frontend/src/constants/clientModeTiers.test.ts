import { describe, expect, it } from 'vitest'
import {
  CLIENT_MODE_TIERS_UI_ENABLED,
  PRO_INTENT_EXPERIENCE_KEY,
  isClientModeTiersUiEnabled,
  resetClientModeTierLocalState,
} from './clientModeTiers'

describe('clientModeTiers', () => {
  it('keeps tier UI off until server-driven levels ship', () => {
    expect(CLIENT_MODE_TIERS_UI_ENABLED).toBe(false)
    expect(isClientModeTiersUiEnabled()).toBe(false)
  })

  it('resets pro intent experience preference', () => {
    localStorage.setItem(PRO_INTENT_EXPERIENCE_KEY, '1')
    resetClientModeTierLocalState()
    expect(localStorage.getItem(PRO_INTENT_EXPERIENCE_KEY)).toBe('0')
  })
})
