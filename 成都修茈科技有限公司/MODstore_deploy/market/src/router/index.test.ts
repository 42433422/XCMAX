import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

const assignMock = vi.fn()

beforeEach(() => {
  localStorage.setItem('modstore_token', 'router-token')
  sessionStorage.clear()
  assignMock.mockClear()
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: { ...window.location, assign: assignMock },
  })
})

afterEach(() => {
  document.title = ''
  document.head.querySelectorAll('meta[name="description"]').forEach((el) => el.remove())
})

describe('router index behavior', () => {
  it('applies scroll behavior and document metadata', async () => {
    const router = (await import('./index')).default as any
    const scrollBehavior = router.options.scrollBehavior

    expect(scrollBehavior({ path: '/' }, {}, { left: 4, top: 8 })).toEqual({ left: 4, top: 8 })
    expect(scrollBehavior({ hash: '#api-keys' }, {}, null)).toEqual({ el: '#api-keys', behavior: 'smooth' })
    expect(scrollBehavior({ path: '/' }, {}, null)).toEqual({ top: 0 })

    await router.push('/about')
    await router.isReady()

    expect(document.title).toContain('XC AGI 市场')
    expect(document.querySelector('meta[name="description"]')?.getAttribute('content')).toContain('修茈科技')
  })

  it('reloads once when lazy route chunks fail and ignores non-chunk errors', async () => {
    const router = (await import('./index')).default as any
    router.addRoute({
      path: '/coverage-broken-chunk',
      name: 'coverage-broken-chunk',
      component: () => Promise.reject(new Error('Loading chunk coverage failed')),
    })
    router.addRoute({
      path: '/coverage-normal-error',
      name: 'coverage-normal-error',
      component: () => Promise.reject(new Error('plain route failure')),
    })
    router.addRoute({
      path: '/coverage-broken-existing-key',
      name: 'coverage-broken-existing-key',
      component: () => Promise.reject(new Error('Failed to fetch dynamically imported module')),
    })

    await router.push('/coverage-normal-error').catch(() => undefined)
    expect(assignMock).not.toHaveBeenCalled()

    await router.push('/coverage-broken-chunk').catch(() => undefined)
    expect(assignMock).toHaveBeenCalledTimes(1)
    expect(assignMock.mock.calls[0]?.[0]).toContain('/coverage-broken-chunk')

    const href = router.resolve('/coverage-broken-existing-key').href
    sessionStorage.setItem(`vite-chunk-reload:${href}`, '1')
    await router.push('/coverage-broken-existing-key').catch(() => undefined)
    expect(assignMock).toHaveBeenCalledTimes(1)
    expect(sessionStorage.getItem(`vite-chunk-reload:${href}`)).toBeNull()
  })
})
