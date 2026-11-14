/**
 * 统一 TTS 入口：
 *   - online（默认 / auto）：`POST /api/tts` → 平台 MiMo-V2.5 TTS，失败时提示用户。
 *   - system：用户显式选择时可使用已安装的离线包或系统语音作为回退。
 *   - offline：可选 MMS-TTS（需用户显式启用）；失败不再回退系统 TTS。
 *   - system：保留设置项兼容。
 */

import { apiFetch } from './apiBase'
import { readCsrfTokenFromCookie } from './csrfCookie'
import { playOfflinePcm, synthesizeOffline, ensureOfflineReady, isOfflineReady, isOfflineLoading, getOfflineProgress, stopOffline } from './offlineTts'
import { asRecord, asString } from '@/utils/typeGuards'
import { showAppToast } from '@/composables/useAppToast'

const VOICE_PREF_KEY = 'xcagi_tts_voice'
const ENGINE_PREF_KEY = 'xcagi_tts_engine' // 'auto' | 'system' | 'offline' | 'online'
const BANNER_DISMISSED_KEY = 'xcagi_tts_banner_dismissed'
const SPEECH_RATE_KEY = 'xcagi_tts_rate'
const DEFAULT_SPEECH_RATE = 1.15
/** Edge TTS voice id，须匹配后端 ``^[a-z]{2,3}-[A-Z]{2,3}-[A-Za-z]+Neural$``，默认与 ``app/services/tts_service.DEFAULT_EDGE_VOICE`` 一致 */
const ONLINE_VOICE_KEY = 'xcagi_tts_online_voice'
const DEFAULT_ONLINE_VOICE_ID = 'zh-CN-XiaoxiaoNeural'
const AUTO_PRELOAD_OFFLINE_TTS = String(import.meta.env.VITE_PRELOAD_OFFLINE_TTS || '').toLowerCase() === 'true'

export type TtsEngineMode = 'auto' | 'system' | 'offline' | 'online'

let onlineAudioEl: HTMLAudioElement | null = null
let speechController: AbortController | null = null
let offlineWarmupStarted = false

function stopOnlinePlayback(): void {
  if (!onlineAudioEl) return
  const el = onlineAudioEl
  onlineAudioEl = null
  try {
    el.pause()
    // Setting src to empty releases the media resource without calling load(),
    // which avoids triggering Windows audio-session teardown (and the resulting
    // volume-restore "pop" from OS audio ducking).
    el.src = ''
  } catch {
    /* ignore */
  }
}

const NEURAL_KEYWORDS = [
  'Yunxi', 'Yunyang', 'Yunjian', 'Yunhao', 'Yunxia',
  'Xiaoxiao', 'Xiaoyi', 'Xiaohan', 'Xiaomeng', 'Xiaomo',
  '云希', '云扬', '云健', '云皓', '云夏',
  '晓晓', '晓伊', '晓涵', '晓萌', '晓墨',
]
const CLASSIC_KEYWORDS = ['Huihui', 'Yaoyao', 'Kangkang', '慧慧', '瑶瑶', '康康']

let voicesCache: SpeechSynthesisVoice[] = []
let voicesReady = false
let voicesReadyPromise: Promise<SpeechSynthesisVoice[]> | null = null
let debugExposed = false

type Listener = () => void
const listeners = new Set<Listener>()

function emitChange() {
  for (const fn of listeners) {
    try { fn() } catch { /* ignore */ }
  }
}

export function onTtsStatusChange(cb: Listener): () => void {
  listeners.add(cb)
  return () => listeners.delete(cb)
}

function readPreferredVoiceName(): string {
  try { return String(localStorage.getItem(VOICE_PREF_KEY) || '').trim() } catch { return '' }
}

function writePreferredVoiceName(name: string): void {
  try {
    if (name) localStorage.setItem(VOICE_PREF_KEY, name)
    else localStorage.removeItem(VOICE_PREF_KEY)
  } catch { /* ignore */ }
  emitChange()
}

export function getEngineMode(): TtsEngineMode {
  try {
    const v = String(localStorage.getItem(ENGINE_PREF_KEY) || 'online').toLowerCase()
    if (v === 'system' || v === 'offline' || v === 'online') return v
    return 'online'
  } catch { return 'online' }
}

