import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { registerModRoutes } from './registerModRoutes'
import type { RuntimeModMetadata } from '@/utils/runtimeModSdk'
vi.mock('@/constants/modRouteGlob', () => ({ modRouteGlob: {} }))
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
