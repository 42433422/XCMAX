import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import Sidebar from './Sidebar.vue'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { useIndustryStore } from '@/stores/industry'
import { useModsStore } from '@/stores/mods'

const api = vi.hoisted(() => ({
  getCurrentEntitlementsSyncStatus: vi.fn(),
  pullSync: vi.fn(),
  checkDeployUpdates: vi.fn(),
}))
vi.mock('@/api/xcmaxAdmin', () => ({ xcmaxAdminApi: api }))

let wrapper: VueWrapper | undefined
beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-10-07T12:00:00Z'))
  localStorage.clear()
  sessionStorage.clear()
  setActivePinia(createPinia())
  const account = useAccountProfileStore()
  account.loaded = true
  account.companyBrand = 'SUNBIRD'
  account.marketUserId = 29
  account.tenantId = 1
  account.localUserId = 2
  useIndustryStore().isLoaded = true
  useModsStore().isLoaded = true
  api.getCurrentEntitlementsSyncStatus.mockReset().mockResolvedValue({ data: { has_snapshot: true, snapshot: { username: 'SUNBIRD' } } })
  api.pullSync.mockReset()
  api.checkDeployUpdates.mockReset()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ status: 'healthy', version: '1.0.0.5' }) }))
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  vi.clearAllTimers()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})
async function openSidebar(activeView = 'chat') {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', name: 'chat', component: { template: '<div />' } }] })
  await router.push('/')
  await router.isReady()
  wrapper = mount(Sidebar, { props: { activeView }, attachTo: document.body, global: { plugins: [router], stubs: { DesktopAppUpdatePrompt: true } } })
  await flushPromises()
  return wrapper
}

describe('Sidebar customer navigation and runtime status', () => {
  it('shows the current customer and installed version without reading administrator deployment data', async () => {
    const view = await openSidebar()
    expect(view.find('.sidebar-brand-text').text()).toContain('SUNBIRD')
    expect(view.text()).toContain('v1.0.0.5')
    expect(api.checkDeployUpdates).not.toHaveBeenCalled()
    expect(api.pullSync).not.toHaveBeenCalled()
  })

  it('routes settings from the visible button and suppresses rapid duplicate selections', async () => {
    const view = await openSidebar()
    const settings = view.get('button[data-view="settings"]')
    await settings.trigger('click')
    await settings.trigger('click')
    expect(view.emitted('change-view')).toEqual([['settings']])
    vi.advanceTimersByTime(81)
    await settings.trigger('click')
    expect(view.emitted('change-view')).toHaveLength(2)
    await view.setProps({ activeView: 'settings' })
    expect(settings.attributes('aria-current')).toBe('page')
  })

  it('lets the runtime status open settings and keeps unavailable health distinct from normal service', async () => {
    vi.mocked(fetch).mockRejectedValue(new Error('offline'))
    const view = await openSidebar()
    const health = view.get('.runtime-health-button')
    expect(health.text()).not.toBe('系统正常')
    await health.trigger('click')
    expect(view.emitted('change-view')).toEqual([['settings']])
  })

  it('retains a usable brand image when each startup asset fails', async () => {
    const view = await openSidebar()
    const image = view.get('.sidebar-brand-logo')
    for (const suffix of ['xc-logo-text.jpg', 'xc-logo-base.jpg', 'vite.svg', 'vite.svg']) {
      await image.trigger('error')
      expect(image.attributes('src')).toContain(suffix)
    }
  })

  it('supports keyboard navigation between actual visible menu buttons', async () => {
    const view = await openSidebar()
    const buttons = view.findAll('nav button.menu-item[data-view]')
    expect(buttons.length).toBeGreaterThan(1)
    await buttons[0].trigger('keydown', { key: 'End' })
    expect(document.activeElement).toBe(buttons.at(-1)?.element)
    await buttons.at(-1)!.trigger('keydown', { key: 'Home' })
    expect(document.activeElement).toBe(buttons[0].element)
    await buttons[0].trigger('keydown', { key: 'ArrowDown' })
    expect(document.activeElement).toBe(buttons[1].element)
    await buttons[1].trigger('keydown', { key: 'ArrowUp' })
    expect(document.activeElement).toBe(buttons[0].element)
  })

  it('polls local entitlement snapshots and stops polling when the customer leaves the view', async () => {
    const view = await openSidebar()
    expect(api.getCurrentEntitlementsSyncStatus).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(30_000)
    expect(api.getCurrentEntitlementsSyncStatus).toHaveBeenCalledTimes(2)
    expect(api.pullSync).not.toHaveBeenCalled()
    view.unmount()
    wrapper = undefined
    await vi.advanceTimersByTimeAsync(60_000)
    expect(api.getCurrentEntitlementsSyncStatus).toHaveBeenCalledTimes(2)
  })
})