export function getOnlineVoiceId(): string {
  try {
    const v = String(localStorage.getItem(ONLINE_VOICE_KEY) || '').trim()
    return v || DEFAULT_ONLINE_VOICE_ID
  } catch {
    return DEFAULT_ONLINE_VOICE_ID
  }
}

export function setOnlineVoiceId(id: string): void {
  try {
    const t = String(id || '').trim()
    if (t) localStorage.setItem(ONLINE_VOICE_KEY, t)
    else localStorage.removeItem(ONLINE_VOICE_KEY)
  } catch { /* ignore */ }
  emitChange()
}

export function setEngineMode(mode: TtsEngineMode): void {
  try { localStorage.setItem(ENGINE_PREF_KEY, mode) } catch { /* ignore */ }
  emitChange()
}

export function isBannerDismissed(): boolean {
  try { return localStorage.getItem(BANNER_DISMISSED_KEY) === '1' } catch { return false }
}

export function dismissBanner(): void {
  try { localStorage.setItem(BANNER_DISMISSED_KEY, '1') } catch { /* ignore */ }
  emitChange()
}

export function getSpeechRate(): number {
  try {
    const v = localStorage.getItem(SPEECH_RATE_KEY)
    if (v) {
      const n = parseFloat(v)
      if (!isNaN(n) && n >= 0.5 && n <= 2.0) return n
    }
  } catch { /* ignore */ }
  return DEFAULT_SPEECH_RATE
}

export function setSpeechRate(rate: number): void {
  const clamped = Math.max(0.5, Math.min(2.0, rate))
  try { localStorage.setItem(SPEECH_RATE_KEY, String(clamped)) } catch { /* ignore */ }
  emitChange()
}

const PUNCTUATION_NOISE = /[，。！？；：、""''（）【】《》「」『』·•○●※◆■□…——,.!:;!?~-]+/g
const WHITESPACE_NORMALIZE = /\s+/g
const NEWLINE_NORMALIZE = /[\r\n]+/g

export function cleanTextForSpeech(text: string): string {
  return text
    .replace(PUNCTUATION_NOISE, ' ')
    .replace(NEWLINE_NORMALIZE, ' ')
    .replace(WHITESPACE_NORMALIZE, ' ')
    .trim()
}

function hasSpeechSynthesis(): boolean {
  return typeof window !== 'undefined' && 'speechSynthesis' in window
}

function loadVoicesOnce(): Promise<SpeechSynthesisVoice[]> {
  if (!hasSpeechSynthesis()) return Promise.resolve([])
  if (voicesReady) return Promise.resolve(voicesCache)
  if (voicesReadyPromise) return voicesReadyPromise

  voicesReadyPromise = new Promise<SpeechSynthesisVoice[]>((resolve) => {
    const tryResolve = () => {
      const v = window.speechSynthesis.getVoices() || []
      if (v.length > 0) {
        voicesCache = v
        voicesReady = true
        exposeDebugHelpers()
        emitChange()
        resolve(v)
        return true
      }
      return false
    }
    if (tryResolve()) return

    const onChanged = () => {
      if (tryResolve()) {
        try { window.speechSynthesis.removeEventListener('voiceschanged', onChanged) } catch { /* ignore */ }
      }
    }
    try { window.speechSynthesis.addEventListener('voiceschanged', onChanged) } catch { /* ignore */ }

    setTimeout(() => {
      try { window.speechSynthesis.removeEventListener('voiceschanged', onChanged) } catch { /* ignore */ }
      if (!voicesReady) {
        const v = window.speechSynthesis.getVoices() || []
        voicesCache = v
        voicesReady = v.length > 0
        exposeDebugHelpers()
        emitChange()
        resolve(v)
      } else resolve(voicesCache)
      if (!voicesReady) voicesReadyPromise = null
    }, 2000)
  })

  return voicesReadyPromise
}

function voiceHasLocalService(v: SpeechSynthesisVoice): boolean {
  return Boolean((v as { localService?: boolean }).localService)
}

