import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type RouteRecordRaw } from 'vue-router'
import { BUSINESS_ROUTES } from '@/router/routes/business'
import { modRoutes } from '../../../mods/bridge/xcagi-erp-domain-bridge/frontend/routes.js'
import { resolveErpPageRedirectForRouteName } from '@/utils/erpPagePaths'

vi.mock('@/router/modViews', () => ({ modView: () => ({ template: '<div />' }) }))
afterEach(() => vi.unstubAllGlobals())

function legacyRouter() {
  const paths = ['/kellai', '/data-sources', '/mod/xcagi-erp-domain-bridge/data-sources']
  const routes = [...BUSINESS_ROUTES, ...modRoutes]
    .filter(route => paths.includes(route.path))
    .map(route => 'component' in route ? { ...route, component: { template: '<div />' } } : route)
  const router = createRouter({ history: createMemoryHistory(), routes: routes as RouteRecordRaw[] })
  router.beforeEach(to => {
    const modPath = resolveErpPageRedirectForRouteName(String(to.name || ''))
    return modPath ? { path: modPath, query: to.query, hash: to.hash } : true
  })
  return router
}

describe('客来来旧入口兼容', () => {
  it.each(['/data-sources', '/mod/xcagi-erp-domain-bridge/data-sources'])(
    '%s 保留工作区和锚点，ERP 门面开启也不循环', async path => {
      vi.stubGlobal('localStorage', { getItem: () => '1' })
      const router = legacyRouter()
      await router.push(`${path}?workspace=messages#receipt`)
      expect(router.currentRoute.value.fullPath).toBe('/kellai?workspace=messages#receipt')
      expect(router.currentRoute.value.name).toBe('data-sources')
      expect(router.currentRoute.value.meta.title).toBe('客来来')
    },
  )

  it('保留旧 route name，让收藏和导航键进入客来来', async () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    const router = legacyRouter()
    await router.push({ name: 'data-sources', query: { workspace: 'connections' } })
    expect(router.currentRoute.value.fullPath).toBe('/kellai?workspace=connections')
  })
})
