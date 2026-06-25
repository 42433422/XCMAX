import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const { mockGetApiBase, mockCsrf, mockOffline, mockTypeGuards } = vi.hoisted(() => ({
  mockGetApiBase: vi.fn(() => 'http://localhost:5100'),
  mockCsrf: {
    readCsrfTokenFromCookie: vi.fn(() => null),
    shouldAttachCsrfHeader: vi.fn(() => false),
  },
  mockOffline: {
    playOfflinePcm: vi.fn(() => Promise.resolve()),
    synthesizeOffline: vi.fn(() => Promise.resolve({ audio: new Int16Array(0), samplingRate: 16000 })),
    ensureOfflineReady: vi.fn(() => Promise.resolve()),
    isOfflineReady: vi.fn(() => false),
    isOfflineLoading: vi.fn(() => false),
    getOfflineProgress: vi.fn(() => 0),
    stopOffline: vi.fn(),
  },
  mockTypeGuards: {
    asRecord: vi.fn((v: unknown) => (v && typeof v === 'object' ? v : {})),
    asArray: vi.fn((v: unknown) => (Array.isArray(v) ? v : [])),
    asString: vi.fn((v: unknown) => (typeof v === 'string' ? v : '')),
    asBoolean: vi.fn((v: unknown) => typeof v === 'boolean' ? v : false),
    asDisposable: vi.fn((v: unknown) => v),
  },
}))

vi.mock('./apiBase', () => ({ getApiBase: mockGetApiBase }))
vi.mock('./csrfCookie', () => mockCsrf)
vi.mock('./offlineTts', () => mockOffline)
vi.mock('@/utils/typeGuards', () => mockTypeGuards)

// Mock SpeechSynthesisUtterance for jsdom
class MockSpeechSynthesisUtterance {
  text: string
  lang = 'zh-CN'
  rate = 1
  pitch = 1
  voice: SpeechSynthesisVoice | null = null
  volume = 1
  onend: (() => void) | null = null
  onerror: ((e: unknown) => void) | null = null
  onstart: (() => void) | null = null
  onpause: (() => void) | null = null
  onresume: (() => void) | null = null
  onmark: (() => void) | null = null
  onboundary: (() => void) | null = null
  constructor(text: string) {
    this.text = text
  }
}
vi.stubGlobal('SpeechSynthesisUtterance', MockSpeechSynthesisUtterance)

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
  pickBestChineseVoice,
  onTtsStatusChange,
  getTtsStatus,
  createChineseUtterance,
  stopSpeaking,
  speakText,
  hasYunxiOrXiaoxiaoAvailable,
  hasAnyChineseLocalVoice,
} from './tts'

function makeVoice(overrides: Partial<SpeechSynthesisVoice> = {}): SpeechSynthesisVoice {
  return {
    name: 'Yunxi',
    lang: 'zh-CN',
    voiceURI: 'yunxi',
    default: false,
    localService: true,
    voiceSynthesis: {} as unknown,
    ...overrides,
  } as SpeechSynthesisVoice
}

