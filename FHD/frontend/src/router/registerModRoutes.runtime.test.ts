import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import type { RouteRecordRaw, Router } from 'vue-router'
import { registerModRoutes, retireStaleRuntimeRoutes } from './registerModRoutes'
import type { RuntimeModMetadata } from '@/utils/runtimeModSdk'
vi.mock('@/constants/modRouteGlob', () => ({ modRouteGlob: {} }))
const session = vi.hoisted(() => ({ epoch: 0 }))
vi.mock('@/utils/authSessionCache', () => ({
  captureAuthSession: () => {
    const epoch = session.epoch
    return () => epoch === session.epoch
  },
}))
const data = (): RuntimeModMetadata => ({ mod_id: 'unknown-ui', package_version: '1.0.0', package_sha256: 'a'.repeat(64), owner_scope: 'tenant:1', sdk_version: 1, entry_url: '/verified.js', routes: [{ path: '/mod/unknown-ui/home', name: 'runtime-unknown-ui-0', title: 'Independent UI' }], requires_restart: false, runtime_status: 'running' })
async function setup() {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', name: 'chat', component: { template: '<div />' } }] })
  await router.push('/')
  return router
}
describe('independently installed Mod routes', () => {
  it('resolves a signed runtime without a host glob and replaces old revision routes', async () => {
    const router = await setup()
    await registerModRoutes(router, [{ mod_id: 'unknown-ui', routes_path: '', runtime: data() }])
    expect(router.resolve('/mod/unknown-ui/home').name).toBe('runtime-unknown-ui-0')
    expect(router.resolve('/mod/unknown-ui/home').matched[0]?.props.default).toEqual({ modId: 'unknown-ui' })
    const next = { ...data(), package_sha256: 'b'.repeat(64), routes: [{ path: '/mod/unknown-ui/updated', name: 'runtime-unknown-ui-1', title: 'Updated' }] }
    await registerModRoutes(router, [{ mod_id: 'unknown-ui', routes_path: '', runtime: next }])
    expect(router.hasRoute('runtime-unknown-ui-0')).toBe(false)
    expect(router.resolve('/mod/unknown-ui/updated').name).toBe('runtime-unknown-ui-1')
    expect(router.hasRoute('chat')).toBe(true)
  })
  it('cannot replace a host route by either path or name', async () => {
    const router = await setup()
    for (const route of [{ path: '/chat', name: 'runtime-unknown-ui-0', title: 'Bad' }, { path: '/mod/unknown-ui/home', name: 'chat', title: 'Bad' }]) {
      await registerModRoutes(router, [{ mod_id: 'unknown-ui', routes_path: '', runtime: { ...data(), routes: [route] } }])
    }
    expect(router.getRoutes()).toHaveLength(1)
    expect(router.hasRoute('chat')).toBe(true)
  })
  it('tracks registrations per real Router instance', async () => {
    for (let i = 0; i < 2; i++) {
      const router = await setup()
      await registerModRoutes(router, [{ mod_id: 'unknown-ui', routes_path: '', runtime: data() }])
      expect(router.hasRoute('runtime-unknown-ui-0')).toBe(true)
    }
  })
})


it('rejects duplicate or invalid revisions without leaving an old runtime registered', async () => {
  const router = await setup()
  await registerModRoutes(router, [{ mod_id: 'unknown-ui', routes_path: '', runtime: data() }])
  const invalid = { ...data(), package_sha256: 'invalid' }
  await registerModRoutes(router, [{ mod_id: 'unknown-ui', routes_path: '', runtime: invalid }])
  expect(router.hasRoute('runtime-unknown-ui-0')).toBe(false)
  const duplicate = { ...data(), routes: [data().routes[0]!, data().routes[0]!] }
  await registerModRoutes(router, [{ mod_id: 'unknown-ui', routes_path: '', runtime: duplicate }])
  expect(router.hasRoute('runtime-unknown-ui-0')).toBe(false)
})

it('rejects collisions with a differently named host path and still registers the next extension', async () => {
  const router = await setup()
  router.addRoute({ path: '/mod/unknown-ui/home', name: 'host-home', component: { template: '<div />' } })
  const other = { ...data(), mod_id: 'other-ui', routes: [{ path: '/mod/other-ui/home', name: 'runtime-other-ui-0', title: 'Other' }] }
  await registerModRoutes(router, [{ mod_id: 'unknown-ui', routes_path: '', runtime: data() }, { mod_id: 'other-ui', routes_path: '', runtime: other }])
  expect(router.resolve('/mod/unknown-ui/home').name).toBe('host-home')
  expect(router.hasRoute('runtime-other-ui-0')).toBe(true)
})


it('retires the prior account runtime on session rollover and permits a fresh account', async () => {
  const router = await setup()
  await registerModRoutes(router, [{ mod_id: 'unknown-ui', routes_path: '', runtime: data() }])
  expect(router.hasRoute('runtime-unknown-ui-0')).toBe(true)
  session.epoch++
  retireStaleRuntimeRoutes(router)
  expect(router.hasRoute('runtime-unknown-ui-0')).toBe(false)
  const replacement = { ...data(), package_sha256: 'b'.repeat(64) }
  await registerModRoutes(router, [{ mod_id: 'unknown-ui', routes_path: '', runtime: replacement }])
  expect(router.hasRoute('runtime-unknown-ui-0')).toBe(true)
})

it('distinguishes an empty authoritative revocation from a failed route fetch', async () => {
  const router = await setup()
  await registerModRoutes(router, [{ mod_id: 'unknown-ui', routes_path: '', runtime: data() }])
  await registerModRoutes(router, null, { reconcileRuntime: true })
  expect(router.hasRoute('runtime-unknown-ui-0')).toBe(true)
  await registerModRoutes(router, [], { reconcileRuntime: true })
  expect(router.hasRoute('runtime-unknown-ui-0')).toBe(false)
  expect(router.hasRoute('chat')).toBe(true)
})

it('blocks parameterized host route overlap without replacing the host', async () => {
  const router = await setup()
  router.addRoute({ path: '/mod/:module/home', name: 'host-param', component: { template: '<div />' } })
  await registerModRoutes(router, [{ mod_id: 'unknown-ui', routes_path: '', runtime: data() }])
  expect(router.hasRoute('runtime-unknown-ui-0')).toBe(false)
  expect(router.resolve('/mod/unknown-ui/home').name).toBe('host-param')
})

it('restores the last valid revision if a new addRoute throws mid-registration', async () => {
  const router = await setup()
  await registerModRoutes(router, [{ mod_id: 'unknown-ui', routes_path: '', runtime: data() }])
  const originalAddRoute = router.addRoute.bind(router)
  router.addRoute = ((route: RouteRecordRaw) => {
    if (route.name === 'runtime-unknown-ui-1') throw new Error('injected router failure')
    return originalAddRoute(route)
  }) as Router['addRoute']
  const replacement = {
    ...data(),
    package_sha256: 'b'.repeat(64),
    routes: [{ path: '/mod/unknown-ui/updated', name: 'runtime-unknown-ui-1', title: 'Updated' }],
  }
  await registerModRoutes(router, [{ mod_id: 'unknown-ui', routes_path: '', runtime: replacement }])
  expect(router.hasRoute('runtime-unknown-ui-0')).toBe(true)
  expect(router.hasRoute('runtime-unknown-ui-1')).toBe(false)
})
