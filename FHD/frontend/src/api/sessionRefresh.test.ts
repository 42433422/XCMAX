import { afterEach, expect, it, vi } from 'vitest'
import { installStabilityClient } from './sessionRefresh'
import { registerSessionRefresh } from './core'
import { showAppToast } from '@/composables/useAppToast'

vi.mock('./core', () => ({ buildFullApiUrl: (path: string) => path, registerSessionRefresh: vi.fn() }))
vi.mock('@/composables/useAppToast', () => ({ showAppToast: vi.fn() }))
vi.mock('@/utils/networkStability', () => ({ createTraceId: () => 'test', publishStabilityNotice: vi.fn() }))
const listeners: EventListener[] = []
afterEach(() => {
  for (const listener of listeners.splice(0)) window.removeEventListener('xcagi:stability-notice', listener)
  vi.restoreAllMocks()
  vi.clearAllMocks()
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})
function install() {
  const spy = vi.spyOn(window, 'addEventListener')
  installStabilityClient()
  listeners.push(spy.mock.calls.find(([name]) => name === 'xcagi:stability-notice')![1] as EventListener)
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
})
it('enables experimental refresh only for an explicitly selected lab build', () => {
  vi.stubEnv('VITE_STABILITY_LAB', '1')
  const request = vi.fn().mockResolvedValue({ json: async () => ({}) })
  vi.stubGlobal('fetch', request)
  install()
  expect(registerSessionRefresh).toHaveBeenCalledTimes(1)
  expect(request).toHaveBeenCalledWith('/api/stability/ui-notice', { credentials: 'include' })
})
