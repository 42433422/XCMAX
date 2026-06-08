import { beforeEach, describe, expect, it } from 'vitest'
import { defaultPersonalSettings, loadPersonalSettings, savePersonalSettings } from './personalSettings'

describe('personalSettings', () => {
  beforeEach(() => {
    if (typeof localStorage !== 'undefined') localStorage.clear()
  })

  it('returns defaults when nothing saved', () => {
    const v = loadPersonalSettings()
    expect(v.theme).toBe('dark')
    expect(v.fontPx).toBe(15)
    expect(v.memory).toBe('')
    expect(v.suggestions.length).toBeGreaterThan(0)
    expect(v.ttsEngine).toBe('edge-online')
    expect(v.ttsEdgeVoice).toBe('zh-CN-XiaoxiaoNeural')
    expect(v.ttsVoiceName).toBe('')
    expect(v.ttsRate).toBe(1)
  })

  it('saves and reloads custom values', () => {
    const next = defaultPersonalSettings()
    next.theme = 'light'
    next.fontPx = 18
    next.memory = 'I prefer concise answers'
    next.suggestions = ['line a', 'line b']
    savePersonalSettings(next)

    const got = loadPersonalSettings()
    expect(got.theme).toBe('light')
    expect(got.fontPx).toBe(18)
    expect(got.memory).toBe('I prefer concise answers')
    expect(got.suggestions).toEqual(['line a', 'line b'])
  })

  it('clamps fontPx to safe range', () => {
    savePersonalSettings({ ...defaultPersonalSettings(), fontPx: 99 })
    expect(loadPersonalSettings().fontPx).toBeLessThanOrEqual(20)
    savePersonalSettings({ ...defaultPersonalSettings(), fontPx: 1 })
    expect(loadPersonalSettings().fontPx).toBeGreaterThanOrEqual(13)
  })

  it('clamps ttsRate to safe range', () => {
    savePersonalSettings({ ...defaultPersonalSettings(), ttsRate: 9 })
    expect(loadPersonalSettings().ttsRate).toBeLessThanOrEqual(1.6)
    savePersonalSettings({ ...defaultPersonalSettings(), ttsRate: 0.1 })
    expect(loadPersonalSettings().ttsRate).toBeGreaterThanOrEqual(0.6)
  })
})
