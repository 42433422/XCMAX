import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  apiFetch: vi.fn(), csrf: vi.fn(),
  offline: { synthesizeOffline: vi.fn(), playOfflinePcm: vi.fn(), ensureOfflineReady: vi.fn(),
    isOfflineReady: vi.fn(), isOfflineLoading: vi.fn(), getOfflineProgress: vi.fn(), stopOffline: vi.fn() },
}))
vi.mock('./apiBase', () => ({ apiFetch: mocks.apiFetch }))
vi.mock('./csrfCookie', () => ({ readCsrfTokenFromCookie: mocks.csrf }))
vi.mock('./offlineTts', () => mocks.offline)

const voice = { name: 'Microsoft Yunxi', lang: 'zh-CN', localService: true, default: false } as SpeechSynthesisVoice
let tts: typeof import('./tts')
let speech: EventTarget & { getVoices: ReturnType<typeof vi.fn>; speak: ReturnType<typeof vi.fn>; cancel: ReturnType<typeof vi.fn>; speaking: boolean; pending: boolean }
let audio: AudioFixture[]
let playback: 'end' | 'error' | 'reject' | 'pending'
class AudioFixture {
  onended: (() => void) | null = null
  onerror: (() => void) | null = null
  pause = vi.fn()
  play = vi.fn(async () => {
    if (playback === 'error') this.onerror?.()
    if (playback === 'reject') throw new Error('play rejected')
    if (playback === 'end') this.onended?.()
  })
  constructor(public src: string) { audio.push(this) }
}
const success = () => ({ ok: true, status: 200, json: async () => ({ success: true, data: { audioBase64: 'data:audio/mp3;base64,AAAA' } }) })
beforeEach(async () => {
  vi.resetModules()
  vi.resetAllMocks()
  vi.stubEnv('VITE_PRELOAD_OFFLINE_TTS', 'false')
  localStorage.clear()
  mocks.csrf.mockReturnValue('csrf-token')
  mocks.apiFetch.mockResolvedValue(success())
  mocks.offline.synthesizeOffline.mockResolvedValue({ audio: new Float32Array([0, 0]), samplingRate: 16000 })
  mocks.offline.playOfflinePcm.mockResolvedValue(undefined)
  mocks.offline.ensureOfflineReady.mockResolvedValue(undefined)
  mocks.offline.isOfflineReady.mockReturnValue(false)
  mocks.offline.isOfflineLoading.mockReturnValue(false)
  mocks.offline.getOfflineProgress.mockReturnValue(0)
  speech = Object.assign(new EventTarget(), { getVoices: vi.fn(() => [voice]), speak: vi.fn(), cancel: vi.fn(), speaking: false, pending: false })
  vi.stubGlobal('speechSynthesis', speech)
  vi.stubGlobal('SpeechSynthesisUtterance', class { constructor(public text: string) {} })
  audio = []; playback = 'end'
  vi.stubGlobal('Audio', AudioFixture)
  tts = await import('./tts')
})
afterEach(() => { tts.stopSpeaking(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.unstubAllEnvs() })

describe('TTS speech dispatch and playback', () => {
  it('finishes empty text without making a speech request', async () => {
    const onEnd = vi.fn()
    await tts.speakText('  ', { onEnd })
    expect(onEnd).toHaveBeenCalledOnce()
    expect(mocks.apiFetch).not.toHaveBeenCalled()
    await tts.speakText('')
  })
  it.each(['system', 'online', 'auto'] as const)('routes %s through online audio with normalized text and preferences', async (mode) => {
    tts.setEngineMode(mode); tts.setSpeechRate(1.5); tts.setOnlineVoiceId('zh-CN-YunxiNeural')
    const onEnd = vi.fn(), onError = vi.fn()
    await tts.speakText('  在线朗读  ', { onEnd, onError })
    expect(mocks.apiFetch).toHaveBeenCalledWith('/api/tts', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, timeoutMs: 30_000,
      body: JSON.stringify({ text: '在线朗读', lang: 'zh', voice: 'zh-CN-YunxiNeural', rate: '+50%' }),
    })
    expect(audio[0].src).toBe('data:audio/mp3;base64,AAAA')
    expect(audio[0].play).toHaveBeenCalledOnce()
    expect(onEnd).toHaveBeenCalledOnce(); expect(onError).not.toHaveBeenCalled()
    expect(speech.speak).not.toHaveBeenCalled(); expect(mocks.offline.synthesizeOffline).not.toHaveBeenCalled()
  })
  it.each([
    ['network', () => Promise.reject(new Error('network')), 'network'],
    ['server message', async () => ({ ok: false, status: 503, json: async () => ({ message: 'unavailable' }) }), 'unavailable'],
    ['invalid JSON', async () => ({ ok: false, status: 502, json: async () => { throw new Error('invalid') } }), '在线 TTS 失败（HTTP 502）'],
    ['missing audio', async () => ({ ok: true, json: async () => ({ success: true }) }), '在线 TTS 响应缺少音频'],
    ['invalid audio', async () => ({ ok: true, json: async () => ({ success: true, data: { audioBase64: 42 } }) }), '在线 TTS 响应缺少音频'],
  ])('reports %s and finishes once without falling back to system speech', async (_label, response, message) => {
    mocks.apiFetch.mockImplementation(response as () => Promise<unknown>)
    const onEnd = vi.fn(), onError = vi.fn()
    await tts.speakText('测试', { onEnd, onError })
    expect(onError).toHaveBeenCalledWith(new Error(message as string))
    expect(onEnd).toHaveBeenCalledOnce(); expect(speech.speak).not.toHaveBeenCalled()
  })
  it.each(['success', 'failure'])('primes absent CSRF with best-effort health request (%s)', async (mode) => {
    mocks.csrf.mockReturnValue('')
    if (mode === 'failure') mocks.apiFetch.mockRejectedValueOnce(new Error('health offline'))
    else mocks.apiFetch.mockResolvedValueOnce({ ok: true })
    await tts.speakText('冷启动')
    expect(mocks.apiFetch).toHaveBeenNthCalledWith(1, '/api/health', { method: 'GET', timeoutMs: 5000 })
    expect(mocks.apiFetch.mock.calls[1][0]).toBe('/api/tts')
    expect(audio[0].play).toHaveBeenCalledOnce()
  })
  it.each(['error', 'reject'] as const)('reports audio %s and clears its playback handle', async (mode) => {
    playback = mode
    const onError = vi.fn(), onEnd = vi.fn()
    await tts.speakText('播放', { onError, onEnd })
    expect(onError).toHaveBeenCalledWith(new Error(mode === 'error' ? '音频播放失败' : 'play rejected'))
    expect(onEnd).toHaveBeenCalledOnce()
    tts.stopSpeaking(); expect(audio[0].pause).not.toHaveBeenCalled()
  })
  it('stops previous audio and cancels only active or pending system speech', async () => {
    playback = 'pending'
    const first = tts.speakText('first')
    await vi.waitFor(() => expect(audio).toHaveLength(1))
    const second = tts.speakText('second')
    await vi.waitFor(() => expect(audio).toHaveLength(2))
    expect(audio[0].pause).toHaveBeenCalledOnce(); expect(audio[0].src).toBe('')
    tts.stopSpeaking(); expect(audio[1].pause).toHaveBeenCalledOnce(); expect(audio[1].src).toBe('')
    expect(speech.cancel).not.toHaveBeenCalled()
    speech.speaking = true; tts.stopSpeaking()
    speech.speaking = false; speech.pending = true; tts.stopSpeaking()
    expect(speech.cancel).toHaveBeenCalledTimes(2)
    audio.forEach((item) => item.onended?.()); await Promise.all([first, second])
  })
  it.each(['success', 'synthesis failure', 'playback failure'])('uses offline synthesis and preserves completion on %s', async (mode) => {
    tts.setEngineMode('offline'); mocks.offline.isOfflineReady.mockReturnValue(true)
    if (mode === 'synthesis failure') mocks.offline.synthesizeOffline.mockRejectedValueOnce(new Error(mode))
    if (mode === 'playback failure') mocks.offline.playOfflinePcm.mockRejectedValueOnce(new Error(mode))
    const onEnd = vi.fn(), onError = vi.fn()
    await tts.speakText('离线朗读', { onEnd, onError })
    expect(mocks.offline.synthesizeOffline).toHaveBeenCalledWith('离线朗读')
    if (mode === 'success') {
      expect(mocks.offline.playOfflinePcm).toHaveBeenCalledWith(new Float32Array([0, 0]), 16000)
      expect(onError).not.toHaveBeenCalled()
    } else expect(onError).toHaveBeenCalledWith(new Error(mode))
    expect(onEnd).toHaveBeenCalledOnce(); expect(mocks.apiFetch).not.toHaveBeenCalled()
    expect(tts.getTtsStatus().effectiveEngine).toBe('offline')
  })
  it('chooses Yunxi, configures utterances and reports concrete availability', async () => {
    expect(tts.pickBestChineseVoice([{ name: 'English', lang: 'en-US' } as SpeechSynthesisVoice, voice])).toBe(voice)
    expect(tts.createChineseUtterance('测试')).toMatchObject({ text: '测试', voice, lang: 'zh-CN', rate: 1.15, pitch: 1 })
    expect(tts.getTtsStatus()).toMatchObject({ engineMode: 'online', effectiveEngine: 'online', yunxiAvailable: true })
    expect(tts.hasYunxiOrXiaoxiaoAvailable()).toBe(true); expect(tts.hasAnyChineseLocalVoice()).toBe(true)
    Reflect.deleteProperty(window, 'speechSynthesis')
    expect(await tts.ensureVoicesLoaded()).toEqual([])
  })
})

