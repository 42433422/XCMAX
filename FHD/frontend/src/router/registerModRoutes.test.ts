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
    '/mods/refresh-mod/frontend/routes.js': vi.fn().mockResolvedValue({
      default: [
        {
          path: '/mod/refresh-mod/hello',
          name: 'refresh-mod-hello',
          component: () => import('@/views/LoginView.vue'),
        },
      ],
    }),
    '/mods/refresh-home-mod/frontend/routes.js': vi.fn().mockResolvedValue({
      default: [
        {
          path: '/refresh-home-mod',
          name: 'refresh-home-mod-home',
          component: () => import('@/views/LoginView.vue'),
        },
      ],
    }),
  },
}))

describe('registerModRoutes', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.history.replaceState(null, '', '/')
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

  it('refreshes the actual browser path when router is still at start location', async () => {
    window.history.replaceState(null, '', '/onboarding?step=welcome&redirect=/')
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        {
          path: '/onboarding',
          name: 'product-onboarding',
          component: () => import('@/views/LoginView.vue'),
        },
      ],
    })
    const replaceSpy = vi.spyOn(router, 'replace')

    await registerModRoutes(router, [
      { mod_id: 'refresh-mod', routes_path: '/mods/refresh-mod/frontend/routes.js' },
    ])

    expect(replaceSpy).toHaveBeenCalledWith('/onboarding?step=welcome&redirect=/')
  })

  it('prefers the browser mod path when current route has already fallen back to home', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        {
          path: '/',
          name: 'chat',
          component: () => import('@/views/LoginView.vue'),
        },
      ],
    })
    await router.push('/')
    await router.isReady()
    window.history.replaceState(null, '', '/refresh-home-mod')
    const replaceSpy = vi.spyOn(router, 'replace')

    await registerModRoutes(router, [
      { mod_id: 'refresh-home-mod', routes_path: '/mods/refresh-home-mod/frontend/routes.js' },
    ])

    expect(replaceSpy).toHaveBeenCalledWith('/refresh-home-mod')
  })
})
