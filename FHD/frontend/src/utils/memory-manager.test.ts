import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  ResourceManager,
  createResourceManager,
  globalResourceManager,
  useCleanup,
  cleanupCanvas,
  cleanupAnimationFrame,
  cleanupInterval,
  cleanupTimeout,
  cleanupEventListener,
  cleanupObject,
} from './memory-manager'

describe('ResourceManager', () => {
  let mgr: ResourceManager

  beforeEach(() => {
    mgr = createResourceManager()
  })

  it('registers and retrieves resources', () => {
    const obj = { id: 1 }
    expect(mgr.register('a', obj, 'test')).toBe(true)
    expect(mgr.get('a')).toBe(obj)
    expect(mgr.has('a')).toBe(true)
  })

  it('replaces duplicate registration', () => {
    const dispose = vi.fn()
    mgr.register('dup', { dispose }, 'generic')
    mgr.register('dup', { value: 2 }, 'generic')
    expect(dispose).toHaveBeenCalled()
    expect(mgr.get('dup')).toEqual({ value: 2 })
  })

  it('refuses registration after dispose', () => {
    mgr.dispose()
    expect(mgr.register('x', {})).toBe(false)
  })

  it('releases disposable resources', () => {
    const dispose = vi.fn()
    mgr.register('d', { dispose })
    expect(mgr.release('d')).toBe(true)
    expect(dispose).toHaveBeenCalled()
    expect(mgr.has('d')).toBe(false)
  })

  it('releases HTMLElement resources', () => {
    const el = document.createElement('div')
    document.body.appendChild(el)
    mgr.register('el', el, 'dom')
    mgr.release('el')
    expect(document.body.contains(el)).toBe(false)
  })

  it('releaseByType and releaseAll', () => {
    mgr.register('a', {}, 'type-a')
    mgr.register('b', {}, 'type-b')
    expect(mgr.releaseByType('type-a')).toBe(1)
    expect(mgr.has('a')).toBe(false)
    mgr.register('c', {}, 'type-c')
    const count = mgr.releaseAll()
    expect(count).toBeGreaterThanOrEqual(1)
    expect(mgr.has('c')).toBe(false)
  })

  it('manages listeners and timers', () => {
    const target = new EventTarget()
    const handler = vi.fn()
    const key = mgr.addListener(target, 'click', handler)
    target.dispatchEvent(new Event('click'))
    expect(handler).toHaveBeenCalled()
    expect(mgr.removeListener(key)).toBe(true)

    const timer = window.setInterval(() => {}, 10000)
    mgr.registerTimer('t', timer)
    mgr.clearTimer('t')
    mgr.clearAllTimers()
  })

  it('disconnects observers on releaseAll', () => {
    const obs = { disconnect: vi.fn() } as unknown as MutationObserver
    mgr.registerObserver(obs)
    mgr.releaseAll()
    expect(obs.disconnect).toHaveBeenCalled()
  })
})

describe('useCleanup', () => {
  it('runs registered cleanup fns', () => {
    const fn = vi.fn()
    const { register, cleanup } = useCleanup()
    register(fn)
    cleanup()
    expect(fn).toHaveBeenCalled()
    cleanup()
  })

  it('ignores non-function register', () => {
    const { register, cleanup } = useCleanup()
    register('bad' as unknown as () => void)
    expect(() => cleanup()).not.toThrow()
  })
})

describe('cleanup helpers', () => {
  it('cleanupCanvas no-ops when ctx is null', () => {
    cleanupCanvas(null)
  })

  it('cleanupAnimationFrame cancels id', () => {
    const spy = vi.spyOn(globalThis, 'cancelAnimationFrame')
    cleanupAnimationFrame(42)
    expect(spy).toHaveBeenCalledWith(42)
    cleanupAnimationFrame(0)
    spy.mockRestore()
  })

  it('cleanupInterval and cleanupTimeout', () => {
    const i = window.setInterval(() => {}, 10000)
    const t = window.setTimeout(() => {}, 10000)
    cleanupInterval(i)
    cleanupTimeout(t)
    cleanupInterval(null)
    cleanupTimeout(undefined)
  })

  it('cleanupEventListener removes handler', () => {
    const target = new EventTarget()
    const handler = vi.fn()
    target.addEventListener('evt', handler)
    cleanupEventListener(target, 'evt', handler)
    target.dispatchEvent(new Event('evt'))
    expect(handler).not.toHaveBeenCalled()
    cleanupEventListener(null, null, null)
  })

  it('cleanupObject nulls nested keys', () => {
    const obj: Record<string, unknown> = { a: { b: 1 }, c: 'x' }
    cleanupObject(obj)
    expect(obj.a).toBeNull()
    expect(obj.c).toBeNull()
    cleanupObject(null as unknown as Record<string, unknown>)
  })
})