function scoreVoice(v: SpeechSynthesisVoice): number {
  const lang = (v.lang || '').toLowerCase()
  const name = v.name || ''
  let score = 0
  if (lang === 'zh-cn' || lang === 'zh_cn') score += 100
  else if (lang === 'zh-sg') score += 70
  else if (lang === 'zh-tw' || lang === 'zh-hk') score += 40
  else if (lang.startsWith('zh')) score += 30
  else return -1

  if (voiceHasLocalService(v)) score += 50

  // Yunxi 优先级拉满（默认偏好）
  if (/yunxi|云希/i.test(name)) score += 60
  if (NEURAL_KEYWORDS.some((k) => name.toLowerCase().includes(k.toLowerCase()))) score += 25
  if (CLASSIC_KEYWORDS.some((k) => name.toLowerCase().includes(k.toLowerCase()))) score += 10
  if (/natural|neural|online/i.test(name)) score += 10
  if (/^google/i.test(name) && !voiceHasLocalService(v)) score += 5

  return score
}

export function pickBestChineseVoice(voices?: SpeechSynthesisVoice[]): SpeechSynthesisVoice | null {
  const list = voices && voices.length ? voices : voicesCache
  if (!list || !list.length) return null
  const preferred = readPreferredVoiceName()
  if (preferred) {
    const match = list.find((v) => v.name === preferred)
    if (match) return match
  }
  let best: SpeechSynthesisVoice | null = null
  let bestScore = -Infinity
  for (const v of list) {
    const s = scoreVoice(v)
    if (s > bestScore) { bestScore = s; best = v }
  }
  return bestScore > 0 ? best : null
}

export function pickBestChineseVoiceSync(): SpeechSynthesisVoice | null {
  if (!hasSpeechSynthesis()) return null
  if (!voicesReady) {
    void loadVoicesOnce()
    const v = window.speechSynthesis.getVoices() || []
    if (v.length) {
      voicesCache = v
      voicesReady = true
      exposeDebugHelpers()
    }
  }
  return pickBestChineseVoice()
}

export function ensureVoicesLoaded(): Promise<SpeechSynthesisVoice[]> {
  return loadVoicesOnce()
}

export function hasYunxiOrXiaoxiaoAvailable(): boolean {
  const list = voicesCache || []
  return list.some((v) => /yunxi|xiaoxiao|云希|晓晓|natural|neural/i.test(v.name) && (v.lang || '').toLowerCase().startsWith('zh'))
}

export function hasAnyChineseLocalVoice(): boolean {
  const list = voicesCache || []
  return list.some((v) => (v.lang || '').toLowerCase().startsWith('zh') && voiceHasLocalService(v))
}

export interface TtsStatus {
  engineMode: TtsEngineMode
  effectiveEngine: 'system' | 'offline' | 'online'
  onlineVoiceId: string
  systemVoice: string | null
  yunxiAvailable: boolean
  neuralAvailable: boolean
  anyChineseLocal: boolean
  offlineReady: boolean
  offlineLoading: boolean
  offlineProgress: number
  bannerDismissed: boolean
}

export function getTtsStatus(): TtsStatus {
  const engineMode = getEngineMode()
  const v = pickBestChineseVoiceSync()
  const neural = hasYunxiOrXiaoxiaoAvailable()
  const offlineReadyNow = isOfflineReady()
  const onlineVid = getOnlineVoiceId()
  let effective: 'system' | 'offline' | 'online'
  if (engineMode === 'online') effective = 'online'
  else if (engineMode === 'offline') effective = offlineReadyNow ? 'offline' : 'system'
  else if (engineMode === 'system') effective = 'system'
  else {
    effective = offlineReadyNow ? 'offline' : 'online'
  }
  return {
    engineMode,
    effectiveEngine: effective,
    onlineVoiceId: onlineVid,
    systemVoice: v ? `${v.name} (${v.lang})` : null,
    yunxiAvailable: !!v && /yunxi|云希/i.test(v.name),
    neuralAvailable: neural,
    anyChineseLocal: hasAnyChineseLocalVoice(),
    offlineReady: offlineReadyNow,
    offlineLoading: isOfflineLoading(),
    offlineProgress: getOfflineProgress(),
    bannerDismissed: isBannerDismissed(),
  }
}

function configureUtterance(u: SpeechSynthesisUtterance): SpeechSynthesisUtterance {
  u.lang = 'zh-CN'
  u.rate = getSpeechRate()
  u.pitch = 1
  const v = pickBestChineseVoiceSync()
  if (v) {
    u.voice = v
    if (v.lang) u.lang = v.lang
  }
  return u
}

export function createChineseUtterance(text: string): SpeechSynthesisUtterance {
  const u = new SpeechSynthesisUtterance(text)
  return configureUtterance(u)
}