describe('voice loading and offline warmup', () => {
  it.each(['voiceschanged', 'timeout'])('shares pending load and resolves on %s', async (mode) => {
    vi.useFakeTimers(); vi.resetModules(); speech.getVoices.mockReturnValue([])
    const remove = vi.spyOn(speech, 'removeEventListener')
    tts = await import('./tts')
    const pending = tts.ensureVoicesLoaded()
    expect(tts.ensureVoicesLoaded()).toBe(pending)
    const listener = vi.fn(); const off = tts.onTtsStatusChange(listener)
    if (mode === 'voiceschanged') {
      speech.getVoices.mockReturnValue([voice]); speech.dispatchEvent(new Event('voiceschanged'))
      expect(await pending).toEqual([voice]); expect(remove).toHaveBeenCalledWith('voiceschanged', expect.any(Function))
    } else {
      await vi.advanceTimersByTimeAsync(2000)
      expect(await pending).toEqual([])
    }
    expect(listener).toHaveBeenCalledOnce(); off()
    await vi.advanceTimersByTimeAsync(2000)
    expect(await tts.ensureVoicesLoaded()).toEqual(mode === 'voiceschanged' ? [voice] : [])
  })
  it('selects newly available voices synchronously while the asynchronous load is pending', async () => {
    vi.useFakeTimers(); vi.resetModules(); speech.getVoices.mockReturnValue([])
    tts = await import('./tts')
    speech.getVoices.mockReturnValue([voice])
    expect(tts.pickBestChineseVoiceSync()).toBe(voice)
    speech.dispatchEvent(new Event('voiceschanged'))
    await vi.advanceTimersByTimeAsync(2000)
    expect(await tts.ensureVoicesLoaded()).toEqual([voice])
  })
  it.each(['zh-SG', 'zh-HK', 'zh-MO'])('supports the %s voice fallback locale', (lang) => {
    const candidate = { name: 'Google Chinese', lang, localService: false } as SpeechSynthesisVoice
    expect(tts.pickBestChineseVoice([candidate])).toBe(candidate)
  })
  it('publishes download progress and completion', async () => {
    const onProgress = vi.fn(), onChange = vi.fn(); const off = tts.onTtsStatusChange(onChange)
    mocks.offline.ensureOfflineReady.mockImplementation(async (progress) => { progress(25); progress(100) })
    await tts.startOfflineDownload(onProgress)
    expect(onProgress.mock.calls).toEqual([[25], [100]])
    expect(onChange).toHaveBeenCalledTimes(3); off()
  })
  it('skips loading or ready packs, retries a failed warmup, then deduplicates success', async () => {
    mocks.offline.isOfflineLoading.mockReturnValue(true); await tts.preloadOfflineTts()
    mocks.offline.isOfflineLoading.mockReturnValue(false); mocks.offline.isOfflineReady.mockReturnValue(true)
    await tts.preloadOfflineTts(); expect(mocks.offline.ensureOfflineReady).not.toHaveBeenCalled()
    mocks.offline.isOfflineReady.mockReturnValue(false)
    mocks.offline.ensureOfflineReady.mockRejectedValueOnce(new Error('offline download failed'))
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    await tts.preloadOfflineTts()
    expect(warn).toHaveBeenCalledWith('[tts] offline preload failed:', new Error('offline download failed'))
    await tts.preloadOfflineTts(); await tts.preloadOfflineTts()
    expect(mocks.offline.ensureOfflineReady).toHaveBeenCalledTimes(2)
  })
  it('starts optional automatic warmup only after its startup delay', async () => {
    vi.useFakeTimers(); vi.resetModules(); vi.stubEnv('VITE_PRELOAD_OFFLINE_TTS', 'true')
    tts = await import('./tts')
    await vi.advanceTimersByTimeAsync(1499); expect(mocks.offline.ensureOfflineReady).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1); expect(mocks.offline.ensureOfflineReady).toHaveBeenCalledOnce()
  })
})
