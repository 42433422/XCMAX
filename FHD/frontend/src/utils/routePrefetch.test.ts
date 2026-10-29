import { describe, expect, it } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { prefetchRouteChunks } from './routePrefetch'

describe('route prefetch concurrency', () => {
  it('keeps at most four unresolved imports even when every idle callback runs', async () => {
    let active = 0, peak = 0, started = 0
    const releases: Array<() => void> = []
    const jobs = Array.from({ length: 40 }, () => () => new Promise<void>((resolve) => {
      started++; active++; peak = Math.max(peak, active)
      releases.push(() => { active--; resolve() })
    }))
    const done = prefetchRouteChunks(jobs, (task) => task())
    await flushPromises()
    expect(started).toBe(4)
    releases.shift()!()
    await flushPromises()
    expect(started).toBe(5)
    while (releases.length) {
      releases.shift()!()
      await flushPromises()
    }
    await done
    expect(started).toBe(40)
    expect(peak).toBe(4)
    expect(active).toBe(0)
  })

  it('deduplicates loaders and recovers worker slots from sync/async failures', async () => {
    let completed = 0
    const success = async () => { completed++ }
    await prefetchRouteChunks([() => { throw new Error('missing') }, () => Promise.reject('offline'), success, success], (task) => task(), 1)
    expect(completed).toBe(1)
  })
})
