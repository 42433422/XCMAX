import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// Mock offlineTts to avoid loading heavy dependencies
vi.mock('./offlineTts', () => ({
  playOfflinePcm: vi.fn(),
  synthesizeOffline: vi.fn(),
  ensureOfflineReady: vi.fn(),
  isOfflineReady: vi.fn(() => false),
  isOfflineLoading: vi.fn(() => false),
  getOfflineProgress: vi.fn(() => 0),
  stopOffline: vi.fn(),
}))

vi.mock('./apiBase', () => ({
  apiFetch: vi.fn(),
  getApiBase: vi.fn(() => ''),
}))

vi.mock('./csrfCookie', () => ({
  readCsrfTokenFromCookie: vi.fn(() => ''),
  shouldAttachCsrfHeader: vi.fn(() => false),
}))

import {
  cleanTextForSpeech,
  getEngineMode,
  setEngineMode,
  getOnlineVoiceId,
  setOnlineVoiceId,
  isBannerDismissed,
  dismissBanner,
  getSpeechRate,
  setSpeechRate,
  pickBestChineseVoice,
  hasYunxiOrXiaoxiaoAvailable,
  hasAnyChineseLocalVoice,
  getTtsStatus,
  onTtsStatusChange,
  type TtsEngineMode,
} from './tts'

