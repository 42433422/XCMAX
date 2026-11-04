import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type RouteLocationNormalizedLoaded } from 'vue-router'
import { useLoginViewState } from './useLoginViewState'
import { buildLoginLocation } from '@/utils/startupRedirect'

afterEach(() => vi.unstubAllEnvs())

function state(redirect: string) {
  return useLoginViewState({ query: { redirect } } as unknown as RouteLocationNormalizedLoaded)
}

describe('login redirect in the independently mounted admin console', () => {
  it('consumes existing browser-prefixed redirects without applying /admin twice', () => {
    vi.stubEnv('BASE_URL', '/admin/')
    const router = createRouter({
      history: createMemoryHistory('/admin/'),
      routes: [{ path: '/customer-service-tickets/:id', component: {} }],
    })
    const redirect = state('/admin/customer-service-tickets/41').redirectPath.value
    expect(redirect).toBe('/customer-service-tickets/41')
    expect(router.resolve(redirect).href).toBe('/admin/customer-service-tickets/41')
  })

  it('round trips a startup location through the real login state', () => {
    vi.stubEnv('BASE_URL', '/admin/')
    const login = buildLoginLocation({ pathname: '/admin/customer-service-tickets/41' }, '/admin/')
    expect(state(login.query.redirect).redirectPath.value).toBe('/customer-service-tickets/41')
  })

  it('peels a nested mounted login while keeping encoded onboarding query semantics', () => {
    vi.stubEnv('BASE_URL', '/admin/')
    const target = '/admin/onboarding?returnTo=%2Fsettings%3Fx%3D1%26y%3D2'
    expect(state('/admin/login?redirect=' + encodeURIComponent(target)).redirectPath.value)
      .toBe('/onboarding?returnTo=%2Fsettings%3Fx%3D1%26y%3D2')
  })

  it.each(['/admin//evil.example', '/admin/\\evil.example', 'https://evil.example', '/admin/login'])('rejects unsafe target %s', (target) => {
    vi.stubEnv('BASE_URL', '/admin/')
    expect(state(target).redirectPath.value).toBe('/')
  })
})
