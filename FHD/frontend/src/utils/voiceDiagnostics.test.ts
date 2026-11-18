import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { getVoiceMetrics, recordVoiceCount, recordVoiceEvent, recordVoiceTiming, resetVoiceMetrics } from './voiceDiagnostics'

type Diagnostics = { events: () => Array<{ name: string; at: number }>; snapshot: typeof getVoiceMetrics }
const diagnostics = () => (window as Window & { __xcagiVoiceMetrics: Diagnostics }).__xcagiVoiceMetrics
beforeEach(resetVoiceMetrics)
afterEach(resetVoiceMetrics)

describe('voice diagnostics snapshots', () => {
  it('aggregates valid timings, ignores invalid samples, and returns independent snapshots', () => {
    recordVoiceCount('started'); recordVoiceCount('started')
    for (const duration of [10, 30, -1, NaN, Infinity]) recordVoiceTiming('latency', duration)
    recordVoiceEvent('connected', 'ready')
    const snapshot = getVoiceMetrics()
    expect(snapshot.counters).toEqual({ started: 2 })
    expect(snapshot.timings).toEqual({ latency: { count: 2, totalMs: 40, maxMs: 30 } })
    expect(snapshot.lastEvent).toMatchObject({ name: 'connected', detail: 'ready' })
    snapshot.counters.started = 100
    snapshot.timings.latency.maxMs = 100
    snapshot.lastEvent!.name = 'changed'
    expect(diagnostics().snapshot()).toMatchObject({ counters: { started: 2 }, timings: { latency: { maxMs: 30 } }, lastEvent: { name: 'connected' } })
  })

  it('retains only the most recent forty events and resets all metrics', () => {
    for (let n = 0; n < 45; n++) recordVoiceEvent(`event-${n}`)
    const events = diagnostics().events()
    expect(events).toHaveLength(40)
    expect(events[0].name).toBe('event-5')
    expect(events[39].name).toBe('event-44')
    events.pop()
    expect(diagnostics().events()).toHaveLength(40)
    recordVoiceCount('completed'); recordVoiceTiming('latency', 3)
    resetVoiceMetrics()
    expect(getVoiceMetrics()).toEqual({ counters: {}, timings: {}, lastEvent: null })
    expect(diagnostics().events()).toEqual([])
  })
})
