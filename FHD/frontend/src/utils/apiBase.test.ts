import { afterEach, describe, it, expect, vi } from 'vitest'
import { createRouter, createWebHistory } from 'vue-router'
import { apiUrl, getApiBase, getAppBase, isApiFetchTimeoutError } from './apiBase'

describe('apiBase', () => {
  it('isApiFetchTimeoutError detects apiFetch timeout AbortError', () => {
    const err = new DOMException('apiFetch timeout after 1000ms', 'AbortError')
    expect(isApiFetchTimeoutError(err)).toBe(true)
  })

  it('isApiFetchTimeoutError ignores generic AbortError', () => {
    const err = new DOMException('user aborted', 'AbortError')
    expect(isApiFetchTimeoutError(err)).toBe(false)
  })

  it('isApiFetchTimeoutError handles Error shape', () => {
    const err = new Error('apiFetch timeout')
    err.name = 'AbortError'
    expect(isApiFetchTimeoutError(err)).toBe(true)
  })
})


describe('shared desktop and cloud mount', () => {
  afterEach(() => {
    window.history.replaceState(null, '', '/')
    vi.unstubAllEnvs()
    delete (window as unknown as { __XCMAX_API_BASE__?: string }).__XCMAX_API_BASE__
  })

  it.each([
    ['/fhd-api/workspaces/task-1?conversation=conv-2', '/fhd-api/', '/fhd-api'],
    ['/fhd-api', '/fhd-api/', '/fhd-api'],
    ['/workspaces/task-1', '/', ''],
    ['/fhd-api-other/workspaces/task-1', '/', ''],
  ])('resolves assets, routing and API at %s', (path, appBase, apiBase) => {
    vi.stubEnv('BASE_URL', './')
    vi.stubEnv('VITE_API_BASE', '')
    vi.stubEnv('VITE_API_BASE_URL', '')
    window.history.replaceState(null, '', path)
    expect(getAppBase()).toBe(appBase)
    expect(getApiBase()).toBe(apiBase)
    expect(apiUrl('/api/auth/me')).toBe(`${apiBase}/api/auth/me`)
  })

  it('preserves explicit build and injected API configuration', () => {
    window.history.replaceState(null, '', '/fhd-api/workspaces/task-1')
    vi.stubEnv('BASE_URL', '/admin/')
    ;(window as unknown as { __XCMAX_API_BASE__?: string }).__XCMAX_API_BASE__ = '/custom-api'
    expect(getAppBase()).toBe('/admin/')
    expect(getApiBase()).toBe('/custom-api')
  })

  it.each(['', '/fhd-api'])('opens a task deep link and keeps the mount during navigation: %s', async (prefix) => {
    vi.stubEnv('BASE_URL', './')
    window.history.replaceState(null, '', `${prefix}/workspaces/task-1?conversation=conv-2`)
    const history = createWebHistory(getAppBase())
    const router = createRouter({ history, routes: [
      { path: '/workspaces/:taskId', component: { template: '<div />' } },
      { path: '/customers', component: { template: '<div />' } },
    ] })
    try {
      await router.replace(history.location)
      expect(router.currentRoute.value.params.taskId).toBe('task-1')
      expect(router.currentRoute.value.query.conversation).toBe('conv-2')
      await router.push('/customers')
      expect(window.location.pathname).toBe(`${prefix}/customers`)
    } finally {
      history.destroy()
    }
  })
})
