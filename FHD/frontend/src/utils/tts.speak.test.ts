import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  apiFetch: vi.fn(), csrf: vi.fn(), toast: vi.fn(),
  offline: { synthesizeOffline: vi.fn(), playOfflinePcm: vi.fn(), ensureOfflineReady: vi.fn(),
    isOfflineReady: vi.fn(), isOfflineLoading: vi.fn(), getOfflineProgress: vi.fn(), stopOffline: vi.fn() },
}))
vi.mock('./apiBase', () => ({ apiFetch: mocks.apiFetch }))
vi.mock('./csrfCookie', () => ({ readCsrfTokenFromCookie: mocks.csrf }))
vi.mock('./offlineTts', () => mocks.offline)
vi.mock('@/composables/useAppToast', () => ({ showAppToast: mocks.toast }))

const voice = { name: 'Microsoft Yunxi', lang: 'zh-CN', localService: true, default: false } as SpeechSynthesisVoice
let tts: typeof import('./tts')
let speech: EventTarget & { getVoices: ReturnType<typeof vi.fn>; speak: ReturnType<typeof vi.fn>; cancel: ReturnType<typeof vi.fn>; speaking: boolean; pending: boolean }
let audio: AudioFixture[]
let playback: 'end' | 'error' | 'reject' | 'pending' | 'loading' | 'blocked'
class AudioFixture {
  onended: (() => void) | null = null
  onerror: (() => void) | null = null
  onplaying: (() => void) | null = null
  pause = vi.fn()
  play = vi.fn(async () => {
    if (playback === 'error') this.onerror?.()
    if (playback === 'reject') throw new Error('play rejected')
    if (playback === 'blocked') throw new DOMException('user gesture required', 'NotAllowedError')
    if (playback === 'pending' || playback === 'end') this.onplaying?.()
    if (playback === 'end') this.onended?.()
  })
  constructor(public src: string) { audio.push(this) }
}
const success = () => ({ ok: true, status: 200, json: async () => ({ success: true, data: { audioBase64: 'data:audio/mp3;base64,AAAA' } }) })
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}
function abortable<T>(promise: Promise<T>, signal: AbortSignal): Promise<T> {
  return new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(signal.reason), { once: true })
    promise.then(resolve, reject)
  })
}
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
      method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: expect.any(AbortSignal),
      body: JSON.stringify({ text: '在线朗读', lang: 'zh', voice: 'zh-CN-YunxiNeural', rate: '+50%' }),
    })
    expect(audio[0].src).toBe('data:audio/mp3;base64,AAAA')
    expect(audio[0].play).toHaveBeenCalledOnce()
    expect(onEnd).toHaveBeenCalledOnce(); expect(onError).not.toHaveBeenCalled()
    expect(mocks.toast).not.toHaveBeenCalled()
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
    expect(mocks.toast).toHaveBeenCalledExactlyOnceWith('语音播放失败，请稍后重试。')
    expect(onEnd).toHaveBeenCalledOnce(); expect(speech.speak).not.toHaveBeenCalled()
  })
  it.each(['success', 'failure'])('primes absent CSRF with best-effort health request (%s)', async (mode) => {
    mocks.csrf.mockReturnValue('')
    if (mode === 'failure') mocks.apiFetch.mockRejectedValueOnce(new Error('health offline'))
    else mocks.apiFetch.mockResolvedValueOnce({ ok: true })
    await tts.speakText('冷启动')
    expect(mocks.apiFetch).toHaveBeenNthCalledWith(1, '/api/health', { method: 'GET', timeoutMs: 5000, signal: expect.any(AbortSignal) })
    expect(mocks.apiFetch.mock.calls[1][0]).toBe('/api/tts')
    expect(audio[0].play).toHaveBeenCalledOnce()
  })
  it.each(['error', 'reject'] as const)('reports audio %s and clears its playback handle', async (mode) => {
    playback = mode
    const onError = vi.fn(), onEnd = vi.fn()
    await tts.speakText('播放', { onError, onEnd })
    expect(onError).toHaveBeenCalledWith(new Error(mode === 'error' ? '音频播放失败' : 'play rejected'))
    expect(onEnd).toHaveBeenCalledOnce()
    expect(audio[0].pause).toHaveBeenCalledOnce(); expect(audio[0].src).toBe('')
    tts.stopSpeaking(); expect(audio[0].pause).toHaveBeenCalledOnce()
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
  it.each([[0.75, '-25%'], [1, '+0%'], [1.5, '+50%']] as const)('formats rate %s as %s', async (rate, expected) => {
    tts.setSpeechRate(rate)
    await tts.speakText('速率测试')
    expect(JSON.parse(mocks.apiFetch.mock.calls[0][1].body).rate).toBe(expected)
  })
  it.each(['health', 'post', 'json'] as const)('cancels during %s and ignores a late result', async (stage) => {
    const late = deferred<unknown>(), started = deferred<void>()
    mocks.csrf.mockReturnValue(stage === 'health' ? '' : 'csrf-token')
    mocks.apiFetch.mockImplementation(async () => {
      if (stage === 'health' || stage === 'post') {
        started.resolve()
        return late.promise
      }
      return { ...success(), json: () => { started.resolve(); return late.promise } }
    })
    const onEnd = vi.fn(), onError = vi.fn()
    const speaking = tts.speakText('取消请求', { onEnd, onError })
    await started.promise
    const signal = mocks.apiFetch.mock.calls[0][1].signal as AbortSignal
    expect(signal.aborted).toBe(false)
    tts.stopSpeaking()
    expect(signal.aborted).toBe(true)
    late.resolve(stage === 'json' ? await success().json() : success())
    await speaking
    expect(audio).toHaveLength(0)
    expect(mocks.apiFetch).toHaveBeenCalledTimes(1)
    expect(onEnd).toHaveBeenCalledOnce()
    expect(onError).not.toHaveBeenCalled(); expect(mocks.toast).not.toHaveBeenCalled()
  })
  it('supersedes pending synthesis without allowing the old response to play', async () => {
    const old = deferred<ReturnType<typeof success>>(), started = deferred<void>()
    mocks.apiFetch.mockImplementationOnce(() => { started.resolve(); return old.promise })
    const oldEnd = vi.fn(), oldError = vi.fn()
    const first = tts.speakText('旧请求', { onEnd: oldEnd, onError: oldError })
    await started.promise
    const signal = mocks.apiFetch.mock.calls[0][1].signal as AbortSignal
    await tts.speakText('新请求')
    expect(signal.aborted).toBe(true)
    old.resolve(success()); await first
    expect(audio).toHaveLength(1)
    expect(oldEnd).toHaveBeenCalledOnce(); expect(oldError).not.toHaveBeenCalled()
    expect(mocks.toast).not.toHaveBeenCalled()
  })
  it('settles active playback on stop without waiting for an ended event', async () => {
    playback = 'pending'
    const onEnd = vi.fn(), onError = vi.fn()
    const speaking = tts.speakText('停止播放', { onEnd, onError })
    await vi.waitFor(() => expect(audio).toHaveLength(1))
    tts.stopSpeaking(); await speaking
    expect(onEnd).toHaveBeenCalledOnce(); expect(onError).not.toHaveBeenCalled()
    expect(audio[0].pause).toHaveBeenCalledOnce(); expect(audio[0].onended).toBeNull()
    expect(mocks.toast).not.toHaveBeenCalled()
  })
  it('lets playing audio exceed 30 seconds before finishing normally', async () => {
    vi.useFakeTimers(); playback = 'pending'
    const onEnd = vi.fn(), onError = vi.fn()
    const speaking = tts.speakText('长消息', { onEnd, onError })
    await vi.advanceTimersByTimeAsync(60_000)
    expect(audio).toHaveLength(1)
    expect(audio[0].pause).not.toHaveBeenCalled()
    expect(onEnd).not.toHaveBeenCalled(); expect(onError).not.toHaveBeenCalled()
    audio[0].onended?.(); await speaking
    expect(onEnd).toHaveBeenCalledOnce(); expect(mocks.toast).not.toHaveBeenCalled()
  })
  it.each(['health', 'post', 'json'] as const)('aborts timed out %s with one visible error', async (stage) => {
    vi.useFakeTimers()
    mocks.csrf.mockReturnValue(stage === 'health' ? '' : 'csrf-token')
    let requestSignal: AbortSignal
    mocks.apiFetch.mockImplementation(async (_url, init) => {
      requestSignal = init.signal
      const pending = abortable(new Promise<never>(() => {}), requestSignal)
      return stage === 'json' ? { ...success(), json: () => pending } : pending
    })
    const onEnd = vi.fn(), onError = vi.fn()
    const speaking = tts.speakText('慢合成', { onEnd, onError })
    await vi.advanceTimersByTimeAsync(29_999)
    expect(onEnd).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1); await speaking
    expect(requestSignal!.aborted).toBe(true)
    expect(onError).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ name: 'TimeoutError' }))
    expect(onEnd).toHaveBeenCalledOnce(); expect(audio).toHaveLength(0)
    expect(mocks.toast).toHaveBeenCalledExactlyOnceWith('语音服务响应超时，请稍后重试。')
  })
  it('limits stalled audio loading to 15 seconds', async () => {
    vi.useFakeTimers(); playback = 'loading'
    const onEnd = vi.fn(), onError = vi.fn()
    const speaking = tts.speakText('加载失败', { onEnd, onError })
    await vi.advanceTimersByTimeAsync(14_999)
    expect(onEnd).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1); await speaking
    expect(onEnd).toHaveBeenCalledOnce()
    expect(onError).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ name: 'TimeoutError' }))
    expect(audio[0].pause).toHaveBeenCalledOnce(); expect(audio[0].src).toBe('')
    expect(mocks.toast).toHaveBeenCalledExactlyOnceWith('语音服务响应超时，请稍后重试。')
  })
  it('shares the synthesis deadline across health, POST and response-body reads', async () => {
    vi.useFakeTimers(); mocks.csrf.mockReturnValue('')
    const health = deferred<unknown>(), post = deferred<unknown>()
    mocks.apiFetch.mockImplementation((url) => url === '/api/health' ? health.promise : post.promise)
    const onEnd = vi.fn(), onError = vi.fn()
    const speaking = tts.speakText('总预算', { onEnd, onError })
    await vi.advanceTimersByTimeAsync(4_000)
    health.resolve({ ok: true }); await vi.advanceTimersByTimeAsync(20_000)
    const signal = mocks.apiFetch.mock.calls[1][1].signal as AbortSignal
    post.resolve({ ...success(), json: () => abortable(new Promise<never>(() => {}), signal) })
    await vi.advanceTimersByTimeAsync(5_999)
    expect(onEnd).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1); await speaking
    expect(onError).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ name: 'TimeoutError' }))
    expect(onEnd).toHaveBeenCalledOnce(); expect(audio).toHaveLength(0)
  })
  it('shows an actionable browser permission error', async () => {
    playback = 'blocked'
    const onEnd = vi.fn(), onError = vi.fn()
    await tts.speakText('手动重试', { onEnd, onError })
    expect(onError).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ name: 'NotAllowedError' }))
    expect(onEnd).toHaveBeenCalledOnce()
    expect(mocks.toast).toHaveBeenCalledExactlyOnceWith('语音播放被浏览器阻止，请点击朗读按钮重试。')
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
