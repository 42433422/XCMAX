import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { h, onMounted, ref } from 'vue'
import { expect, it, vi } from 'vitest'
import App from './App.vue'
import { useAccountProfileStore } from '@/stores/accountProfile'
const mode = vi.hoisted(() => ({ admin: true, desktop: false }))
vi.mock('@/utils/desktopShell', () => ({ isDesktopShell: () => mode.desktop }))

vi.mock('./components/MainLayout.vue', () => ({ default: { template: '<main><slot /></main>' } }))
vi.mock('@/components/shell/LegacyFloatPanels.vue', () => ({ default: { render: () => null } }))
vi.mock('@/components/shell/AppGlobalProviders.vue', () => ({ default: { render: () => null } }))
vi.mock('@/components/aiopen/VirtualCursorOverlay.vue', () => ({ default: { render: () => null } }))
vi.mock('@/composables/useAppBoot', () => ({ useAppBoot: () => ({ hideChrome: false, appReady: true, isAdminConsoleSpa: () => mode.admin }) }))
vi.mock('@/composables/usePrivateDeliverySync', () => ({ usePrivateDeliverySync: () => undefined }))

it('preserves an admin page and its input across anchor jumps, while query changes still reload it', async () => {
  let mounts = 0
  const page = {
    setup() { const draft = ref(''); onMounted(() => mounts++); return { draft } },
    template: '<section><input v-model="draft" /><div id="delivery-roster">客户台账</div></section>',
  }
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/delivery', component: page }] })
  await router.push('/delivery')
  const wrapper = mount(App, { global: { plugins: [router] } })
  await flushPromises()
  await wrapper.get('input').setValue('正在查阅的客户')
  await router.push('/delivery#delivery-roster')
  await flushPromises()
  expect(mounts).toBe(1)
  expect(wrapper.get('input').element.value).toBe('正在查阅的客户')
  await router.push('/delivery?stage=acceptance#delivery-roster')
  await flushPromises()
  expect(mounts).toBe(2)
  expect(wrapper.get('input').element.value).toBe('')
  wrapper.unmount()
})


it('caches desktop pages and retires them on identity or permission changes', async () => {
  mode.admin = false; mode.desktop = true
  const account = useAccountProfileStore()
  account.loaded = true; account.localUserId = 1
  let mounts = 0
  const page = { setup() { const draft = ref(''); onMounted(() => mounts++); return { draft } }, template: '<section><input v-model="draft" /></section>' }
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/one', component: page }, { path: '/two', component: { template: '<section>other</section>' } }] })
  await router.push('/one')
  const wrapper = mount(App, { global: { plugins: [router] } })
  await flushPromises(); await wrapper.get('input').setValue('draft')
  await router.push('/two'); await router.push('/one'); await flushPromises()
  expect(mounts).toBe(1); expect(wrapper.get('input').element.value).toBe('draft')
  account.permissions = ['new.permission']; await flushPromises()
  expect(mounts).toBe(2); expect(wrapper.get('input').element.value).toBe('')
  await wrapper.get('input').setValue('private')
  account.localUserId = 2; await flushPromises()
  expect(mounts).toBe(3); expect(wrapper.get('input').element.value).toBe('')
  account.loaded = false; await flushPromises()
  expect(mounts).toBe(4)
  wrapper.unmount(); mode.admin = true; mode.desktop = false
})

it('limits the desktop cache and handles rapid route changes', async () => {
  mode.admin = false; mode.desktop = true
  let mounts = 0
  const page = { setup() { onMounted(() => mounts++); return {} }, template: '<section>page</section>' }
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/page/:id', component: page }] })
  await router.push('/page/0')
  const wrapper = mount(App, { global: { plugins: [router] } })
  await flushPromises()
  for (let i = 1; i <= 12; i++) { await router.push(`/page/${i}`); await flushPromises() }
  await router.push('/page/0'); await flushPromises()
  expect(mounts).toBe(14)
  const first = router.push('/page/1'); const second = router.push('/page/2')
  await Promise.allSettled([first, second]); await flushPromises()
  expect(router.currentRoute.value.path).toBe('/page/2')
  expect(wrapper.text()).toContain('page')
  wrapper.unmount(); mode.admin = true; mode.desktop = false
})

it.each([80, 450])('shows async page content immediately after its %sms setup, without a bare-text flash', async (delay) => {
  vi.useFakeTimers({ toFake: ['Date', 'setTimeout', 'clearTimeout'] })
  mode.admin = false; mode.desktop = true
  const page = {
    async setup() {
      await new Promise(resolve => setTimeout(resolve, delay))
      return () => h('section', { 'data-testid': 'async-page' }, 'ready')
    },
  }
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/async', component: page }] })
  await router.push('/async')
  const wrapper = mount(App, { global: { plugins: [router] } })
  try {
    await flushPromises()
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
    if (delay > 280) {
      await vi.advanceTimersByTimeAsync(280)
      expect(wrapper.get('[role="status"]').text()).toBe('页面加载中…')
    }
    await vi.advanceTimersByTimeAsync(delay > 280 ? delay - 280 : delay)
    await flushPromises()
    expect(wrapper.get('[data-testid="async-page"]').text()).toBe('ready')
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
  } finally {
    wrapper.unmount(); mode.admin = true; mode.desktop = false
    vi.useRealTimers()
  }
})
