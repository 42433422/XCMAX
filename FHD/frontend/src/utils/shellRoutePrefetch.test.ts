import { afterEach, describe, expect, it, vi } from 'vitest'
import { prefetchShellRoute, prefetchShellRouteChunks } from './shellRoutePrefetch'

function routerWith(name: string, component: () => Promise<unknown>) {
  return {
    getRoutes: () => [{ name, components: { default: component } }],
  } as never
}

describe('shellRoutePrefetch', () => {
  afterEach(() => {
    vi.useRealTimers()
    delete (window as Window & { requestIdleCallback?: unknown }).requestIdleCallback
  })

  it('loads a hovered route once and skips a blank or repeated name', async () => {
    const component = vi.fn().mockResolvedValue({ ready: true })
    const router = routerWith('chat', component)
    prefetchShellRoute(router, 'chat')
    await vi.waitFor(() => expect(component).toHaveBeenCalledOnce())
    prefetchShellRoute(router, 'chat')
    prefetchShellRoute(router, '')
    expect(component).toHaveBeenCalledOnce()
  })

  it('forgets a failed chunk so the next hover can load it', async () => {
    const component = vi.fn().mockRejectedValueOnce(new Error('missing chunk')).mockResolvedValueOnce({ ready: true })
    const router = routerWith('settings', component)
    prefetchShellRoute(router, 'settings')
    await vi.waitFor(() => expect(component).toHaveBeenCalledOnce())
    prefetchShellRoute(router, 'settings')
    await vi.waitFor(() => expect(component).toHaveBeenCalledTimes(2))
  })

  it('loads the messenger immediately and does not schedule the same router twice', async () => {
    vi.useFakeTimers()
    delete (window as Window & { requestIdleCallback?: unknown }).requestIdleCallback
    const im = vi.fn().mockResolvedValue({ ready: true })
    const router = {
      getRoutes: () => [{ name: 'im', components: { default: im } }],
    } as never
    prefetchShellRouteChunks(router)
    await Promise.resolve()
    expect(im).toHaveBeenCalledOnce()
    prefetchShellRouteChunks(router)
    await vi.advanceTimersByTimeAsync(200)
    expect(im).toHaveBeenCalledOnce()
  })

  it('warms a shell route from the idle timer and from requestIdleCallback', async () => {
    vi.useFakeTimers()
    delete (window as Window & { requestIdleCallback?: unknown }).requestIdleCallback
    const customers = vi.fn().mockResolvedValue({ ready: true })
    prefetchShellRouteChunks(routerWith('customers', customers))
    await vi.advanceTimersByTimeAsync(200)
    expect(customers).toHaveBeenCalledOnce()

    const idle = vi.fn((task: () => void) => {
      task()
      return 1
    })
    ;(window as Window & { requestIdleCallback?: typeof idle }).requestIdleCallback = idle
    const orders = vi.fn().mockResolvedValue({ ready: true })
    prefetchShellRouteChunks(routerWith('orders', orders))
    await Promise.resolve()
    expect(idle).toHaveBeenCalled()
    expect(orders).toHaveBeenCalledOnce()
  })
})