async function fetchOnlineTtsDataUri(text: string, signal: AbortSignal): Promise<string> {
  const voice = getOnlineVoiceId()
  const rate = getSpeechRate()
  const ratePercent = Math.round(rate * 100) - 100

  await ensureTtsCsrfCookie(signal)
  signal.throwIfAborted()

  const res = await apiFetch('/api/tts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    signal,
    body: JSON.stringify({ text, lang: 'zh', voice, rate: `${ratePercent >= 0 ? '+' : ''}${ratePercent}%` }),
  })
  let json: Record<string, unknown> = {}
  try {
    json = asRecord(await res.json())
  } catch {
    json = {}
  }
  signal.throwIfAborted()
  if (!res.ok || !json.success) {
    throw new Error(asString(json.message) || `在线 TTS 失败（HTTP ${res.status}）`)
  }
  const ttsData = asRecord(json.data)
  const uri = ttsData.audioBase64
  if (!uri || typeof uri !== 'string') {
    throw new Error('在线 TTS 响应缺少音频')
  }
  return uri
}

async function ensureTtsCsrfCookie(signal: AbortSignal): Promise<void> {
  if (typeof window === 'undefined') return
  if (readCsrfTokenFromCookie()) return
  try {
    await apiFetch('/api/health', { method: 'GET', timeoutMs: 5_000, signal })
  } catch {
    /* best-effort: the following POST will surface the actual TTS error */
  }
}

/** 单句合成上限：过长会拉高首字延迟，过短又会句间停顿明显。 */
const SPEECH_CHUNK_MAX_CHARS = 48
const SPEECH_CHUNK_MIN_CHARS = 12
const SENTENCE_BREAK = /[。！？；!?;…\n]+/

/** 把回复切成便于「边合成边播」的句子块；短句合并，长句按标点截断。 */
export function splitSpeechChunks(text: string): string[] {
  const plain = String(text || '').trim()
  if (!plain) return []
  const sentences: string[] = []
  let buffer = ''
  for (const piece of plain.split(SENTENCE_BREAK)) {
    const body = piece.trim()
    if (!body) continue
    buffer = buffer ? `${buffer}，${body}` : body
    if (buffer.length >= SPEECH_CHUNK_MIN_CHARS) {
      sentences.push(buffer)
      buffer = ''
    }
  }
  if (buffer) sentences.push(buffer)
  const chunks: string[] = []
  for (const sentence of sentences) {
    for (let i = 0; i < sentence.length; i += SPEECH_CHUNK_MAX_CHARS) {
      chunks.push(sentence.slice(i, i + SPEECH_CHUNK_MAX_CHARS))
    }
  }
  return chunks
}

function playAudioUri(uri: string, signal: AbortSignal, onStart?: () => void): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    const a = new Audio(uri)
    onlineAudioEl = a
    let settled = false
    let loadTimer: ReturnType<typeof setTimeout> | undefined
    const finish = (error?: unknown) => {
      if (settled) return
      settled = true
      if (loadTimer) clearTimeout(loadTimer)
      signal.removeEventListener('abort', onAbort)
      a.onended = a.onerror = a.onplaying = null
      if (onlineAudioEl === a) onlineAudioEl = null
      if (error) {
        a.pause()
        a.src = ''
        reject(error)
      } else resolve()
    }
    const onAbort = () => finish(signal.reason)
    // Limit loading only; a long, playing message must be allowed to finish.
    loadTimer = setTimeout(() => finish(new DOMException('TTS audio load timeout', 'TimeoutError')), 15_000)
    signal.addEventListener('abort', onAbort, { once: true })
    a.onplaying = () => { clearTimeout(loadTimer); onStart?.() }
    a.onended = () => finish()
    a.onerror = () => finish(new Error('音频播放失败'))
    void a.play().catch(finish)
  })
}

