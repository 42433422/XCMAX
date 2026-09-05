import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import RuntimeModView from './RuntimeModView.vue'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { apiFetch } from '@/utils/apiBase'
import { loadRuntimeMod, type RuntimeModMetadata, type RuntimeModSdk } from '@/utils/runtimeModSdk'
vi.mock('@/utils/apiBase', () => ({ apiFetch: vi.fn() }))
vi.mock('@/utils/runtimeModSdk', async (original) => ({ ...await original<typeof import('@/utils/runtimeModSdk')>(), loadRuntimeMod: vi.fn() }))
const metadata = (): RuntimeModMetadata => ({ mod_id: 'independent-ui', package_version: '1.0.0', package_sha256: 'a'.repeat(64), owner_scope: 'tenant:1', sdk_version: 1, entry_url: '/verified.js', routes: [], requires_restart: false, runtime_status: 'running' })
async function setup() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const account = useAccountProfileStore()
  account.tenantId = 1
  account.localUserId = 1
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/mod/independent-ui/home', component: { template: '<div />' } }] })
  await router.push('/mod/independent-ui/home')
  const wrapper = mount(RuntimeModView, { props: { modId: 'independent-ui' }, global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, account }
}
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(apiFetch).mockImplementation(async () => new Response(JSON.stringify({ success: true, data: metadata() }), { status: 200 }))
})
describe('runtime Mod component lifecycle', () => {
  it('mounts with the stable SDK and cleans up on unmount', async () => {
    const cleanup = vi.fn()
    let signal: AbortSignal | undefined
    vi.mocked(loadRuntimeMod).mockResolvedValue({ mount(element, sdk) { element.textContent = 'Independent module'; signal = sdk.signal; return cleanup } })
    const { wrapper } = await setup()
    expect(wrapper.text()).toContain('Independent module')
    expect(signal?.aborted).toBe(false)
    wrapper.unmount()
    expect(cleanup).toHaveBeenCalledOnce()
    expect(signal?.aborted).toBe(true)
  })
  it('clears account one immediately and never exposes its late async mount to account two', async () => {
    let firstElement: HTMLElement | undefined
    let firstSdk: RuntimeModSdk | undefined
    let finish: ((cleanup: () => void) => void) | undefined
    const lateCleanup = vi.fn()
    vi.mocked(loadRuntimeMod).mockResolvedValueOnce({ mount(element, sdk) { firstElement = element; firstSdk = sdk; return new Promise((resolve) => { finish = resolve }) } })
    vi.mocked(loadRuntimeMod).mockResolvedValueOnce({ mount(element) { element.textContent = 'Account two'; return () => element.remove() } })
    const { wrapper, account } = await setup()
    account.tenantId = 2
    account.localUserId = 2
    await flushPromises()
    expect(firstSdk?.signal.aborted).toBe(true)
    if (firstElement) firstElement.textContent = 'Late private account one data'
    finish?.(lateCleanup)
    await flushPromises()
    expect(wrapper.text()).toContain('Account two')
    expect(wrapper.text()).not.toContain('Late private')
    expect(lateCleanup).toHaveBeenCalledOnce()
    wrapper.unmount()
  })
  it('does not import anything when current authentication or restart validation fails', async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce(new Response(JSON.stringify({ detail: '请先登录' }), { status: 401 }))
    const one = await setup()
    expect(one.wrapper.get('[role="alert"]').text()).toBe('请先登录')
    one.wrapper.unmount()
    vi.mocked(apiFetch).mockResolvedValueOnce(new Response(JSON.stringify({ success: true, data: { ...metadata(), requires_restart: true } })))
    const two = await setup()
    expect(two.wrapper.get('[role="alert"]').text()).toContain('重启客户端')
    expect(loadRuntimeMod).not.toHaveBeenCalled()
    two.wrapper.unmount()
  })
})

it('requests durable verification after mount and keeps the page usable when receipt delivery fails', async () => {
  vi.mocked(loadRuntimeMod).mockResolvedValue({ mount(element) { element.textContent = 'Usable private page'; return () => element.remove() } })
  vi.mocked(apiFetch).mockImplementation(async (path) => {
    if (path === '/api/mod-store/receipts/retry') throw new Error('network unavailable')
    return new Response(JSON.stringify({ success: true, data: metadata() }))
  })
  const { wrapper } = await setup()
  expect(apiFetch).toHaveBeenCalledWith('/api/mod-store/receipts/retry', expect.objectContaining({ method: 'POST', body: '{}' }))
  expect(wrapper.text()).toContain('Usable private page')
  expect(wrapper.text()).toContain('回执暂未确认')
  expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  wrapper.unmount()
})
