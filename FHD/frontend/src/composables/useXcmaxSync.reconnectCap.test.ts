import { afterEach, describe, expect, it, vi } from 'vitest'
import { useXcmaxSync } from './useXcmaxSync'

class TestEventSource {
  static instances: TestEventSource[] = []
  url: string
  onerror: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  close = vi.fn()
  constructor(url: string) {
    this.url = url
    TestEventSource.instances.push(this)
  }
}

describe('xcmax sync reconnect cap', () => {
  afterEach(() => {
    useXcmaxSync().stop()
    vi.useRealTimers()
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('enters a recoverable cooldown after exhausting retries and resumes from its cursor', () => {
    vi.useFakeTimers()
    TestEventSource.instances = []
    vi.stubGlobal('EventSource', TestEventSource)
    const sync = useXcmaxSync()
    localStorage.setItem('xcmax_sync_cursor', '42')
    sync.start()
    for (let i = 0; i < 12; i += 1) {
      const current = TestEventSource.instances.at(-1)
      expect(current).toBeTruthy()
      current?.onerror?.(new Event('error'))
      vi.advanceTimersByTime(30_000)
    }
    const capped = TestEventSource.instances.length
    TestEventSource.instances.at(-1)?.onerror?.(new Event('error'))
    vi.advanceTimersByTime(30_000)
    expect(TestEventSource.instances.length).toBe(capped)
    expect(capped).toBe(13)
    vi.advanceTimersByTime(30_000)
    expect(TestEventSource.instances).toHaveLength(14)
    expect(TestEventSource.instances.at(-1)?.url).toContain('since_cursor=42')
    TestEventSource.instances.at(-1)?.onmessage?.(new MessageEvent('message', { data: '{"type":"connected"}' }))
    TestEventSource.instances.at(-1)?.onerror?.(new Event('error'))
    vi.advanceTimersByTime(3000)
    expect(TestEventSource.instances).toHaveLength(15)
  })

  it.each(['online', 'xcagi:backend-ready'])('recovers immediately on %s and ignores retired callbacks', event => {
    vi.useFakeTimers()
    TestEventSource.instances = []
    vi.stubGlobal('EventSource', TestEventSource)
    const sync = useXcmaxSync()
    sync.start()
    const previous = TestEventSource.instances.at(-1)!
    const oldError = previous.onerror!
    const oldMessage = previous.onmessage!
    oldError(new Event('error'))
    window.dispatchEvent(new Event(event))
    expect(TestEventSource.instances).toHaveLength(2)
    const current = TestEventSource.instances.at(-1)!
    current.onmessage?.(new MessageEvent('message', { data: '{"type":"heartbeat","cursor":90}' }))
    oldMessage(new MessageEvent('message', { data: '{"type":"heartbeat","cursor":1}' }))
    oldError(new Event('error'))
    expect(sync.readCursor()).toBe(90)
    expect(current.close).not.toHaveBeenCalled()
    sync.stop()
    window.dispatchEvent(new Event(event))
    vi.advanceTimersByTime(120_000)
    expect(TestEventSource.instances).toHaveLength(2)
  })
})
