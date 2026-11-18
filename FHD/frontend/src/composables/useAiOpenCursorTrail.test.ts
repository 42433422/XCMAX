import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: Error) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function deferLibrary() {
  const started = deferred<void>()
  const loaded = deferred<{ fairyDustCursor: ReturnType<typeof vi.fn> }>()
  vi.doMock('cursor-effects', async () => {
    started.resolve()
    return loaded.promise
  })
  return { started: started.promise, ...loaded }
}

function library() {
  const destroy = vi.fn()
  const fairyDustCursor = vi.fn(function () { return { destroy } })
  return { fairyDustCursor, destroy }
}

describe('AIOPEN cursor trail lifecycle', () => {
  let trail: typeof import('./useAiOpenCursorTrail')
  let events: MouseEvent[]
  const capture = (event: Event) => events.push(event as MouseEvent)

  beforeEach(async () => {
    vi.resetModules()
    vi.stubEnv('MODE', 'development')
    events = []
    document.addEventListener('mousemove', capture)
    document.addEventListener('mousedown', capture)
    trail = await import('./useAiOpenCursorTrail')
  })

  afterEach(() => {
    trail.disableTrail()
    document.removeEventListener('mousemove', capture)
    document.removeEventListener('mousedown', capture)
    vi.doUnmock('cursor-effects')
    vi.unstubAllEnvs()
  })

  it('does not create an effect or emit events when disabled during library loading', async () => {
    const load = deferLibrary()
    const cursor = library()
    const pending = trail.ensureTrail()
    await load.started

    trail.disableTrail()
    load.resolve(cursor)
    await pending
    expect(cursor.fairyDustCursor).not.toHaveBeenCalled()
    trail.moveTrail(12, 34)
    trail.pulseTrail(56, 78)
    expect(events).toEqual([])
  })

  it('shares one active effect and stops emitting after destroying it once', async () => {
    const load = deferLibrary()
    const cursor = library()
    const pending = trail.ensureTrail()
    const concurrent = trail.ensureTrail()
    await load.started
    load.resolve(cursor)
    await Promise.all([pending, concurrent])
    await trail.ensureTrail()

    expect(cursor.fairyDustCursor).toHaveBeenCalledTimes(1)
    trail.disableTrail()
    trail.disableTrail()
    trail.moveTrail(90, 12)
    trail.pulseTrail(34, 56)
    expect(cursor.destroy).toHaveBeenCalledTimes(1)
    expect(events).toEqual([])
  })

  it('does not release a newer pending load when a retired import finishes', async () => {
    const retiredLoad = deferLibrary()
    const retiredCursor = library()
    const retiredPending = trail.ensureTrail()
    await retiredLoad.started
    trail.disableTrail()

    const currentLoad = deferLibrary()
    const currentCursor = library()
    const currentPending = trail.ensureTrail()
    await currentLoad.started
    retiredLoad.resolve(retiredCursor)
    await retiredPending
    const concurrent = trail.ensureTrail()
    currentLoad.resolve(currentCursor)
    await Promise.all([currentPending, concurrent])

    expect(retiredCursor.fairyDustCursor).not.toHaveBeenCalled()
    expect(currentCursor.fairyDustCursor).toHaveBeenCalledTimes(1)
    trail.disableTrail()
    expect(currentCursor.destroy).toHaveBeenCalledTimes(1)
    trail.moveTrail(12, 34)
    trail.pulseTrail(56, 78)
    expect(events).toEqual([])
  })

  it('keeps the new effect alive when a retired import rejects', async () => {
    const retiredLoad = deferLibrary()
    const retiredPending = trail.ensureTrail()
    await retiredLoad.started
    trail.disableTrail()

    const currentLoad = deferLibrary()
    const currentCursor = library()
    const currentPending = trail.ensureTrail()
    await currentLoad.started
    currentLoad.resolve(currentCursor)
    await currentPending
    retiredLoad.reject(new Error('Retired library load failed'))
    await retiredPending
    await trail.ensureTrail()

    expect(currentCursor.fairyDustCursor).toHaveBeenCalledTimes(1)
    trail.disableTrail()
    expect(currentCursor.destroy).toHaveBeenCalledTimes(1)
    trail.moveTrail(12, 34)
    trail.pulseTrail(56, 78)
    expect(events).toEqual([])
  })
})
