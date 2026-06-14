import { describe, expect, it, vi, beforeEach } from 'vitest'
import { createRouter, createMemoryHistory } from 'vue-router'
import { registerModRoutes } from './registerModRoutes'

vi.mock('@/constants/modRouteGlob', () => ({
  modRouteGlob: {
    '/mods/test-mod/frontend/routes.js': vi.fn().mockResolvedValue({
      default: [
        {
          path: '/mod/test-mod/hello',
          name: 'test-mod-hello',
          component: () => import('@/views/LoginView.vue'),
        },
      ],
    }),
    '/mods/empty-mod/frontend/routes.js': vi.fn().mockResolvedValue({
      default: [],
    }),
  },
}))

describe('registerModRoutes', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('no-ops for empty entries', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [],
    })
    const addSpy = vi.spyOn(router, 'addRoute')
    await registerModRoutes(router, [])
    await registerModRoutes(router, null)
    expect(addSpy).not.toHaveBeenCalled()
  })

  it('registers routes from glob loader', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [],
    })
    const addSpy = vi.spyOn(router, 'addRoute')
    await registerModRoutes(router, [
      { mod_id: 'test-mod', routes_path: '/mods/test-mod/frontend/routes.js' },
    ])
    expect(addSpy).toHaveBeenCalled()
    expect(router.getRoutes().some((r) => r.path.includes('test-mod'))).toBe(true)
  })

  it('skips unknown mod bundle quietly', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [],
    })
    await expect(
      registerModRoutes(router, [{ mod_id: 'missing-mod', routes_path: 'x' }]),
    ).resolves.toBeUndefined()
  })

  it('marks intentionally empty routes as registered', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [],
    })
    await registerModRoutes(router, [
      { mod_id: 'empty-mod', routes_path: '/mods/empty-mod/frontend/routes.js' },
    ])
    await registerModRoutes(router, [
      { mod_id: 'empty-mod', routes_path: '/mods/empty-mod/frontend/routes.js' },
    ])
    const { modRouteGlob } = await import('@/constants/modRouteGlob')
    expect(modRouteGlob['/mods/empty-mod/frontend/routes.js']).toHaveBeenCalledTimes(1)
  })
})