describe('tts utility functions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    mockOffline.isOfflineReady.mockReturnValue(false)
    mockOffline.isOfflineLoading.mockReturnValue(false)
    mockOffline.getOfflineProgress.mockReturnValue(0)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('getEngineMode / setEngineMode', () => {
    it('returns online by default', () => {
      expect(getEngineMode()).toBe('online')
    })

    it('returns stored mode when valid', () => {
      localStorage.setItem('xcagi_tts_engine', 'system')
      expect(getEngineMode()).toBe('system')
    })

    it('returns offline mode when stored', () => {
      localStorage.setItem('xcagi_tts_engine', 'offline')
      expect(getEngineMode()).toBe('offline')
    })

    it('falls back to online for invalid value', () => {
      localStorage.setItem('xcagi_tts_engine', 'invalid-mode')
      expect(getEngineMode()).toBe('online')
    })

    it('falls back to online for auto value (legacy)', () => {
      localStorage.setItem('xcagi_tts_engine', 'auto')
      expect(getEngineMode()).toBe('online')
    })

    it('setEngineMode persists mode to localStorage', () => {
      setEngineMode('system')
      expect(localStorage.getItem('xcagi_tts_engine')).toBe('system')
    })

    it('setEngineMode overwrites previous value', () => {
      setEngineMode('system')
      setEngineMode('offline')
      expect(localStorage.getItem('xcagi_tts_engine')).toBe('offline')
    })

    it('setEngineMode triggers status change listeners', () => {
      const cb = vi.fn()
      const unsub = onTtsStatusChange(cb)
      setEngineMode('system')
      expect(cb).toHaveBeenCalled()
      unsub()
    })
  })

  describe('getOnlineVoiceId / setOnlineVoiceId', () => {
    it('returns default voice id when not set', () => {
      expect(getOnlineVoiceId()).toBe('zh-CN-XiaoxiaoNeural')
    })

    it('returns stored voice id', () => {
      localStorage.setItem('xcagi_tts_online_voice', 'zh-CN-YunxiNeural')
      expect(getOnlineVoiceId()).toBe('zh-CN-YunxiNeural')
    })

    it('returns default when stored value is empty', () => {
      localStorage.setItem('xcagi_tts_online_voice', '')
      expect(getOnlineVoiceId()).toBe('zh-CN-XiaoxiaoNeural')
    })

    it('returns default when stored value is whitespace', () => {
      localStorage.setItem('xcagi_tts_online_voice', '   ')
      expect(getOnlineVoiceId()).toBe('zh-CN-XiaoxiaoNeural')
    })

    it('setOnlineVoiceId persists value', () => {
      setOnlineVoiceId('zh-CN-YunxiNeural')
      expect(localStorage.getItem('xcagi_tts_online_voice')).toBe('zh-CN-YunxiNeural')
    })

    it('setOnlineVoiceId removes value when empty', () => {
      localStorage.setItem('xcagi_tts_online_voice', 'old')
      setOnlineVoiceId('')
      expect(localStorage.getItem('xcagi_tts_online_voice')).toBeNull()
    })

    it('setOnlineVoiceId trims whitespace', () => {
      setOnlineVoiceId('  zh-CN-YunxiNeural  ')
      expect(localStorage.getItem('xcagi_tts_online_voice')).toBe('zh-CN-YunxiNeural')
    })

    it('setOnlineVoiceId triggers status change listeners', () => {
      const cb = vi.fn()
      const unsub = onTtsStatusChange(cb)
      setOnlineVoiceId('zh-CN-YunxiNeural')
      expect(cb).toHaveBeenCalled()
      unsub()
    })
  })

  describe('isBannerDismissed / dismissBanner', () => {
    it('returns false by default', () => {
      expect(isBannerDismissed()).toBe(false)
    })

    it('returns true when dismissed flag set', () => {
      localStorage.setItem('xcagi_tts_banner_dismissed', '1')
      expect(isBannerDismissed()).toBe(true)
    })

    it('returns false for non-1 value', () => {
      localStorage.setItem('xcagi_tts_banner_dismissed', '0')
      expect(isBannerDismissed()).toBe(false)
    })

    it('dismissBanner sets flag to 1', () => {
      dismissBanner()
      expect(localStorage.getItem('xcagi_tts_banner_dismissed')).toBe('1')
    })

    it('dismissBanner triggers status change listeners', () => {
      const cb = vi.fn()
      const unsub = onTtsStatusChange(cb)
      dismissBanner()
      expect(cb).toHaveBeenCalled()
      unsub()
    })
  })

  describe('getSpeechRate / setSpeechRate', () => {
    it('returns default rate 1.15 when not set', () => {
      expect(getSpeechRate()).toBe(1.15)
    })

    it('returns stored rate when valid', () => {
      localStorage.setItem('xcagi_tts_rate', '1.5')
      expect(getSpeechRate()).toBe(1.5)
    })

    it('returns default when stored value is invalid', () => {
      localStorage.setItem('xcagi_tts_rate', 'not-a-number')
      expect(getSpeechRate()).toBe(1.15)
    })

    it('returns default when stored value is NaN', () => {
      localStorage.setItem('xcagi_tts_rate', 'NaN')
      expect(getSpeechRate()).toBe(1.15)
    })

    it('returns default when value below 0.5', () => {
      localStorage.setItem('xcagi_tts_rate', '0.3')
      expect(getSpeechRate()).toBe(1.15)
    })

    it('returns default when value above 2.0', () => {
      localStorage.setItem('xcagi_tts_rate', '2.5')
      expect(getSpeechRate()).toBe(1.15)
    })

    it('returns 0.5 boundary value', () => {
      localStorage.setItem('xcagi_tts_rate', '0.5')
      expect(getSpeechRate()).toBe(0.5)
    })

    it('returns 2.0 boundary value', () => {
      localStorage.setItem('xcagi_tts_rate', '2.0')
      expect(getSpeechRate()).toBe(2.0)
    })

    it('setSpeechRate clamps to minimum 0.5', () => {
      setSpeechRate(0.1)
      expect(localStorage.getItem('xcagi_tts_rate')).toBe('0.5')
    })

    it('setSpeechRate clamps to maximum 2.0', () => {
      setSpeechRate(5.0)
      expect(localStorage.getItem('xcagi_tts_rate')).toBe('2')
    })

    it('setSpeechRate stores valid value within range', () => {
      setSpeechRate(1.5)
      expect(localStorage.getItem('xcagi_tts_rate')).toBe('1.5')
    })

    it('setSpeechRate triggers status change listeners', () => {
      const cb = vi.fn()
      const unsub = onTtsStatusChange(cb)
      setSpeechRate(1.5)
      expect(cb).toHaveBeenCalled()
      unsub()
    })
  })

  describe('cleanTextForSpeech', () => {
    it('returns empty string for empty input', () => {
      expect(cleanTextForSpeech('')).toBe('')
    })

    it('returns trimmed string for plain text', () => {
      expect(cleanTextForSpeech('hello world')).toBe('hello world')
    })

    it('removes Chinese punctuation', () => {
      expect(cleanTextForSpeech('你好，世界！')).toBe('你好 世界')
    })

    it('removes English punctuation', () => {
      expect(cleanTextForSpeech('hello, world!')).toBe('hello world')
    })

    it('replaces multiple spaces with single space', () => {
      expect(cleanTextForSpeech('hello    world')).toBe('hello world')
    })

    it('replaces newlines with space', () => {
      expect(cleanTextForSpeech('hello\nworld')).toBe('hello world')
    })

    it('replaces multiple newlines with single space', () => {
      expect(cleanTextForSpeech('hello\n\n\nworld')).toBe('hello world')
    })

    it('removes semicolons and colons', () => {
      expect(cleanTextForSpeech('a;b:c')).toBe('a b c')
    })

    it('removes brackets and quotes', () => {
      expect(cleanTextForSpeech('【test】「quote」')).toBe('test quote')
    })

    it('trims leading and trailing whitespace', () => {
      expect(cleanTextForSpeech('  hello  ')).toBe('hello')
    })

    it('handles mixed punctuation and whitespace', () => {
      expect(cleanTextForSpeech('你好，世界！\nHello, world!')).toBe('你好 世界 Hello world')
    })

    it('handles dashes and ellipsis', () => {
      expect(cleanTextForSpeech('wait— or... maybe')).toBe('wait or maybe')
    })
  })

  describe('pickBestChineseVoice', () => {
    it('returns null for empty list', () => {
      expect(pickBestChineseVoice([])).toBeNull()
    })

    it('returns null for undefined list', () => {
      expect(pickBestChineseVoice(undefined)).toBeNull()
    })

    it('returns preferred voice when set and matches', () => {
      localStorage.setItem('xcagi_tts_voice', 'MyVoice')
      const voices = [makeVoice({ name: 'MyVoice', lang: 'zh-CN' }), makeVoice({ name: 'Yunxi', lang: 'zh-CN' })]
      const result = pickBestChineseVoice(voices)
      expect(result?.name).toBe('MyVoice')
    })

    it('falls back to scoring when preferred not found', () => {
      localStorage.setItem('xcagi_tts_voice', 'NonExistent')
      const voices = [makeVoice({ name: 'Yunxi', lang: 'zh-CN' })]
      const result = pickBestChineseVoice(voices)
      expect(result?.name).toBe('Yunxi')
    })

    it('scores zh-CN highest', () => {
      const voices = [
        makeVoice({ name: 'Voice1', lang: 'zh-TW' }),
        makeVoice({ name: 'Voice2', lang: 'zh-CN' }),
      ]
      const result = pickBestChineseVoice(voices)
      expect(result?.lang).toBe('zh-CN')
    })

    it('scores zh-SG higher than zh-TW', () => {
      const voices = [
        makeVoice({ name: 'Voice1', lang: 'zh-TW' }),
        makeVoice({ name: 'Voice2', lang: 'zh-SG' }),
      ]
      const result = pickBestChineseVoice(voices)
      expect(result?.lang).toBe('zh-SG')
    })

    it('returns null when no Chinese voices', () => {
      const voices = [makeVoice({ name: 'EnglishVoice', lang: 'en-US' })]
      expect(pickBestChineseVoice(voices)).toBeNull()
    })

    it('prefers Yunxi voice (bonus score)', () => {
      const voices = [
        makeVoice({ name: 'NormalVoice', lang: 'zh-CN' }),
        makeVoice({ name: 'Yunxi', lang: 'zh-CN' }),
      ]
      const result = pickBestChineseVoice(voices)
      expect(result?.name).toBe('Yunxi')
    })

    it('prefers local service voices', () => {
      const voices = [
        makeVoice({ name: 'Voice1', lang: 'zh-CN', localService: false }),
        makeVoice({ name: 'Voice2', lang: 'zh-CN', localService: true }),
      ]
      // Both have same name bonus (none), but localService adds 50
      const result = pickBestChineseVoice(voices)
      expect(result?.localService).toBe(true)
    })

    it('handles zh_cn underscore format', () => {
      const voices = [makeVoice({ name: 'TestVoice', lang: 'zh_cn' })]
      const result = pickBestChineseVoice(voices)
      expect(result).not.toBeNull()
    })

    it('handles zh-HK variant', () => {
      const voices = [makeVoice({ name: 'TestVoice', lang: 'zh-HK' })]
      const result = pickBestChineseVoice(voices)
      expect(result).not.toBeNull()
    })

    it('handles generic zh prefix', () => {
      const voices = [makeVoice({ name: 'TestVoice', lang: 'zh' })]
      const result = pickBestChineseVoice(voices)
      expect(result).not.toBeNull()
    })

    it('gives neural keyword bonus', () => {
      const voices = [
        makeVoice({ name: 'PlainVoice', lang: 'zh-CN' }),
        makeVoice({ name: 'XiaoxiaoNeural', lang: 'zh-CN' }),
      ]
      const result = pickBestChineseVoice(voices)
      expect(result?.name).toBe('XiaoxiaoNeural')
    })
  })

  describe('onTtsStatusChange', () => {
    it('returns unsubscribe function', () => {
      const unsub = onTtsStatusChange(() => {})
      expect(typeof unsub).toBe('function')
      unsub()
    })

    it('calls listener on status change', () => {
      const cb = vi.fn()
      const unsub = onTtsStatusChange(cb)
      setEngineMode('system')
      expect(cb).toHaveBeenCalledTimes(1)
      unsub()
    })

    it('does not call listener after unsubscribe', () => {
      const cb = vi.fn()
      const unsub = onTtsStatusChange(cb)
      unsub()
      setEngineMode('system')
      expect(cb).not.toHaveBeenCalled()
    })

    it('supports multiple listeners', () => {
      const cb1 = vi.fn()
      const cb2 = vi.fn()
      const unsub1 = onTtsStatusChange(cb1)
      const unsub2 = onTtsStatusChange(cb2)
      setEngineMode('offline')
      expect(cb1).toHaveBeenCalledTimes(1)
      expect(cb2).toHaveBeenCalledTimes(1)
      unsub1()
      unsub2()
    })

    it('listener errors do not break other listeners', () => {
      const cb1 = vi.fn(() => { throw new Error('boom') })
      const cb2 = vi.fn()
      const unsub1 = onTtsStatusChange(cb1)
      const unsub2 = onTtsStatusChange(cb2)
      setEngineMode('system')
      expect(cb2).toHaveBeenCalledTimes(1)
      unsub1()
      unsub2()
    })
  })

  describe('getTtsStatus', () => {
    it('returns status object with engineMode', () => {
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

    it('returns online effective engine when mode is online', () => {
      setEngineMode('online')
      const status = getTtsStatus()
      expect(status.effectiveEngine).toBe('online')
    })

    it('returns system effective engine when mode is system', () => {
      setEngineMode('system')
      const status = getTtsStatus()
      expect(status.effectiveEngine).toBe('system')
    })

    it('returns system effective engine when mode is offline but not ready', () => {
      setEngineMode('offline')
      mockOffline.isOfflineReady.mockReturnValue(false)
      const status = getTtsStatus()
      expect(status.effectiveEngine).toBe('system')
    })

    it('returns offline effective engine when mode is offline and ready', () => {
      setEngineMode('offline')
      mockOffline.isOfflineReady.mockReturnValue(true)
      const status = getTtsStatus()
      expect(status.effectiveEngine).toBe('offline')
    })

    it('returns onlineVoiceId from storage', () => {
      setOnlineVoiceId('zh-CN-YunxiNeural')
      const status = getTtsStatus()
      expect(status.onlineVoiceId).toBe('zh-CN-YunxiNeural')
    })

    it('returns bannerDismissed from storage', () => {
      dismissBanner()
      const status = getTtsStatus()
      expect(status.bannerDismissed).toBe(true)
    })

    it('returns offlineReady from offline module', () => {
      mockOffline.isOfflineReady.mockReturnValue(true)
      const status = getTtsStatus()
      expect(status.offlineReady).toBe(true)
    })

    it('returns offlineLoading from offline module', () => {
      mockOffline.isOfflineLoading.mockReturnValue(true)
      const status = getTtsStatus()
      expect(status.offlineLoading).toBe(true)
    })

    it('returns offlineProgress from offline module', () => {
      mockOffline.getOfflineProgress.mockReturnValue(0.5)
      const status = getTtsStatus()
      expect(status.offlineProgress).toBe(0.5)
    })
  })

  describe('createChineseUtterance', () => {
    beforeEach(() => {
      // Mock speechSynthesis on window
      Object.defineProperty(window, 'speechSynthesis', {
        value: {
          getVoices: vi.fn(() => []),
          speak: vi.fn(),
          cancel: vi.fn(),
          speaking: false,
          pending: false,
          addEventListener: vi.fn(),
          removeEventListener: vi.fn(),
        },
        configurable: true,
        writable: true,
      })
    })

    it('creates an utterance with the given text', () => {
      const u = createChineseUtterance('hello')
      expect(u.text).toBe('hello')
    })

    it('sets lang to zh-CN by default', () => {
      const u = createChineseUtterance('test')
      expect(u.lang).toBe('zh-CN')
    })

    it('sets rate from getSpeechRate', () => {
      setSpeechRate(1.5)
      const u = createChineseUtterance('test')
      expect(u.rate).toBe(1.5)
    })

    it('sets pitch to 1', () => {
      const u = createChineseUtterance('test')
      expect(u.pitch).toBe(1)
    })

    it('handles empty text', () => {
      const u = createChineseUtterance('')
      expect(u.text).toBe('')
    })
  })

  describe('stopSpeaking', () => {
    it('does not throw when speechSynthesis not available', () => {
      expect(() => stopSpeaking()).not.toThrow()
    })

    it('calls cancel when speechSynthesis is speaking', () => {
      const cancelSpy = vi.fn()
      Object.defineProperty(window, 'speechSynthesis', {
        value: {
          getVoices: vi.fn(() => []),
          speak: vi.fn(),
          cancel: cancelSpy,
          speaking: true,
          pending: false,
          addEventListener: vi.fn(),
          removeEventListener: vi.fn(),
        },
        configurable: true,
        writable: true,
      })
      stopSpeaking()
      expect(cancelSpy).toHaveBeenCalled()
    })

    it('calls cancel when speechSynthesis is pending', () => {
      const cancelSpy = vi.fn()
      Object.defineProperty(window, 'speechSynthesis', {
        value: {
          getVoices: vi.fn(() => []),
          speak: vi.fn(),
          cancel: cancelSpy,
          speaking: false,
          pending: true,
          addEventListener: vi.fn(),
          removeEventListener: vi.fn(),
        },
        configurable: true,
        writable: true,
      })
      stopSpeaking()
      expect(cancelSpy).toHaveBeenCalled()
    })

    it('does not call cancel when speechSynthesis is idle', () => {
      const cancelSpy = vi.fn()
      Object.defineProperty(window, 'speechSynthesis', {
        value: {
          getVoices: vi.fn(() => []),
          speak: vi.fn(),
          cancel: cancelSpy,
          speaking: false,
          pending: false,
          addEventListener: vi.fn(),
          removeEventListener: vi.fn(),
        },
        configurable: true,
        writable: true,
      })
      stopSpeaking()
      expect(cancelSpy).not.toHaveBeenCalled()
    })

    it('calls stopOffline', () => {
      stopSpeaking()
      expect(mockOffline.stopOffline).toHaveBeenCalled()
    })
  })

  describe('speakText', () => {
    it('calls onEnd immediately for empty text', async () => {
      const onEnd = vi.fn()
      await speakText('', { onEnd })
      expect(onEnd).toHaveBeenCalled()
    })

    it('calls onEnd immediately for whitespace-only text', async () => {
      const onEnd = vi.fn()
      await speakText('   ', { onEnd })
      expect(onEnd).toHaveBeenCalled()
    })

    it('uses online engine when mode is online', async () => {
      setEngineMode('online')
      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ success: true, data: { audioBase64: 'data:audio/wav;base64,mock' } }),
      } as Response)
      const audioPlaySpy = vi.fn().mockResolvedValue(undefined)
      const audioEl = {
        play: audioPlaySpy,
        onended: null as null | (() => void),
        onerror: null as null | (() => void),
        src: '',
      }
      vi.spyOn(globalThis, 'Audio').mockImplementation(() => audioEl as unknown as HTMLAudioElement)

      const promise = speakText('hello')
      // Simulate audio ended
      setTimeout(() => audioEl.onended?.(), 0)
      await promise

      expect(fetchSpy).toHaveBeenCalled()
      fetchSpy.mockRestore()
      vi.spyOn(globalThis, 'Audio').mockRestore()
    })

    it('online engine falls back to system TTS on error', async () => {
      setEngineMode('online')
      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('network'))
      const speakSpy = vi.fn((u: { onend: (() => void) | null }) => {
        setTimeout(() => u.onend?.(), 0)
      })
      Object.defineProperty(window, 'speechSynthesis', {
        value: {
          getVoices: vi.fn(() => []),
          speak: speakSpy,
          cancel: vi.fn(),
          speaking: false,
          pending: false,
          addEventListener: vi.fn(),
          removeEventListener: vi.fn(),
        },
        configurable: true,
        writable: true,
      })

      await speakText('hello')
      // Should have fallen back to browser TTS
      expect(speakSpy).toHaveBeenCalled()
      fetchSpy.mockRestore()
    })

    it('uses system engine when mode is system', async () => {
      setEngineMode('system')
      const speakSpy = vi.fn((u: { onend: (() => void) | null }) => {
        setTimeout(() => u.onend?.(), 0)
      })
      Object.defineProperty(window, 'speechSynthesis', {
        value: {
          getVoices: vi.fn(() => []),
          speak: speakSpy,
          cancel: vi.fn(),
          speaking: false,
          pending: false,
          addEventListener: vi.fn(),
          removeEventListener: vi.fn(),
        },
        configurable: true,
        writable: true,
      })

      await speakText('hello')
      expect(speakSpy).toHaveBeenCalled()
    })

    it('calls onError when online fails and no offline fallback', async () => {
      setEngineMode('online')
      vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('network'))
      mockOffline.isOfflineReady.mockReturnValue(false)
      const onError = vi.fn()
      const speakSpy = vi.fn((u: { onend: (() => void) | null }) => {
        setTimeout(() => u.onend?.(), 0)
      })
      Object.defineProperty(window, 'speechSynthesis', {
        value: {
          getVoices: vi.fn(() => []),
          speak: speakSpy,
          cancel: vi.fn(),
          speaking: false,
          pending: false,
          addEventListener: vi.fn(),
          removeEventListener: vi.fn(),
        },
        configurable: true,
        writable: true,
      })

      await speakText('hello', { onError })
      expect(onError).toHaveBeenCalled()
      vi.spyOn(globalThis, 'fetch').mockRestore()
    })
  })

  describe('hasYunxiOrXiaoxiaoAvailable', () => {
    it('returns false when no voices cached', () => {
      expect(hasYunxiOrXiaoxiaoAvailable()).toBe(false)
    })
  })

  describe('hasAnyChineseLocalVoice', () => {
    it('returns false when no voices cached', () => {
      expect(hasAnyChineseLocalVoice()).toBe(false)
    })
  })
})
