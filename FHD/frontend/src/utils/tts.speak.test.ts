import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const mockApiFetch = vi.hoisted(() => vi.fn())
const mockReadCsrfTokenFromCookie = vi.hoisted(() => vi.fn(() => 'csrf-token'))

vi.mock('./offlineTts', () => ({
  synthesizeOffline: vi.fn().mockResolvedValue({ audio: new Float32Array([0, 0]), samplingRate: 16000 }),
  playOfflinePcm: vi.fn().mockResolvedValue(undefined),
  ensureOfflineReady: vi.fn().mockResolvedValue(undefined),
  isOfflineReady: vi.fn(() => false),
  isOfflineLoading: vi.fn(() => false),
  getOfflineProgress: vi.fn(() => 0),
  stopOffline: vi.fn(),
}))

vi.mock('./apiBase', () => ({
  apiFetch: mockApiFetch,
}))

vi.mock('./csrfCookie', () => ({
  readCsrfTokenFromCookie: mockReadCsrfTokenFromCookie,
}))

class MockUtterance {
  text = ''
  lang = ''
  rate = 1
  pitch = 1
  voice: SpeechSynthesisVoice | null = null
  onend: (() => void) | null = null
  onerror: ((e: unknown) => void) | null = null
  constructor(text: string) {
    this.text = text
  }
}

function installSpeechMocks() {
  // @ts-expect-error test global
  globalThis.SpeechSynthesisUtterance = MockUtterance
  Object.defineProperty(window, 'speechSynthesis', {
    configurable: true,
    value: {
      speak: vi.fn((u: MockUtterance) => {
        queueMicrotask(() => u.onend?.())
      }),
      cancel: vi.fn(),
      getVoices: () => [{ name: 'Microsoft Yunxi', lang: 'zh-CN', localService: true, default: false }],
      speaking: false,
      pending: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    },
  })
}

import {
  speakText,
  stopSpeaking,
  getTtsStatus,
  pickBestChineseVoice,
  createChineseUtterance,
  ensureVoicesLoaded,
  hasYunxiOrXiaoxiaoAvailable,
  hasAnyChineseLocalVoice,
  startOfflineDownload,
  preloadOfflineTts,
  setEngineMode,
} from './tts'