describe('tts utility functions', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  describe('cleanTextForSpeech', () => {
    it('removes Chinese punctuation', () => {
      expect(cleanTextForSpeech('你好，世界！')).toBe('你好 世界')
    })

    it('removes English punctuation', () => {
      expect(cleanTextForSpeech('Hello, World!')).toBe('Hello World')
    })

    it('normalizes whitespace', () => {
      expect(cleanTextForSpeech('a   b')).toBe('a b')
    })

    it('normalizes newlines to spaces', () => {
      expect(cleanTextForSpeech('line1\nline2')).toBe('line1 line2')
    })

    it('handles empty string', () => {
      expect(cleanTextForSpeech('')).toBe('')
    })

    it('handles string with only punctuation', () => {
      expect(cleanTextForSpeech('，。！？')).toBe('')
    })

    it('handles mixed punctuation and text', () => {
      expect(cleanTextForSpeech('test；test：test')).toBe('test test test')
    })

    it('handles special punctuation marks', () => {
      expect(cleanTextForSpeech('a【b】c')).toBe('a b c')
    })
  })

  describe('getEngineMode / setEngineMode', () => {
    it('returns online by default', () => {
      expect(getEngineMode()).toBe('online')
    })

    it('returns system when set', () => {
      setEngineMode('system')
      expect(getEngineMode()).toBe('system')
    })

    it('returns offline when set', () => {
      setEngineMode('offline')
      expect(getEngineMode()).toBe('offline')
    })

    it('returns online when set', () => {
      setEngineMode('online')
      expect(getEngineMode()).toBe('online')
    })

    it('returns online for unknown mode', () => {
      localStorage.setItem('xcagi_tts_engine', 'unknown')
      expect(getEngineMode()).toBe('online')
    })

    it('returns online when localStorage throws', () => {
      const spy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new Error('access denied')
      })
      expect(getEngineMode()).toBe('online')
      spy.mockRestore()
    })
  })

  describe('getOnlineVoiceId / setOnlineVoiceId', () => {
    it('returns default voice id when not set', () => {
      expect(getOnlineVoiceId()).toBe('zh-CN-XiaoxiaoNeural')
    })

    it('returns custom voice id when set', () => {
      setOnlineVoiceId('zh-CN-YunxiNeural')
      expect(getOnlineVoiceId()).toBe('zh-CN-YunxiNeural')
    })

    it('clears voice id when empty string passed', () => {
      setOnlineVoiceId('zh-CN-YunxiNeural')
      setOnlineVoiceId('')
      expect(getOnlineVoiceId()).toBe('zh-CN-XiaoxiaoNeural')
    })

    it('clears voice id when whitespace-only string passed', () => {
      setOnlineVoiceId('zh-CN-YunxiNeural')
      setOnlineVoiceId('   ')
      expect(getOnlineVoiceId()).toBe('zh-CN-XiaoxiaoNeural')
    })

    it('returns default when localStorage throws', () => {
      const spy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new Error('denied')
      })
      expect(getOnlineVoiceId()).toBe('zh-CN-XiaoxiaoNeural')
      spy.mockRestore()
    })
  })

  describe('isBannerDismissed / dismissBanner', () => {
    it('returns false by default', () => {
      expect(isBannerDismissed()).toBe(false)
    })

    it('returns true after dismissBanner', () => {
      dismissBanner()
      expect(isBannerDismissed()).toBe(true)
    })

    it('returns false when localStorage throws', () => {
      const spy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new Error('denied')
      })
      expect(isBannerDismissed()).toBe(false)
      spy.mockRestore()
    })
  })

  describe('getSpeechRate / setSpeechRate', () => {
    it('returns default rate 1.15 when not set', () => {
      expect(getSpeechRate()).toBe(1.15)
    })

    it('returns custom rate when set', () => {
      setSpeechRate(1.5)
      expect(getSpeechRate()).toBe(1.5)
    })

    it('clamps rate to minimum 0.5', () => {
      setSpeechRate(0.1)
      expect(getSpeechRate()).toBe(0.5)
    })

    it('clamps rate to maximum 2.0', () => {
      setSpeechRate(3.0)
      expect(getSpeechRate()).toBe(2.0)
    })

    it('returns default when localStorage throws', () => {
      const spy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new Error('denied')
      })
      expect(getSpeechRate()).toBe(1.15)
      spy.mockRestore()
    })

    it('returns default for invalid stored value', () => {
      localStorage.setItem('xcagi_tts_rate', 'invalid')
      expect(getSpeechRate()).toBe(1.15)
    })

    it('returns default for out-of-range stored value', () => {
      localStorage.setItem('xcagi_tts_rate', '0.1')
      expect(getSpeechRate()).toBe(1.15)
    })
  })

  describe('pickBestChineseVoice', () => {
    it('returns null for empty list', () => {
      expect(pickBestChineseVoice([])).toBeNull()
    })

    it('returns null for undefined list', () => {
      expect(pickBestChineseVoice(undefined)).toBeNull()
    })

    it('returns null when no Chinese voices', () => {
      const voices = [{ name: 'English', lang: 'en-US', localService: true, default: false }]
      expect(pickBestChineseVoice(voices as SpeechSynthesisVoice[])).toBeNull()
    })

    it('returns a Chinese voice when available', () => {
      const voices = [
        { name: 'Yunxi', lang: 'zh-CN', localService: true, default: false },
      ]
      const result = pickBestChineseVoice(voices as SpeechSynthesisVoice[])
      expect(result).not.toBeNull()
      expect(result?.name).toBe('Yunxi')
    })

    it('prefers zh-CN over zh-TW', () => {
      const voices = [
        { name: 'Voice1', lang: 'zh-TW', localService: true, default: false },
        { name: 'Voice2', lang: 'zh-CN', localService: true, default: false },
      ]
      const result = pickBestChineseVoice(voices as SpeechSynthesisVoice[])
      expect(result?.lang).toBe('zh-CN')
    })

    it('prefers local service voices', () => {
      const voices = [
        { name: 'Remote', lang: 'zh-CN', localService: false, default: false },
        { name: 'Local', lang: 'zh-CN', localService: true, default: false },
      ]
      const result = pickBestChineseVoice(voices as SpeechSynthesisVoice[])
      expect(result?.name).toBe('Local')
    })

    it('prefers Yunxi voice', () => {
      const voices = [
        { name: 'Huihui', lang: 'zh-CN', localService: true, default: false },
        { name: 'Yunxi', lang: 'zh-CN', localService: true, default: false },
      ]
      const result = pickBestChineseVoice(voices as SpeechSynthesisVoice[])
      expect(result?.name).toBe('Yunxi')
    })
  })

  describe('hasYunxiOrXiaoxiaoAvailable', () => {
    it('returns false for empty cache', () => {
      expect(hasYunxiOrXiaoxiaoAvailable()).toBe(false)
    })
  })

  describe('hasAnyChineseLocalVoice', () => {
    it('returns false for empty cache', () => {
      expect(hasAnyChineseLocalVoice()).toBe(false)
    })
  })

  describe('getTtsStatus', () => {
    it('returns status object with expected shape', () => {
      const status = getTtsStatus()
      expect(status).toHaveProperty('engineMode')
      expect(status).toHaveProperty('effectiveEngine')
      expect(status).toHaveProperty('onlineVoiceId')
      expect(status).toHaveProperty('systemVoice')
      expect(status).toHaveProperty('yunxiAvailable')
      expect(status).toHaveProperty('neuralAvailable')
      expect(status).toHaveProperty('anyChineseLocal')
      expect(status).toHaveProperty('offlineReady')
      expect(status).toHaveProperty('offlineLoading')
      expect(status).toHaveProperty('offlineProgress')
      expect(status).toHaveProperty('bannerDismissed')
    })

    it('returns online effectiveEngine when mode is online', () => {
      setEngineMode('online')
      const status = getTtsStatus()
      expect(status.effectiveEngine).toBe('online')
    })

    it('returns system effectiveEngine when mode is system', () => {
      setEngineMode('system')
      const status = getTtsStatus()
      expect(status.effectiveEngine).toBe('system')
    })

    it('returns system effectiveEngine when mode is offline but not ready', () => {
      setEngineMode('offline')
      const status = getTtsStatus()
      expect(status.effectiveEngine).toBe('system')
    })

    it('returns onlineVoiceId from getOnlineVoiceId', () => {
      setOnlineVoiceId('zh-CN-YunxiNeural')
      const status = getTtsStatus()
      expect(status.onlineVoiceId).toBe('zh-CN-YunxiNeural')
    })
  })

  describe('onTtsStatusChange', () => {
    it('registers and returns unsubscribe function', () => {
      const cb = vi.fn()
      const unsub = onTtsStatusChange(cb)
      expect(typeof unsub).toBe('function')
      unsub()
    })

    it('calls listener when status changes via setEngineMode', () => {
      const cb = vi.fn()
      onTtsStatusChange(cb)
      setEngineMode('system')
      expect(cb).toHaveBeenCalled()
    })

    it('does not call listener after unsubscribe', () => {
      const cb = vi.fn()
      const unsub = onTtsStatusChange(cb)
      unsub()
      setEngineMode('offline')
      expect(cb).not.toHaveBeenCalled()
    })

    it('listener errors are swallowed', () => {
      const cb = vi.fn(() => {
        throw new Error('listener error')
      })
      onTtsStatusChange(cb)
      expect(() => setEngineMode('system')).not.toThrow()
    })
  })
})
