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