describe('globalResourceManager', () => {
  it('is a ResourceManager instance', () => {
    expect(globalResourceManager).toBeInstanceOf(ResourceManager)
  })
})

describe('resource cleanup guarantees', () => {
  it.each(['destroy', 'cleanup'] as const)('calls the %s protocol and forgets released resources', (method) => {
    const mgr = createResourceManager(), release = vi.fn()
    mgr.register('item', { [method]: release })
    expect(mgr.release('item')).toBe(true)
    expect(release).toHaveBeenCalledOnce()
    expect(mgr.release('item')).toBe(false)
    expect(mgr.get('item')).toBeNull()
  })
  it('still unregisters resources after disposal errors and runs all cleanup callbacks', () => {
    const error = new Error('dispose failed'), log = vi.spyOn(console, 'error').mockImplementation(() => {})
    const mgr = createResourceManager()
    mgr.register('broken', { dispose: () => { throw error } })
    expect(mgr.release('broken')).toBe(true); expect(mgr.has('broken')).toBe(false)
    expect(log).toHaveBeenCalledWith('ResourceManager: Error releasing resource "broken":', error)
    const cleanup = useCleanup(), next = vi.fn()
    cleanup.register(() => { throw error }); cleanup.register(next)
    cleanup.cleanup(); cleanup.cleanup()
    expect(next).toHaveBeenCalledOnce(); expect(log).toHaveBeenCalledWith('Cleanup error:', error)
    log.mockRestore()
  })
  it('releases listeners for only the registered event target', () => {
    const mgr = createResourceManager(), target = new EventTarget(), other = new EventTarget()
    const handler = vi.fn(), retained = vi.fn()
    mgr.addListener(target, 'release', handler, { capture: true })
    const retainedKey = mgr.addListener(other, 'retain', retained)
    mgr.register('target', target)
    mgr.release('target')
    target.dispatchEvent(new Event('release')); other.dispatchEvent(new Event('retain'))
    expect(handler).not.toHaveBeenCalled(); expect(retained).toHaveBeenCalledOnce()
    expect(mgr.removeListener('missing')).toBe(false)
    expect(mgr.removeListener(retainedKey)).toBe(true)
    other.dispatchEvent(new Event('retain')); expect(retained).toHaveBeenCalledOnce()
  })
  it('clears replaced timers, all timers and timers released with the manager', () => {
    vi.useFakeTimers()
    try {
      const mgr = createResourceManager(), expired = vi.fn(), current = vi.fn(), released = vi.fn()
      mgr.registerTimer('same', window.setInterval(expired, 10))
      mgr.registerTimer('same', window.setTimeout(current, 10))
      vi.advanceTimersByTime(10)
      expect(expired).not.toHaveBeenCalled(); expect(current).toHaveBeenCalledOnce()
      mgr.registerTimer('all', window.setInterval(expired, 10))
      mgr.clearAllTimers(); mgr.clearTimer('missing')
      mgr.registerTimer('release', window.setInterval(released, 10)); expect(mgr.releaseAll()).toBe(0)
      vi.advanceTimersByTime(100)
      expect(expired).not.toHaveBeenCalled(); expect(released).not.toHaveBeenCalled()
    } finally { vi.useRealTimers() }
  })
  it('disconnects all observers only once, including after a later release', () => {
    const mgr = createResourceManager(), disconnect = vi.fn()
    mgr.registerObserver({ disconnect } as unknown as MutationObserver)
    mgr.disconnectAllObservers(); mgr.disconnectAllObservers(); mgr.releaseAll()
    expect(disconnect).toHaveBeenCalledOnce()
  })
  it('clears a canvas before releasing its dimensions and handles an already empty canvas', () => {
    const canvas = document.createElement('canvas'); canvas.width = 640; canvas.height = 480
    const clearRect = vi.fn(), ctx = { canvas, clearRect } as unknown as CanvasRenderingContext2D
    cleanupCanvas(ctx)
    expect(clearRect).toHaveBeenCalledWith(0, 0, 640, 480)
    expect([canvas.width, canvas.height]).toEqual([0, 0])
    cleanupCanvas(ctx); expect(clearRect).toHaveBeenLastCalledWith(0, 0, 0, 0)
  })
})
