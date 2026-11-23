import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createRouter, createWebHistory } from 'vue-router'
import { navigateFromSidebarKey, resetSidebarNavigationForTests } from '@/utils/sidebarNavigation'

const page = { template: '<div />' }
const options = { modMenuItems: [] }
const histories: ReturnType<typeof createWebHistory>[] = []

function deferred() {
  let resolve!: () => void
  const promise = new Promise<void>(done => { resolve = done })
  return { promise, resolve }
}

async function makeRouter(settingsLoader?: () => Promise<typeof page>) {
  const history = createWebHistory()
  histories.push(history)
  const router = createRouter({ history, routes: [
    { path: '/', name: 'chat', component: page },
    { path: '/settings', name: 'settings', component: settingsLoader || page },
    { path: '/reports', name: 'reports', component: page },
  ] })
  await router.push('/')
  await router.isReady()
  return router
}

beforeEach(() => {
  resetSidebarNavigationForTests()
  window.history.replaceState(null, '', '/')
  // Keep real browser-history traversal tasks; control only the address-sync interval.
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
})

afterEach(() => {
  resetSidebarNavigationForTests()
  for (const history of histories.splice(0)) history.destroy()
  vi.restoreAllMocks()
  vi.useRealTimers()
  window.history.replaceState(null, '', '/')
})

it('preserves forward history while a guard waits after a cold sidebar navigation was cancelled', async () => {
  const coldEntered = deferred(), coldRelease = deferred(), backDone = deferred()
  const forwardEntered = deferred(), forwardRelease = deferred(), forwardDone = deferred()
  const router = await makeRouter(async () => {
    coldEntered.resolve()
    await coldRelease.promise
    return page
  })
  await router.push('/?history=ready')
  const forwardPosition = window.history.state.position
  router.afterEach((to, from, failure) => {
    if (failure) return
    if (to.fullPath === '/' && from.fullPath === '/?history=ready') backDone.resolve()
    if (to.fullPath === '/?history=ready' && from.fullPath === '/') forwardDone.resolve()
  })
  const pending = navigateFromSidebarKey(router, 'settings', options)
  await coldEntered.promise
  router.back()
  await backDone.promise
  coldRelease.resolve()
  await expect(pending).resolves.toBe(false)
  router.beforeEach(async to => {
    if (to.fullPath === '/?history=ready') {
      forwardEntered.resolve()
      await forwardRelease.promise
    }
  })
  router.forward()
  await forwardEntered.promise
  try {
    expect(window.history.state.position).toBe(forwardPosition)
    expect(window.location.search).toBe('?history=ready')
    expect(router.currentRoute.value.fullPath).toBe('/')
    const writes = vi.spyOn(window.history, 'replaceState')
    vi.advanceTimersByTime(40)
    expect(window.location.search).toBe('?history=ready')
    expect(writes).not.toHaveBeenCalled()
  } finally {
    forwardRelease.resolve()
    await forwardDone.promise
  }
  expect(router.currentRoute.value.fullPath).toBe('/?history=ready')
  expect(window.location.search).toBe('?history=ready')
})

it('does not overwrite a different history entry while its router guard is pending', async () => {
  const router = await makeRouter()
  await navigateFromSidebarKey(router, 'settings', options)
  const ownerPosition = window.history.state.position
  const entered = deferred(), release = deferred(), finished = deferred()
  router.beforeEach(async to => {
    if (to.name === 'chat') { entered.resolve(); await release.promise }
  })
  router.afterEach((to, _from, failure) => { if (to.name === 'chat' && !failure) finished.resolve() })
  router.back()
  await entered.promise
  try {
    expect(window.history.state.position).not.toBe(ownerPosition)
    expect(window.location.pathname).toBe('/')
    expect(router.currentRoute.value.fullPath).toBe('/settings')
    const writes = vi.spyOn(window.history, 'replaceState')
    vi.advanceTimersByTime(40)
    expect(window.location.pathname).toBe('/')
    expect(writes).not.toHaveBeenCalled()
  } finally {
    release.resolve()
    await finished.promise
  }
  expect(window.location.pathname).toBe(router.currentRoute.value.fullPath)
})

it('corrects a stale address within the completed entry, including a duplicate sidebar choice', async () => {
  const router = await makeRouter()
  await router.push('/settings')
  await expect(navigateFromSidebarKey(router, 'settings', options)).resolves.toBe(true)
  const position = window.history.state.position
  window.history.replaceState(window.history.state, '', '/stale-address')
  const writes = vi.spyOn(window.history, 'replaceState')
  vi.advanceTimersByTime(40)
  expect(window.location.pathname).toBe('/settings')
  expect(window.history.state.position).toBe(position)
  expect(writes).toHaveBeenCalledWith(expect.objectContaining({ position, current: '/settings' }), '', new URL('/settings', window.location.origin).href)
})

it('retires the previous address repair as soon as a new sidebar request starts', async () => {
  const router = await makeRouter()
  await navigateFromSidebarKey(router, 'settings', options)
  const entered = deferred(), release = deferred()
  router.beforeEach(async to => {
    if (to.name === 'reports') { entered.resolve(); await release.promise }
  })
  const pending = navigateFromSidebarKey(router, 'reports', options)
  await entered.promise
  try {
    window.history.replaceState(window.history.state, '', '/pending-address')
    const writes = vi.spyOn(window.history, 'replaceState')
    vi.advanceTimersByTime(40)
    expect(window.location.pathname).toBe('/pending-address')
    expect(writes).not.toHaveBeenCalled()
  } finally {
    release.resolve()
    await pending
  }
  expect(router.currentRoute.value.fullPath).toBe('/reports')
  expect(window.location.pathname).toBe('/reports')
})
