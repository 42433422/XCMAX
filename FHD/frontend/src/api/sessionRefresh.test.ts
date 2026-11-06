import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { installStabilityClient } from './sessionRefresh'
import { registerSessionRefresh } from './core'
import { showAppToast } from '@/composables/useAppToast'
import { publishStabilityNotice } from '@/utils/networkStability'

vi.mock('./core', () => ({ buildFullApiUrl: (path: string) => path, registerSessionRefresh: vi.fn() }))
vi.mock('@/composables/useAppToast', () => ({ showAppToast: vi.fn() }))
vi.mock('@/utils/networkStability', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/utils/networkStability')>(),
  createTraceId: () => 'test', publishStabilityNotice: vi.fn(),
}))
const listeners: EventListener[] = []
afterEach(() => {
  for (const listener of listeners.splice(0)) window.removeEventListener('xcagi:stability-notice', listener)
  vi.restoreAllMocks()
  vi.clearAllMocks()
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  window.localStorage.removeItem('xcagi_stability_refresh')
  document.cookie = 'csrf_token=; Max-Age=0; path=/'
})
function install() {
  const spy = vi.spyOn(window, 'addEventListener')
  installStabilityClient()
  listeners.push(spy.mock.calls.find(([name]) => name === 'xcagi:stability-notice')![1] as EventListener)
}
function registeredRefresh() {
  const refresh = vi.mocked(registerSessionRefresh).mock.calls.at(-1)?.[0]
  if (!refresh) throw new Error('lab refresh was not registered')
  return refresh
}
it('keeps production notices without registering experimental authentication or requests', () => {
  vi.stubEnv('VITE_STABILITY_LAB', '')
  const request = vi.fn()
  vi.stubGlobal('fetch', request)
  install()
  expect(registerSessionRefresh).not.toHaveBeenCalled()
  expect(request).not.toHaveBeenCalled()
  window.dispatchEvent(new CustomEvent('xcagi:stability-notice', { detail: { message: '网络已断开' } }))
  expect(showAppToast).toHaveBeenCalledWith('网络已断开', 'error', { duration: 8000 })
  window.dispatchEvent(new CustomEvent('xcagi:stability-notice'))
  expect(showAppToast).toHaveBeenCalledTimes(1)
})
it('enables experimental refresh only for an explicitly selected lab build', () => {
  vi.stubEnv('VITE_STABILITY_LAB', '1')
  const request = vi.fn().mockResolvedValue({ json: async () => ({}) })
  vi.stubGlobal('fetch', request)
  install()
  expect(registerSessionRefresh).toHaveBeenCalledTimes(1)
  expect(request).toHaveBeenCalledWith('/api/stability/ui-notice', { credentials: 'include' })
})

it('does not send an experimental refresh without a stored credential', async () => {
  vi.stubEnv('VITE_STABILITY_LAB', '1')
  const request = vi.fn().mockResolvedValue({ json: async () => ({}) })
  vi.stubGlobal('fetch', request)
  install(); await flushPromises(); request.mockClear()
  await expect(registeredRefresh()()).resolves.toBe(false)
  expect(request).not.toHaveBeenCalled()
})

it.each([null, 'csrf-value'])('rotates the lab credential while respecting the CSRF cookie %s', async (csrf) => {
  vi.stubEnv('VITE_STABILITY_LAB', '1')
  window.localStorage.setItem('xcagi_stability_refresh', 'old-token')
  if (csrf) document.cookie = `csrf_token=${csrf}; path=/`
  const request = vi.fn().mockResolvedValue({ json: async () => ({}) })
  vi.stubGlobal('fetch', request)
  install(); await flushPromises()
  request.mockResolvedValueOnce({ ok: true, json: async () => ({ success: true, refresh_token: 'next-token' }) })
  await expect(registeredRefresh()()).resolves.toBe(true)
  expect(request).toHaveBeenLastCalledWith('/api/stability/lab/refresh', {
    method: 'POST', credentials: 'include', body: JSON.stringify({ refresh_token: 'old-token' }),
    headers: { 'Content-Type': 'application/json', 'X-Request-ID': 'test', ...(csrf ? { 'X-CSRF-Token': csrf } : {}) },
  })
  expect(window.localStorage.getItem('xcagi_stability_refresh')).toBe('next-token')
})

it.each([false, true])('rejects an unsuccessful refresh without replacing the credential (HTTP ok=%s)', async (ok) => {
  vi.stubEnv('VITE_STABILITY_LAB', '1')
  window.localStorage.setItem('xcagi_stability_refresh', 'old-token')
  const request = vi.fn().mockResolvedValue({ json: async () => ({}) })
  vi.stubGlobal('fetch', request)
  install(); await flushPromises()
  request.mockResolvedValueOnce({ ok, json: async () => ({ success: false }) })
  await expect(registeredRefresh()()).resolves.toBe(false)
  expect(window.localStorage.getItem('xcagi_stability_refresh')).toBe('old-token')
})

it('uses the public error message for an experimental diagnostic notice', async () => {
  vi.stubEnv('VITE_STABILITY_LAB', '1')
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ json: async () => ({ raw: 'connect ETIMEDOUT' }) }))
  install(); await flushPromises()
  expect(showAppToast).toHaveBeenCalledWith(expect.stringContaining('请求超时'), 'error', { duration: 8000 })
  expect(publishStabilityNotice).toHaveBeenCalledWith(expect.stringContaining('请求超时'))
})

it('keeps refresh available when the optional lab notice request fails', async () => {
  vi.stubEnv('VITE_STABILITY_LAB', '1')
  window.localStorage.setItem('xcagi_stability_refresh', 'old-token')
  const request = vi.fn().mockRejectedValueOnce(new Error('notice unavailable'))
    .mockResolvedValueOnce({ ok: true, json: async () => ({ success: true }) })
  vi.stubGlobal('fetch', request)
  install(); await flushPromises()
  expect(showAppToast).not.toHaveBeenCalled()
  await expect(registeredRefresh()()).resolves.toBe(true)
})
