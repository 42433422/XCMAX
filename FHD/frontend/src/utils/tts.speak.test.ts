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
  speech = Object.assign(new EventTarget(), { getVoices: vi.fn(() => [voice]), speak: vi.fn((u: { onend?: () => void }) => u.onend?.()), cancel: vi.fn(), speaking: false, pending: false })
  vi.stubGlobal('speechSynthesis', speech)
  vi.stubGlobal('SpeechSynthesisUtterance', class { constructor(public text: string) {} })
  audio = []; playback = 'end'
  vi.stubGlobal('Audio', AudioFixture)
  tts = await import('./tts')
  tts.setEngineMode('system')
})
afterEach(() => { tts.stopSpeaking(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.unstubAllEnvs() })

describe('TTS speech dispatch and playback', () => {
  it('does not silently fall back when MiMo fails in automatic mode', async () => {
    tts.setEngineMode('auto')
    mocks.apiFetch.mockRejectedValueOnce(new Error('platform unavailable'))
    const onError = vi.fn()
    await tts.speakText('测试', { onError })
    expect(speech.speak).not.toHaveBeenCalled()
    expect(mocks.offline.synthesizeOffline).not.toHaveBeenCalled()
    expect(onError).toHaveBeenCalledOnce()
  })
  it('splits a long reply into sentence chunks and plays them in order', async () => {
    tts.setEngineMode('online')
    await tts.speakText('第一句内容需要足够长才能单独成块。第二句内容也需要足够长才能单独成块。')
    expect(mocks.apiFetch).toHaveBeenCalledTimes(2)
    expect(audio).toHaveLength(2)
    const bodies = mocks.apiFetch.mock.calls.map(call => JSON.parse(String(call[1]?.body)).text)
    expect(bodies).toEqual(['第一句内容需要足够长才能单独成块', '第二句内容也需要足够长才能单独成块'])
  })
  it('keeps a short reply in a single synthesis request', async () => {
    tts.setEngineMode('online')
    await tts.speakText('好的，马上处理。')
    expect(mocks.apiFetch).toHaveBeenCalledTimes(1)
    expect(audio).toHaveLength(1)
  })
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
  ])('falls back to system speech when synthesis fails: %s', async (_label, response) => {
    mocks.apiFetch.mockImplementation(response as () => Promise<unknown>)
    const onEnd = vi.fn(), onError = vi.fn()
    await tts.speakText('测试', { onEnd, onError })
    expect(speech.speak).toHaveBeenCalledOnce()
    expect(onError).not.toHaveBeenCalled()
    expect(mocks.toast).not.toHaveBeenCalled()
    expect(onEnd).toHaveBeenCalledOnce()
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
  it.each(['health', 'post', 'json'] as const)('falls back after timed out %s', async (stage) => {
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
    expect(speech.speak).toHaveBeenCalledOnce()
    expect(onError).not.toHaveBeenCalled()
    expect(onEnd).toHaveBeenCalledOnce(); expect(audio).toHaveLength(0)
    expect(mocks.toast).not.toHaveBeenCalled()
  })
  it('limits stalled audio loading to 15 seconds and falls back', async () => {
    vi.useFakeTimers(); playback = 'loading'
    const onEnd = vi.fn(), onError = vi.fn()
    const speaking = tts.speakText('加载失败', { onEnd, onError })
    await vi.advanceTimersByTimeAsync(14_999)
    expect(onEnd).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1); await speaking
    expect(onEnd).toHaveBeenCalledOnce()
    expect(speech.speak).toHaveBeenCalledOnce()
    expect(onError).not.toHaveBeenCalled()
    expect(audio[0].pause).toHaveBeenCalledOnce(); expect(audio[0].src).toBe('')
    expect(mocks.toast).not.toHaveBeenCalled()
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
    expect(speech.speak).toHaveBeenCalledOnce()
    expect(onError).not.toHaveBeenCalled()
    expect(onEnd).toHaveBeenCalledOnce(); expect(audio).toHaveLength(0)
  })
  it('uses ready offline audio when the online request fails', async () => {
    mocks.offline.isOfflineReady.mockReturnValue(true)
    mocks.apiFetch.mockRejectedValue(new Error('upstream down'))
    const onError = vi.fn()
    await tts.speakText('在线失败', { onError })
    expect(mocks.offline.synthesizeOffline).toHaveBeenCalledWith('在线失败', expect.any(AbortSignal))
    expect(mocks.offline.playOfflinePcm).toHaveBeenCalledWith(new Float32Array([0, 0]), 16000, expect.any(AbortSignal))
    expect(onError).not.toHaveBeenCalled()
    expect(speech.speak).not.toHaveBeenCalled()
  })
  it.each(['stop', 'switch'] as const)('does not play an offline fallback after %s during synthesis', async (action) => {
    const pending = deferred<{ audio: Float32Array; samplingRate: number }>(), started = deferred<void>()
    mocks.offline.isOfflineReady.mockReturnValue(true)
    mocks.apiFetch.mockRejectedValueOnce(new Error('network'))
    mocks.offline.synthesizeOffline.mockImplementationOnce(() => { started.resolve(); return pending.promise })
    const onEnd = vi.fn(), onError = vi.fn()
    const first = tts.speakText('旧回退', { onEnd, onError })
    await started.promise
    if (action === 'stop') tts.stopSpeaking()
    else await tts.speakText('新语音')
    pending.resolve({ audio: new Float32Array([1]), samplingRate: 16000 })
    await first
    expect(mocks.offline.playOfflinePcm).not.toHaveBeenCalled()
    expect(speech.speak).not.toHaveBeenCalled()
    expect(onEnd).toHaveBeenCalledOnce(); expect(onError).not.toHaveBeenCalled()
    expect(mocks.toast).not.toHaveBeenCalled()
  })
  it('settles a stopped system fallback even when cancellation emits no event', async () => {
    mocks.apiFetch.mockRejectedValueOnce(new Error('network'))
    const started = deferred<void>(), onEnd = vi.fn(), onError = vi.fn()
    speech.speak.mockImplementation(() => { speech.speaking = true; started.resolve() })
    const speaking = tts.speakText('停止系统语音', { onEnd, onError })
    await started.promise
    tts.stopSpeaking()
    await vi.waitFor(() => expect(onEnd).toHaveBeenCalledOnce(), { timeout: 200 })
    await speaking
    expect(speech.cancel).toHaveBeenCalledOnce()
    expect(onError).not.toHaveBeenCalled(); expect(mocks.toast).not.toHaveBeenCalled()
  })
  it('times out a system fallback that never starts or emits an event', async () => {
    vi.useFakeTimers()
    mocks.apiFetch.mockRejectedValueOnce(new Error('network'))
    speech.speak.mockImplementation(() => {})
    const onEnd = vi.fn(), onError = vi.fn()
    const speaking = tts.speakText('无事件', { onEnd, onError })
    await vi.advanceTimersByTimeAsync(60_000)
    expect(onEnd).toHaveBeenCalledOnce()
    await speaking
    expect(speech.cancel).toHaveBeenCalledOnce()
    expect(onError).toHaveBeenCalledOnce(); expect(mocks.toast).toHaveBeenCalledOnce()
  })
  it('finishes a started system fallback if the engine becomes idle without an end event', async () => {
    vi.useFakeTimers()
    mocks.apiFetch.mockRejectedValueOnce(new Error('network'))
    speech.speak.mockImplementation((u) => { speech.speaking = true; u.onstart?.() })
    const onEnd = vi.fn(), onError = vi.fn()
    const speaking = tts.speakText('系统语音中断', { onEnd, onError })
    await vi.advanceTimersByTimeAsync(0)
    speech.speaking = false
    await vi.advanceTimersByTimeAsync(60_000)
    expect(onEnd).toHaveBeenCalledOnce()
    await speaking
    expect(onError).toHaveBeenCalledOnce()
  })
  it('does not cut off a system fallback that has started a long message', async () => {
    vi.useFakeTimers()
    mocks.apiFetch.mockRejectedValueOnce(new Error('network'))
    let utterance: { onstart?: () => void; onend?: () => void } | undefined
    speech.speak.mockImplementation((u) => { speech.speaking = true; utterance = u; u.onstart?.() })
    const onEnd = vi.fn()
    const speaking = tts.speakText('长语音'.repeat(1000), { onEnd })
    await vi.advanceTimersByTimeAsync(120_000)
    expect(onEnd).not.toHaveBeenCalled(); expect(speech.cancel).not.toHaveBeenCalled()
    utterance?.onend?.(); await speaking
    expect(onEnd).toHaveBeenCalledOnce(); expect(mocks.toast).not.toHaveBeenCalled()
  })
  it('settles promptly when stopped while waiting for system voices', async () => {
    vi.useFakeTimers(); vi.resetModules(); speech.getVoices.mockReturnValue([])
    tts = await import('./tts')
    mocks.apiFetch.mockRejectedValueOnce(new Error('network'))
    const onEnd = vi.fn(), onError = vi.fn()
    const speaking = tts.speakText('准备中', { onEnd, onError })
    await vi.advanceTimersByTimeAsync(0)
    tts.stopSpeaking()
    await vi.advanceTimersByTimeAsync(0)
    expect(onEnd).toHaveBeenCalledOnce()
    expect(onError).not.toHaveBeenCalled(); expect(speech.speak).not.toHaveBeenCalled()
    await speaking
  })
  it('allows system fallback after an online timeout and cancels it on stop', async () => {
    vi.useFakeTimers()
    mocks.apiFetch.mockImplementation((_url, init) => abortable(new Promise<never>(() => {}), init.signal))
    speech.speak.mockImplementation(() => { speech.speaking = true })
    const onEnd = vi.fn(), onError = vi.fn()
    const speaking = tts.speakText('超时后回退', { onEnd, onError })
    await vi.advanceTimersByTimeAsync(30_000)
    expect(speech.speak).toHaveBeenCalledOnce()
    tts.stopSpeaking()
    await vi.advanceTimersByTimeAsync(0)
    expect(onEnd).toHaveBeenCalledOnce()
    expect(onError).not.toHaveBeenCalled(); expect(mocks.toast).not.toHaveBeenCalled()
    await speaking
  })
  it('does not impose a fixed playback deadline after system speech starts', async () => {
    vi.useFakeTimers()
    mocks.apiFetch.mockRejectedValueOnce(new Error('network'))
    let utterance: { onstart?: () => void; onend?: () => void } | undefined
    speech.speak.mockImplementation((u) => { speech.speaking = true; utterance = u; u.onstart?.() })
    const onEnd = vi.fn()
    const speaking = tts.speakText('长时间播放', { onEnd })
    await vi.advanceTimersByTimeAsync(180_000)
    expect(onEnd).not.toHaveBeenCalled(); expect(speech.cancel).not.toHaveBeenCalled()
    utterance?.onend?.(); await speaking
    expect(onEnd).toHaveBeenCalledOnce()
  })
  it('does not stop started system speech when its estimated duration expires', async () => {
    vi.useFakeTimers()
    mocks.apiFetch.mockRejectedValueOnce(new Error('network'))
    let utterance: { onstart?: () => void; onend?: () => void } | undefined
    speech.speak.mockImplementation((u) => { speech.speaking = true; utterance = u; u.onstart?.() })
    const onEnd = vi.fn()
    const speaking = tts.speakText('长语音', { onEnd })
    await vi.advanceTimersByTimeAsync(120_000)
    expect(onEnd).not.toHaveBeenCalled()
    expect(speech.cancel).not.toHaveBeenCalled()
    utterance?.onend?.(); await speaking
  })
  it.each(['stop', 'switch'] as const)('settles system fallback after online timeout on %s', async (action) => {
    vi.useFakeTimers()
    mocks.apiFetch.mockImplementationOnce((_url, init) => abortable(new Promise<never>(() => {}), init.signal))
    speech.speak.mockImplementation(() => { speech.speaking = true })
    const onEnd = vi.fn(), onError = vi.fn()
    const first = tts.speakText('超时后回退', { onEnd, onError })
    await vi.advanceTimersByTimeAsync(30_000)
    expect(speech.speak).toHaveBeenCalledOnce()
    if (action === 'stop') tts.stopSpeaking()
    else await tts.speakText('新语音')
    await vi.advanceTimersByTimeAsync(0)
    expect(onEnd).toHaveBeenCalledOnce()
    expect(onError).not.toHaveBeenCalled(); expect(mocks.toast).not.toHaveBeenCalled()
    await first
  })
  it.each(['offline', 'fallback'] as const)('settles stopped %s synthesis without waiting for its result', async (mode) => {
    const pending = deferred<{ audio: Float32Array; samplingRate: number }>(), started = deferred<void>()
    if (mode === 'offline') tts.setEngineMode('offline')
    else { mocks.offline.isOfflineReady.mockReturnValue(true); mocks.apiFetch.mockRejectedValueOnce(new Error('network')) }
    mocks.offline.synthesizeOffline.mockImplementationOnce(() => { started.resolve(); return pending.promise })
    const onEnd = vi.fn(), onError = vi.fn()
    const speaking = tts.speakText('离线合成', { onEnd, onError })
    await started.promise
    tts.stopSpeaking()
    await vi.waitFor(() => expect(onEnd).toHaveBeenCalledOnce(), { timeout: 200 })
    await speaking
    pending.resolve({ audio: new Float32Array([1]), samplingRate: 16000 })
    await Promise.resolve()
    expect(mocks.offline.playOfflinePcm).not.toHaveBeenCalled()
    expect(onError).not.toHaveBeenCalled(); expect(mocks.toast).not.toHaveBeenCalled()
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
    expect(mocks.offline.synthesizeOffline).toHaveBeenCalledWith('离线朗读', expect.any(AbortSignal))
    if (mode === 'success') {
      expect(mocks.offline.playOfflinePcm).toHaveBeenCalledWith(new Float32Array([0, 0]), 16000, expect.any(AbortSignal))
      expect(onError).not.toHaveBeenCalled()
    } else expect(onError).toHaveBeenCalledWith(new Error(mode))
    expect(onEnd).toHaveBeenCalledOnce(); expect(mocks.apiFetch).not.toHaveBeenCalled()
    expect(tts.getTtsStatus().effectiveEngine).toBe('offline')
  })
  it.each(['offline', 'fallback'] as const)('passes the cancellation signal to %s synthesis and ignores late audio', async (mode) => {
    const pending = deferred<{ audio: Float32Array; samplingRate: number }>(), started = deferred<void>()
    if (mode === 'offline') tts.setEngineMode('offline')
    else { mocks.offline.isOfflineReady.mockReturnValue(true); mocks.apiFetch.mockRejectedValueOnce(new Error('network')) }
    mocks.offline.synthesizeOffline.mockImplementationOnce((_text, signal) => {
      started.resolve()
      return signal ? abortable(pending.promise, signal) : pending.promise
    })
    const onEnd = vi.fn(), onError = vi.fn()
    const speaking = tts.speakText('取消离线合成', { onEnd, onError })
    await started.promise
    const signal = mocks.offline.synthesizeOffline.mock.calls[0][1] as AbortSignal | undefined
    tts.stopSpeaking()
    expect(signal?.aborted).toBe(true)
    await speaking
    pending.resolve({ audio: new Float32Array([1]), samplingRate: 16000 })
    await Promise.resolve()
    expect(mocks.offline.playOfflinePcm).not.toHaveBeenCalled()
    expect(onEnd).toHaveBeenCalledOnce(); expect(onError).not.toHaveBeenCalled()
    expect(mocks.toast).not.toHaveBeenCalled()
  })
  it.each(['offline', 'fallback'] as const)('passes the cancellation signal to %s PCM playback', async (mode) => {
    const pending = deferred<void>(), started = deferred<void>()
    if (mode === 'offline') tts.setEngineMode('offline')
    else { mocks.offline.isOfflineReady.mockReturnValue(true); mocks.apiFetch.mockRejectedValueOnce(new Error('network')) }
    mocks.offline.playOfflinePcm.mockImplementationOnce((_pcm, _rate, signal) => {
      started.resolve()
      return signal ? abortable(pending.promise, signal) : pending.promise
    })
    const onEnd = vi.fn(), onError = vi.fn()
    const speaking = tts.speakText('取消离线播放', { onEnd, onError })
    await started.promise
    const signal = mocks.offline.playOfflinePcm.mock.calls[0][2] as AbortSignal | undefined
    tts.stopSpeaking()
    expect(signal?.aborted).toBe(true)
    await speaking
    expect(onEnd).toHaveBeenCalledOnce(); expect(onError).not.toHaveBeenCalled()
    expect(mocks.toast).not.toHaveBeenCalled()
  })
  it('chooses Yunxi, configures utterances and reports concrete availability', async () => {
    tts.setEngineMode('online')
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
    const retry = tts.ensureVoicesLoaded()
    if (mode === 'timeout') await vi.advanceTimersByTimeAsync(2000)
    expect(await retry).toEqual(mode === 'voiceschanged' ? [voice] : [])
  })
  it('cleans up timed-out voice discovery and retries when voices appear later', async () => {
    vi.useFakeTimers(); vi.resetModules(); speech.getVoices.mockReturnValue([])
    const remove = vi.spyOn(speech, 'removeEventListener')
    tts = await import('./tts')
    const first = tts.ensureVoicesLoaded()
    await vi.advanceTimersByTimeAsync(2000)
    expect(await first).toEqual([])
    expect(remove).toHaveBeenCalledWith('voiceschanged', expect.any(Function))
    speech.getVoices.mockReturnValue([voice])
    expect(await tts.ensureVoicesLoaded()).toEqual([voice])
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
