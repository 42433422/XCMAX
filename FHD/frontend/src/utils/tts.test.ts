import { describe, expect, it, beforeEach } from 'vitest'
import {
  getEngineMode,
  setEngineMode,
  getOnlineVoiceId,
  setOnlineVoiceId,
  isBannerDismissed,
  dismissBanner,
  getSpeechRate,
  setSpeechRate,
  cleanTextForSpeech,
  onTtsStatusChange,
} from './tts'

describe('tts preferences', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('defaults engine mode to online', () => {
    expect(getEngineMode()).toBe('online')
  })

  it('persists engine mode', () => {
    setEngineMode('system')
    expect(getEngineMode()).toBe('system')
    setEngineMode('offline')
    expect(getEngineMode()).toBe('offline')
  })

  it('manages online voice id', () => {
    expect(getOnlineVoiceId()).toContain('Neural')
    setOnlineVoiceId('zh-CN-YunxiNeural')
    expect(getOnlineVoiceId()).toBe('zh-CN-YunxiNeural')
  })

  it('manages banner dismissed flag', () => {
    expect(isBannerDismissed()).toBe(false)
    dismissBanner()
    expect(isBannerDismissed()).toBe(true)
  })

  it('clamps speech rate', () => {
    expect(getSpeechRate()).toBeGreaterThan(1)
    setSpeechRate(3)
    expect(getSpeechRate()).toBe(2)
    setSpeechRate(0.1)
    expect(getSpeechRate()).toBe(0.5)
  })

  it('cleans text for speech', () => {
    expect(cleanTextForSpeech('你好，世界！\n测试')).toBe('你好 世界 测试')
  })

  it('notifies status listeners', () => {
    let called = 0
    const off = onTtsStatusChange(() => {
      called += 1
    })
    setEngineMode('system')
    expect(called).toBeGreaterThan(0)
    off()
  })
})