async function playOnlineTts(text: string, controller: AbortController, onStart?: () => void): Promise<void> {
  const onlineController = new AbortController()
  const onStop = () => onlineController.abort(controller.signal.reason)
  controller.signal.addEventListener('abort', onStop, { once: true })
  const { signal } = onlineController
  try {
    const chunks = splitSpeechChunks(text)
    if (!chunks.length) return
    // 先合成第一块并立即播放；播放期间并行合成下一块，首字延迟只取决于最短一块。
    const synth = (chunk: string): Promise<string> => {
      // Include CSRF and response-body reads in the synthesis budget (MiMo 8s + Edge 15s).
      const timer = setTimeout(() => onlineController.abort(new DOMException('TTS synthesis timeout', 'TimeoutError')), 30_000)
      const pending = fetchOnlineTtsDataUri(chunk, signal).finally(() => clearTimeout(timer))
      // 预取失败不能变成未处理的 rejection：真正 await 时仍会抛出。
      pending.catch(() => {})
      return pending
    }
    let next = synth(chunks[0])
    for (let i = 0; i < chunks.length; i += 1) {
      const uri = await next
      signal.throwIfAborted()
      next = i + 1 < chunks.length ? synth(chunks[i + 1]) : Promise.resolve('')
      await playAudioUri(uri, signal, i === 0 ? onStart : undefined)
    }
  } finally {
    controller.signal.removeEventListener('abort', onStop)
  }
}

function waitForSpeech<T>(promise: Promise<T>, signal: AbortSignal): Promise<T> {
  if (signal.aborted) return Promise.reject(signal.reason)
  return new Promise<T>((resolve, reject) => {
    const onAbort = () => reject(signal.reason)
    signal.addEventListener('abort', onAbort, { once: true })
    promise.then(resolve, reject).finally(() => signal.removeEventListener('abort', onAbort))
  })
}

async function speakWithSystemVoice(text: string, controller: AbortController): Promise<boolean> {
  if (!hasSpeechSynthesis()) return false
  let voices = voicesCache
  if (!voices.length) voices = await waitForSpeech(loadVoicesOnce(), controller.signal).catch(() => [])
  if (speechController !== controller || !pickBestChineseVoice(voices)) return false
  return new Promise<boolean>((resolve) => {
    let settled = false
    const u = createChineseUtterance(text)
    let timer: ReturnType<typeof setTimeout>
    let started = false
    const finish = (ok: boolean) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      controller.signal.removeEventListener('abort', onAbort)
      u.onstart = u.onend = u.onerror = null
      resolve(ok)
    }
    const onAbort = () => finish(false)
    const onTimeout = () => {
      if (started && (window.speechSynthesis.speaking || window.speechSynthesis.pending)) {
        timer = setTimeout(onTimeout, 60_000)
        return
      }
      finish(false)
      try { window.speechSynthesis.cancel() } catch { return }
    }
    timer = setTimeout(onTimeout, 60_000)
    try {
      if (!controller.signal.aborted) controller.signal.addEventListener('abort', onAbort, { once: true })
      u.onstart = () => {
        started = true
      }
      u.onend = () => finish(true)
      u.onerror = () => finish(false)
      window.speechSynthesis.speak(u)
    } catch {
      finish(false)
    }
  })
}

async function speakWithFallback(text: string, controller: AbortController): Promise<boolean> {
  if (isOfflineReady()) {
    try {
      const { audio, samplingRate } = await waitForSpeech(synthesizeOffline(text, controller.signal), controller.signal)
      if (speechController !== controller) return false
      await waitForSpeech(playOfflinePcm(audio, samplingRate, controller.signal), controller.signal)
      return true
    } catch {
      /* fall through to system voice */
    }
  }
  if (speechController !== controller) return false
  return speakWithSystemVoice(text, controller)
}

