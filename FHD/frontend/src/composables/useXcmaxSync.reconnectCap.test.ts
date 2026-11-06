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
  })

  it('stops scheduling after the reconnect budget is spent', () => {
    vi.useFakeTimers()
    TestEventSource.instances = []
    vi.stubGlobal('EventSource', TestEventSource)
    const sync = useXcmaxSync()
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
  })
})