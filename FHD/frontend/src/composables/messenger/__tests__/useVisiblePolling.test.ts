import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope } from 'vue'
import { reconcileImSnapshot, useVisiblePolling } from '../useVisiblePolling'

beforeEach(() => vi.useFakeTimers())
afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers() })

describe('visible adaptive polling', () => {
  it('reduces idle reads, stops in the background, and refreshes immediately on return', async () => {
    const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
    const read = vi.fn().mockResolvedValue(false)
    const scope = effectScope()
    const poll = scope.run(() => useVisiblePolling(read))!
    poll.start()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(read).toHaveBeenCalledTimes(4) // Fixed 2.5-second polling previously made 24 reads.
    visibility.mockReturnValue('hidden')
    document.dispatchEvent(new Event('visibilitychange'))
    await vi.advanceTimersByTimeAsync(120_000)
    expect(read).toHaveBeenCalledTimes(4)
    visibility.mockReturnValue('visible')
    document.dispatchEvent(new Event('visibilitychange'))
    expect(read).toHaveBeenCalledTimes(5)
    await vi.advanceTimersByTimeAsync(0)
    scope.stop()
    document.dispatchEvent(new Event('visibilitychange'))
    await vi.advanceTimersByTimeAsync(120_000)
    expect(read).toHaveBeenCalledTimes(5)
  })

  it('does not overlap a slow read and retires a pending resume when stopped', async () => {
    const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
    let resolve!: (changed: boolean) => void
    const read = vi.fn(() => new Promise<boolean>((done) => { resolve = done }))
    const poll = useVisiblePolling(read)
    poll.start()
    await vi.advanceTimersByTimeAsync(120_000)
    expect(read).toHaveBeenCalledTimes(1)
    visibility.mockReturnValue('hidden'); document.dispatchEvent(new Event('visibilitychange'))
    visibility.mockReturnValue('visible'); document.dispatchEvent(new Event('visibilitychange'))
    expect(read).toHaveBeenCalledTimes(1)
    resolve(false)
    await vi.advanceTimersByTimeAsync(0)
    expect(read).toHaveBeenCalledTimes(2)
    poll.stop()
    resolve(true)
    await vi.advanceTimersByTimeAsync(120_000)
    expect(read).toHaveBeenCalledTimes(2)
  })

  it('recovers from errors and resets the delay after a changed response', async () => {
    const read = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(true).mockResolvedValue(false)
    const poll = useVisiblePolling(read)
    poll.start()
    await vi.advanceTimersByTimeAsync(7499)
    expect(read).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(read).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(2500)
    expect(read).toHaveBeenCalledTimes(3)
    poll.stop()
  })

  it('reuses unchanged snapshots/rows but applies edits, removals and additions', () => {
    const current = [{ id: 1, body: 'one' }, { id: 2, body: 'two' }]
    expect(reconcileImSnapshot(current, current.map((row) => ({ ...row })))).toEqual({ items: current, changed: false })
    expect(reconcileImSnapshot(current, current.map((row) => ({ ...row }))).items).toBe(current)
    const updated = reconcileImSnapshot(current, [{ id: 1, body: 'one' }, { id: 2, body: 'edited' }, { id: 3, body: 'new' }])
    expect(updated.changed).toBe(true)
    expect(updated.items[0]).toBe(current[0])
    expect(updated.items[1].body).toBe('edited')
    expect(reconcileImSnapshot(updated.items, [{ id: 3, body: 'new' }]).items).toEqual([{ id: 3, body: 'new' }])
  })
})
