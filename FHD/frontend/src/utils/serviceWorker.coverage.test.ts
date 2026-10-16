import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

let api: typeof import('./serviceWorker')
let sw: EventTarget & { controller: { postMessage: ReturnType<typeof vi.fn> } | null; register: ReturnType<typeof vi.fn>; getRegistrations: ReturnType<typeof vi.fn> }
let worker: EventTarget & { state: string }
let registration: EventTarget & { installing: typeof worker | null; update: ReturnType<typeof vi.fn>; unregister: ReturnType<typeof vi.fn> }
let channel: { port1: { onmessage: ((event: { data: object }) => void) | null }; port2: object }
const reload = vi.fn()
const originalLocation = Object.getOwnPropertyDescriptor(window, 'location')!
const originalSw = Object.getOwnPropertyDescriptor(navigator, 'serviceWorker')

beforeEach(async () => {
  vi.resetModules()
  vi.useFakeTimers()
  vi.stubEnv('DEV', false)
  vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '0')
  Object.defineProperty(window, 'location', { configurable: true, value: { hostname: 'app.example.com', reload } })
  worker = Object.assign(new EventTarget(), { state: 'installing' })
  registration = Object.assign(new EventTarget(), { installing: worker, update: vi.fn().mockResolvedValue(undefined), unregister: vi.fn().mockResolvedValue(true) })
  sw = Object.assign(new EventTarget(), { controller: { postMessage: vi.fn() }, register: vi.fn().mockResolvedValue(registration), getRegistrations: vi.fn().mockResolvedValue([registration]) })
  Object.defineProperty(navigator, 'serviceWorker', { configurable: true, value: sw })
  vi.stubGlobal('MessageChannel', class {
    port1 = { onmessage: null }
    port2 = {}
    constructor() { channel = { port1: this.port1, port2: this.port2 } }
  })
  vi.spyOn(console, 'warn').mockImplementation(() => {})
  vi.spyOn(console, 'error').mockImplementation(() => {})
  vi.spyOn(console, 'log').mockImplementation(() => {})
  api = await import('./serviceWorker')
})
afterEach(() => {
  api.swManager.destroy()
  vi.clearAllTimers()
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  Object.defineProperty(window, 'location', originalLocation)
  if (originalSw) Object.defineProperty(navigator, 'serviceWorker', originalSw)
  else Reflect.deleteProperty(navigator, 'serviceWorker')
})