describe('tts speak branches', () => {
  beforeEach(() => {
    mockApiFetch.mockReset()
    mockReadCsrfTokenFromCookie.mockReset()
    mockReadCsrfTokenFromCookie.mockReturnValue('csrf-token')
    localStorage.clear()
    setEngineMode('system')
    installSpeechMocks()
    vi.clearAllMocks()
  })

  afterEach(() => {
    stopSpeaking()
  })

  it('speakText resolves immediately for empty text', async () => {
    const onEnd = vi.fn()
    await speakText('  ', { onEnd })
    expect(onEnd).toHaveBeenCalled()
  })

  it('speakText uses browser TTS in system mode', async () => {
    const onEnd = vi.fn()
    await speakText('你好', { onEnd })
    expect(onEnd).toHaveBeenCalled()
  })

  it('speakText online mode falls back to browser on fetch failure', async () => {
    setEngineMode('online')
    mockApiFetch.mockRejectedValue(new Error('network'))
    const onError = vi.fn()
    await speakText('测试在线回退', { onError })
    expect(onError).toHaveBeenCalled()
  })

  it('speakText online mode plays audio on success', async () => {
    setEngineMode('online')
    mockApiFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        success: true,
        data: { audioBase64: 'data:audio/mp3;base64,AAAA' },
      }),
    })

    class MockAudio {
      onended: (() => void) | null = null
      onerror: (() => void) | null = null
      src = ''
      play = vi.fn().mockImplementation(async () => {
        this.onended?.()
      })
      pause = vi.fn()
    }
    vi.stubGlobal('Audio', MockAudio)

    const onEnd = vi.fn()
    await speakText('在线播放', { onEnd })
    expect(onEnd).toHaveBeenCalled()
    expect(mockApiFetch).toHaveBeenCalledWith('/api/tts', expect.objectContaining({ method: 'POST' }))
  })

  it('speakText online mode primes csrf cookie before posting when missing', async () => {
    setEngineMode('online')
    mockReadCsrfTokenFromCookie.mockReturnValueOnce('').mockReturnValue('csrf-token')
    mockApiFetch
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ success: true }) })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          success: true,
          data: { audioBase64: 'data:audio/mp3;base64,AAAA' },
        }),
      })

    class MockAudio {
      onended: (() => void) | null = null
      onerror: (() => void) | null = null
      src = ''
      play = vi.fn().mockImplementation(async () => {
        this.onended?.()
      })
      pause = vi.fn()
    }
    vi.stubGlobal('Audio', MockAudio)

    await speakText('冷启动在线朗读')
    expect(mockApiFetch.mock.calls[0]?.[0]).toBe('/api/health')
    expect(mockApiFetch.mock.calls[1]?.[0]).toBe('/api/tts')
  })

  it('speakText offline mode synthesizes offline', async () => {
    const offline = await import('./offlineTts')
    vi.mocked(offline.isOfflineReady).mockReturnValue(true)
    setEngineMode('offline')
    const onEnd = vi.fn()
    await speakText('离线朗读', { onEnd })
    expect(offline.synthesizeOffline).toHaveBeenCalled()
    expect(onEnd).toHaveBeenCalled()
  })

  it('stopSpeaking cancels active synthesis', () => {
    Object.defineProperty(window, 'speechSynthesis', {
      configurable: true,
      value: {
        speak: vi.fn(),
        cancel: vi.fn(),
        getVoices: () => [],
        speaking: true,
        pending: false,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      },
    })
    stopSpeaking()
    expect(window.speechSynthesis.cancel).toHaveBeenCalled()
  })

  it('pickBestChineseVoice prefers Yunxi', () => {
    const voices = [
      { name: 'English', lang: 'en-US', localService: true, default: false },
      { name: 'Microsoft Yunxi', lang: 'zh-CN', localService: true, default: false },
    ] as SpeechSynthesisVoice[]
    const best = pickBestChineseVoice(voices)
    expect(best?.name).toContain('Yunxi')
  })

  it('createChineseUtterance sets lang and rate', () => {
    const u = createChineseUtterance('测试')
    expect(u.lang).toBeTruthy()
    expect(u.rate).toBeGreaterThan(0)
  })

  it('getTtsStatus reflects engine mode', () => {
    setEngineMode('online')
    const status = getTtsStatus()
    expect(status.engineMode).toBe('online')
    expect(status.effectiveEngine).toBe('online')
  })

  it('ensureVoicesLoaded resolves empty without speechSynthesis', async () => {
    const orig = window.speechSynthesis
    // @ts-expect-error test stub
    delete window.speechSynthesis
    const voices = await ensureVoicesLoaded()
    expect(voices).toEqual([])
    Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: orig })
  })

  it('hasYunxiOrXiaoxiaoAvailable and hasAnyChineseLocalVoice', () => {
    expect(typeof hasYunxiOrXiaoxiaoAvailable()).toBe('boolean')
    expect(typeof hasAnyChineseLocalVoice()).toBe('boolean')
  })

  it('startOfflineDownload calls ensureOfflineReady', async () => {
    const offline = await import('./offlineTts')
    await startOfflineDownload()
    expect(offline.ensureOfflineReady).toHaveBeenCalled()
  })

  it('preloadOfflineTts skips when already loading', async () => {
    const offline = await import('./offlineTts')
    vi.mocked(offline.isOfflineLoading).mockReturnValue(true)
    await preloadOfflineTts()
    expect(offline.ensureOfflineReady).not.toHaveBeenCalled()
  })
})
