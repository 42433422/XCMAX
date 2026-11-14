/**
 * 语音链路可观测性与能力探测。
 *
 * 只记录计数、耗时和失败原因，不保存音频内容与转写正文，
 * 数据仅保留在内存环形缓冲中，供设置面板与 DevTools 排查使用。
 */

export interface VoiceTiming {
  count: number
  totalMs: number
  maxMs: number
}

export interface VoiceMetricsSnapshot {
  counters: Record<string, number>
  timings: Record<string, VoiceTiming>
  lastEvent: { name: string; detail?: string; at: number } | null
}

export interface VoiceSupport {
  microphone: boolean
  recorder: boolean
  streaming: boolean
  websocket: boolean
  speechSynthesis: boolean
}

const counters: Record<string, number> = {}
const timings: Record<string, VoiceTiming> = {}
const eventRing: Array<{ name: string; detail?: string; at: number }> = []
const EVENT_LIMIT = 40

export function recordVoiceCount(name: string): void {
  counters[name] = (counters[name] || 0) + 1
}

export function recordVoiceTiming(name: string, ms: number): void {
  if (!Number.isFinite(ms) || ms < 0) return
  const entry = (timings[name] ||= { count: 0, totalMs: 0, maxMs: 0 })
  entry.count += 1
  entry.totalMs += ms
  entry.maxMs = Math.max(entry.maxMs, ms)
}

export function recordVoiceEvent(name: string, detail?: string): void {
  eventRing.push({ name, detail, at: Date.now() })
  if (eventRing.length > EVENT_LIMIT) eventRing.splice(0, eventRing.length - EVENT_LIMIT)
  try {
    ;(window as Window & { __xcagiVoiceMetrics?: unknown }).__xcagiVoiceMetrics = {
      snapshot: getVoiceMetrics,
      events: () => eventRing.slice(),
      support: getVoiceSupport,
    }
  } catch { /* ignore */ }
}

export function getVoiceMetrics(): VoiceMetricsSnapshot {
  return {
    counters: { ...counters },
    timings: Object.fromEntries(
      Object.entries(timings).map(([key, value]) => [key, { ...value }]),
    ),
    lastEvent: eventRing.length ? { ...eventRing[eventRing.length - 1] } : null,
  }
}

export function resetVoiceMetrics(): void {
  for (const key of Object.keys(counters)) delete counters[key]
  for (const key of Object.keys(timings)) delete timings[key]
  eventRing.length = 0
}

/** 首轮通话前的能力探测：缺失项直接反映为可见降级提示。 */
export function getVoiceSupport(): VoiceSupport {
  const hasWindow = typeof window !== 'undefined'
  return {
    microphone: Boolean(hasWindow && navigator.mediaDevices?.getUserMedia),
    recorder: Boolean(hasWindow && typeof window.MediaRecorder !== 'undefined'),
    streaming: Boolean(hasWindow && typeof WebSocket !== 'undefined'),
    websocket: Boolean(hasWindow && typeof WebSocket !== 'undefined'),
    speechSynthesis: Boolean(hasWindow && 'speechSynthesis' in window),
  }
}