describe('service worker public lifecycle', () => {
  it('registers, publishes immutable status, observes installation and checks hourly until destroyed', async () => {
    const listener = vi.fn()
    const off = api.swManager.onChange(listener)
    expect(typeof off).toBe('function')
    expect(await api.swManager.checkForUpdate()).toBe(false)
    const status = await api.initServiceWorker()
    expect(status).toMatchObject({ registered: true, supported: true, controller: true })
    expect(status.lastUpdate).toBe(Date.now())
    expect(sw.register).toHaveBeenCalledWith('/sw.js', { scope: '/', updateViaCache: 'all' })
    status.registered = false
    expect(api.swManager.status.registered).toBe(true)
    expect(listener).toHaveBeenCalledWith(expect.objectContaining({ registered: true }))
    sw.dispatchEvent(new Event('controllerchange'))
    expect(api.swManager.status.controller).toBe(true)
    registration.dispatchEvent(new Event('updatefound'))
    listener.mockClear()
    worker.dispatchEvent(new Event('statechange'))
    expect(listener).not.toHaveBeenCalled()
    worker.state = 'installed'
    worker.dispatchEvent(new Event('statechange'))
    expect(listener).toHaveBeenCalledOnce()
    sw.controller = null
    worker.dispatchEvent(new Event('statechange'))
    expect(listener).toHaveBeenCalledOnce()
    registration.installing = null
    registration.dispatchEvent(new Event('updatefound'))
    await vi.advanceTimersByTimeAsync(3_600_000)
    expect(registration.update).toHaveBeenCalledOnce()
    expect(await api.swManager.checkForUpdate()).toBe(true)
    registration.update.mockRejectedValue(new Error('update fail'))
    expect(await api.swManager.checkForUpdate()).toBe(false)
    expect(console.warn).toHaveBeenCalledWith('[SW Manager] Update check failed:', expect.any(Error))
    api.swManager.destroy()
    await vi.advanceTimersByTimeAsync(3_600_000)
    expect(registration.update).toHaveBeenCalledTimes(3)
    listener.mockClear()
    window.dispatchEvent(new Event('offline'))
    expect(listener).not.toHaveBeenCalled()
  })
  it.each(['DEV', 'admin', 'localhost', '127.0.0.1'])('unregisters stale workers for %s without claiming control', async (mode) => {
    if (mode === 'DEV') vi.stubEnv('DEV', true)
    else if (mode === 'admin') vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '1')
    else window.location.hostname = mode
    expect(await api.swManager.register()).toBe(false)
    expect(sw.register).not.toHaveBeenCalled()
    expect(registration.unregister).toHaveBeenCalledOnce()
  })
  it('reports registration and stale-unregister failures without rejecting', async () => {
    sw.register.mockRejectedValue(new Error('registration failed'))
    expect(await api.initServiceWorker()).toMatchObject({ supported: true, registered: false })
    expect(console.error).toHaveBeenCalledWith('[SW Manager] Registration failed:', expect.any(Error))
    expect(console.warn).toHaveBeenCalledWith('[SW Init] Service Worker initialization skipped or failed')
    sw.getRegistrations.mockRejectedValue(new Error('permission denied'))
    await expect(api.unregisterStaleServiceWorkers()).resolves.toBeUndefined()
    expect(console.warn).toHaveBeenCalledWith('[SW Manager] Failed to unregister stale workers:', expect.any(Error))
  })
  it('handles unsupported browsers without trying registration or messaging', async () => {
    api.swManager.destroy()
    Reflect.deleteProperty(navigator, 'serviceWorker')
    vi.resetModules()
    api = await import('./serviceWorker')
    expect(api.swManager.status.supported).toBe(false)
    expect(await api.swManager.register()).toBe(false)
    expect(await api.swManager.clearCache()).toBe(false)
    expect(await api.swManager.getCacheStatus()).toBeNull()
    await expect(api.swManager.activateUpdate()).resolves.toBeUndefined()
    await expect(api.unregisterStaleServiceWorkers()).resolves.toBeUndefined()
  })
  it('publishes offline and online transitions, isolates faulty listeners and supports unsubscribe', () => {
    const listener = vi.fn()
    api.swManager.onChange(() => { throw new Error('listener error') })
    const off = api.swManager.onChange(listener)
    window.dispatchEvent(new Event('offline'))
    expect(api.swManager.isOffline()).toBe(true)
    expect(listener).toHaveBeenLastCalledWith(expect.objectContaining({ offline: true }))
    window.dispatchEvent(new Event('online'))
    expect(api.swManager.isOffline()).toBe(false)
    expect(listener).toHaveBeenLastCalledWith(expect.objectContaining({ offline: false }))
    expect(console.error).toHaveBeenCalledWith('[SW Manager] Listener error:', expect.any(Error))
    off()
    listener.mockClear()
    window.dispatchEvent(new Event('offline'))
    expect(listener).not.toHaveBeenCalled()
  })
  it('waits for controller replacement before reloading', async () => {
    const pending = api.swManager.activateUpdate()
    expect(sw.controller!.postMessage).toHaveBeenCalledWith({ type: 'SKIP_WAITING' })
    expect(reload).not.toHaveBeenCalled()
    sw.dispatchEvent(new Event('controllerchange'))
    await pending
    expect(reload).toHaveBeenCalledOnce()
    reload.mockClear()
    sw.controller = null
    await api.swManager.activateUpdate()
    expect(reload).not.toHaveBeenCalled()
  })
  it.each([
    ['clearCache', 'CLEAR_CACHE', { type: 'CACHE_CLEARED' }, true, 5000, false],
    ['getCacheStatus', 'GET_STATUS', { type: 'STATUS', size: 100 }, { type: 'STATUS', size: 100 }, 3000, null],
  ] as const)('%s validates replies and times out safely', async (method, request, reply, expected, timeout, fallback) => {
    const pending = api.swManager[method]()
    expect(sw.controller!.postMessage).toHaveBeenCalledWith({ type: request }, [channel.port2])
    channel.port1.onmessage!({ data: reply })
    expect(await pending).toEqual(expected)
    const invalid = api.swManager[method]()
    channel.port1.onmessage!({ data: { type: 'OTHER' } })
    expect(await invalid).toEqual(fallback)
    const expired = api.swManager[method]()
    await vi.advanceTimersByTimeAsync(timeout)
    expect(await expired).toEqual(fallback)
    sw.controller = null
    expect(await api.swManager[method]()).toEqual(fallback)
  })
})
