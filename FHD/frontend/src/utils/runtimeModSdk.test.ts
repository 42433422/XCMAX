import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createRuntimeModSdk, trustedRuntimeEntry, type RuntimeModMetadata } from './runtimeModSdk'
import { apiFetch } from './apiBase'
vi.mock('./apiBase', () => ({ apiFetch: vi.fn() }))
const metadata = (): RuntimeModMetadata => ({ mod_id: 'independent-ui', package_version: '1.0.0', package_sha256: 'a'.repeat(64), owner_scope: 'tenant:1', sdk_version: 1, entry_url: `/api/mods/runtime/independent-ui/assets/${'a'.repeat(64)}/frontend/runtime/index.js`, routes: [], requires_restart: false, runtime_status: 'running' })

describe('verified local Mod SDK', () => {
  beforeEach(() => vi.clearAllMocks())
  it('accepts only the exact same-origin signed revision path', () => {
    expect(trustedRuntimeEntry(metadata())).toBe(window.location.origin + metadata().entry_url)
    for (const entry_url of ['https://other.example/evil.js', '//other.example/evil.js', '/assets/other.js', metadata().entry_url + '?redirect=other', metadata().entry_url.replace('/index.js', '/../other.js')]) {
      expect(() => trustedRuntimeEntry({ ...metadata(), entry_url })).toThrow()
    }
    expect(() => trustedRuntimeEntry({ ...metadata(), package_sha256: '../other' })).toThrow()
  })
  it('scopes API paths, navigation and cancellation to this Mod', async () => {
    const controller = new AbortController()
    const navigate = vi.fn().mockResolvedValue(undefined)
    const sdk = createRuntimeModSdk(metadata(), { path: '/mod/independent-ui/home', query: { tab: 'one' } }, controller.signal, navigate)
    await sdk.request('/records?name=hello', { method: 'POST', body: '{}' })
    expect(apiFetch).toHaveBeenCalledWith('/api/mod/independent-ui/records?name=hello', expect.objectContaining({ method: 'POST', signal: controller.signal }))
    await sdk.navigate('/mod/independent-ui/detail')
    expect(navigate).toHaveBeenCalledWith('/mod/independent-ui/detail')
    expect(Object.isFrozen(sdk)).toBe(true)
    expect(Object.isFrozen(sdk.route.query)).toBe(true)
    for (const path of ['//evil', '/../auth', '/%2e%2e/auth', '/%2f../auth', '/x\\..\\auth']) expect(() => sdk.request(path)).toThrow()
    for (const path of ['/chat', '/mod/independent-ui/../../chat', '/mod/independent-ui/%2e%2e/chat']) expect(() => sdk.navigate(path)).toThrow()
  })
})