/** 朗读完成、失败或主动停止后结束；失败统一提示，取消静默。 */
export async function speakText(text: string, options?: { onEnd?: () => void; onError?: (e: unknown) => void; onStart?: () => void; silent?: boolean }): Promise<boolean> {
  const plain = String(text || '').trim()
  if (!plain) { options?.onEnd?.(); return false }
  stopSpeaking()
  const controller = new AbortController()
  speechController = controller
  let completed = false
  try {
    if (getEngineMode() === 'offline') {
      const { audio, samplingRate } = await waitForSpeech(synthesizeOffline(plain, controller.signal), controller.signal)
      controller.signal.throwIfAborted()
      options?.onStart?.()
      await waitForSpeech(playOfflinePcm(audio, samplingRate, controller.signal), controller.signal)
      completed = true
    } else {
      await playOnlineTts(plain, controller, options?.onStart)
      completed = true
    }
  } catch (e) {
    const error = controller.signal.aborted ? controller.signal.reason : e
    const abortedByUser = controller.signal.aborted && error?.name !== 'TimeoutError'
    const message = String(error?.message || '')
    const playbackError = error?.name === 'NotAllowedError'
      || error?.name === 'AbortError'
      || message.includes('音频播放失败')
      || message.includes('play rejected')
    const offlineMode = getEngineMode() === 'offline'
    const fallbackOk = getEngineMode() !== 'system' || offlineMode || abortedByUser || playbackError ? false : await speakWithFallback(plain, controller)
    if (!fallbackOk) {
      if (!options?.silent && speechController === controller && (!controller.signal.aborted || error?.name === 'TimeoutError')) {
        showAppToast(error?.name === 'NotAllowedError'
          ? '语音播放被浏览器阻止，请点击朗读按钮重试。'
          : error?.name === 'TimeoutError' ? '语音服务响应超时，请稍后重试。' : '语音播放失败，请稍后重试。')
        options?.onError?.(error)
      }
    }
  } finally {
    if (speechController === controller) speechController = null
    options?.onEnd?.()
  }
  return completed
}

export function stopSpeaking(): void {
  const controller = speechController
  speechController = null
  controller?.abort()
  stopOnlinePlayback()
  // Only cancel speechSynthesis when it is actually active; unconditional cancel
  // releases the Windows "communications" audio session even when idle, which
  // causes other apps' volumes to snap back (OS audio-ducking restore).
  try {
    if (hasSpeechSynthesis() && (window.speechSynthesis.speaking || window.speechSynthesis.pending)) {
      window.speechSynthesis.cancel()
    }
  } catch { /* ignore */ }
  try { stopOffline() } catch { /* ignore */ }
}

/** 启动离线包下载（包装 offlineTts.ensureOfflineReady，加状态广播）。 */
export async function startOfflineDownload(onProgress?: (p: number) => void): Promise<void> {
  await ensureOfflineReady((p) => {
    onProgress?.(p)
    emitChange()
  })
  emitChange()
}

/** 后台预热离线语音包；失败只记录日志，不打扰聊天界面。 */
export async function preloadOfflineTts(): Promise<void> {
  if (offlineWarmupStarted || isOfflineReady() || isOfflineLoading()) return
  offlineWarmupStarted = true
  try {
    await startOfflineDownload()
  } catch (e) {
    offlineWarmupStarted = false
    console.warn('[tts] offline preload failed:', e)
    emitChange()
  }
}

function exposeDebugHelpers(): void {
  if (debugExposed) return
  if (typeof window === 'undefined') return
  debugExposed = true
  try {
    ;(window as Window & { __xcagiTts?: unknown }).__xcagiTts = {
      list(): Array<{ name: string; lang: string; localService: boolean; default: boolean }> {
        return (voicesCache || []).map((v) => ({
          name: v.name,
          lang: v.lang,
          localService: voiceHasLocalService(v),
          default: v.default === true,
        }))
      },
      current(): string | null {
        const v = pickBestChineseVoice()
        return v ? `${v.name} (${v.lang})` : null
      },
      status(): TtsStatus { return getTtsStatus() },
      preferred(): string { return readPreferredVoiceName() },
      set(name: string): string {
        writePreferredVoiceName(String(name || ''))
        const v = pickBestChineseVoice()
        return v ? `已切换到：${v.name} (${v.lang})` : '未找到指定语音，已保存偏好'
      },
      reset(): string { writePreferredVoiceName(''); const v = pickBestChineseVoice(); return v ? `已重置，自动选用：${v.name} (${v.lang})` : '已重置' },
      setEngine: setEngineMode,
      onlineVoice: getOnlineVoiceId,
      setOnlineVoice: setOnlineVoiceId,
      download: startOfflineDownload,
      getRate: getSpeechRate,
      setRate: setSpeechRate,
      clean: cleanTextForSpeech,
      debug: {
        getStatus: () => getTtsStatus(),
        getEngineMode: getEngineMode,
        isOfflineReady,
        isOfflineLoading,
        getOfflineProgress,
      },
    }
  } catch { /* ignore */ }
}

// 模块加载时预热
if (hasSpeechSynthesis()) {
  void loadVoicesOnce()
}
if (typeof window !== 'undefined' && AUTO_PRELOAD_OFFLINE_TTS) {
  window.setTimeout(() => {
    void preloadOfflineTts()
  }, 1500)
}
