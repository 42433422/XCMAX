import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, NavigationFailureType, isNavigationFailure } from 'vue-router'
import {
  isSidebarNavigationPending,
  navigateFromSidebarKey,
  resetSidebarNavigationForTests,
} from '@/utils/sidebarNavigation'

const options = { modMenuItems: [] }
const page = { template: '<div />' }

async function makeRouter() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'chat', component: page },
      { path: '/settings', name: 'settings', component: page },
      { path: '/reports', name: 'reports', component: page },
      { path: '/external', name: 'external', component: page },
    ],
  })
  await router.push('/')
  await router.isReady()
  return router
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

describe('sidebar navigation with Vue Router', () => {
  beforeEach(() => resetSidebarNavigationForTests())
  afterEach(() => resetSidebarNavigationForTests())

  it('reports a guard rejection as a failed navigation and allows retrying the same target', async () => {
    const router = await makeRouter()
    let blocked = true
    router.beforeEach((to) => to.name === 'settings' && blocked ? false : true)

    const rejected = await navigateFromSidebarKey(router, 'settings', options)
    expect(router.currentRoute.value.name).toBe('chat')
    expect(isSidebarNavigationPending()).toBe(false)

    blocked = false
    await expect(navigateFromSidebarKey(router, 'settings', options)).resolves.toBe(true)
    expect(router.currentRoute.value.name).toBe('settings')
    expect(rejected).toBe(false)
  })

  it('treats an already-current target as a successful navigation', async () => {
    const router = await makeRouter()

    await expect(navigateFromSidebarKey(router, 'chat', options)).resolves.toBe(true)
    expect(isSidebarNavigationPending()).toBe(false)
  })

  it('lets the latest sidebar click win over a still-pending guard', async () => {
    const router = await makeRouter()
    const entered = deferred<void>()
    const release = deferred<void>()
    const oldFinished = deferred<void>()
    router.beforeEach(async (to) => {
      if (to.name === 'settings') {
        entered.resolve()
        await release.promise
      }
    })
    router.afterEach((to) => { if (to.name === 'settings') oldFinished.resolve() })

    const first = navigateFromSidebarKey(router, 'settings', options)
    await entered.promise
    const latest = navigateFromSidebarKey(router, 'reports', options)
    try {
      await expect(latest).resolves.toBe(true)
      expect(router.currentRoute.value.name).toBe('reports')
    } finally {
      release.resolve()
      await oldFinished.promise
      await first
    }
    expect(router.currentRoute.value.name).toBe('reports')
    expect(isSidebarNavigationPending()).toBe(false)
    await expect(first).resolves.toBe(false)
  })

  it('returns to the original target after a fast A to B to A sequence', async () => {
    const router = await makeRouter()
    const entered = deferred<void>()
    const release = deferred<void>()
    let attempts = 0
    router.beforeEach(async (to) => {
      if (to.name === 'settings' && ++attempts === 1) {
        entered.resolve()
        await release.promise
      }
    })

    const first = navigateFromSidebarKey(router, 'settings', options)
    await entered.promise
    const middle = navigateFromSidebarKey(router, 'reports', options)
    await expect(middle).resolves.toBe(true)
    expect(router.currentRoute.value.name).toBe('reports')

    const last = navigateFromSidebarKey(router, 'settings', options)
    await expect(last).resolves.toBe(true)
    expect(router.currentRoute.value.name).toBe('settings')
    expect(attempts).toBe(2)

    release.resolve()
    await expect(first).resolves.toBe(false)
    expect(router.currentRoute.value.name).toBe('settings')
    expect(isSidebarNavigationPending()).toBe(false)
  })

  it('does not report success when an external router navigation cancels the pending sidebar navigation', async () => {
    const router = await makeRouter()
    const entered = deferred<void>()
    const release = deferred<void>()
    router.beforeEach(async (to) => {
      if (to.name === 'settings') {
        entered.resolve()
        await release.promise
      }
    })

    const sidebar = navigateFromSidebarKey(router, 'settings', options)
    await entered.promise
    try {
      await router.push({ name: 'external' })
      expect(router.currentRoute.value.name).toBe('external')
    } finally {
      release.resolve()
    }
    const applied = await sidebar
    expect(router.currentRoute.value.name).toBe('external')
    expect(isSidebarNavigationPending()).toBe(false)
    expect(applied).toBe(false)
  })

  it('retries the same target while its first navigation is pending', async () => {
    const router = await makeRouter()
    const entered = deferred<void>()
    const release = deferred<void>()
    const firstFinished = deferred<void>()
    let attempts = 0
    router.beforeEach(async (to) => {
      if (to.name === 'settings' && ++attempts === 1) {
        entered.resolve()
        await release.promise
      }
    })
    router.afterEach((to, _from, failure) => {
      if (to.name === 'settings' && isNavigationFailure(failure, NavigationFailureType.cancelled)) firstFinished.resolve()
    })

    const first = navigateFromSidebarKey(router, 'settings', options)
    await entered.promise
    const retry = navigateFromSidebarKey(router, 'settings', options)
    try {
      await expect(retry).resolves.toBe(true)
      expect(router.currentRoute.value.name).toBe('settings')
      expect(attempts).toBe(2)
    } finally {
      release.resolve()
      await firstFinished.promise
      await first
    }
    expect(router.currentRoute.value.name).toBe('settings')
    await expect(first).resolves.toBe(false)
  })

  it('preserves history when navigating back and forward after sidebar selections', async () => {
    const router = await makeRouter()
    await navigateFromSidebarKey(router, 'settings', options)
    await navigateFromSidebarKey(router, 'reports', options)
    expect(router.currentRoute.value.name).toBe('reports')

    router.back()
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('settings'))
    router.back()
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('chat'))
    router.forward()
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('settings'))
    router.forward()
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('reports'))
  })
})
