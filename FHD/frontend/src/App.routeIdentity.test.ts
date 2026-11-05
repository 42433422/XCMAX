import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { h, onMounted, ref, type Ref } from 'vue'
import { expect, it, vi } from 'vitest'
import App from './App.vue'
import { useAccountProfileStore } from '@/stores/accountProfile'
const mode = vi.hoisted(() => ({ admin: true, desktop: false, viewPending: undefined as Ref<boolean> | undefined }))
vi.mock('@/utils/desktopShell', () => ({ isDesktopShell: () => mode.desktop }))

vi.mock('./components/MainLayout.vue', () => ({ default: { template: '<main><slot /></main>' } }))
vi.mock('@/components/shell/LegacyFloatPanels.vue', () => ({ default: { render: () => null } }))
vi.mock('@/components/shell/AppGlobalProviders.vue', () => ({ default: { render: () => null } }))
vi.mock('@/components/aiopen/VirtualCursorOverlay.vue', () => ({ default: { render: () => null } }))
vi.mock('@/composables/useAppBoot', () => ({ useAppBoot: (viewPending: Ref<boolean>) => { mode.viewPending = viewPending; return ({ hideChrome: false, appReady: ref(true), startupVisible: ref(false), startupError: ref(''), startupStage: ref(''), retryStartup: vi.fn(), cancelStartup: vi.fn(), isAdminConsoleSpa: () => mode.admin }) } }))
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


it('keeps cached desktop pages across permission refreshes and retires them on identity changes', async () => {
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
  expect(mounts).toBe(1); expect(wrapper.get('input').element.value).toBe('draft')
  account.loaded = false; await flushPromises()
  expect(mounts).toBe(1)
  account.localUserId = 2; await flushPromises()
  expect(mounts).toBe(2); expect(wrapper.get('input').element.value).toBe('')
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
  expect(mounts).toBe(13)
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
    expect(mode.viewPending?.value).toBe(true)
    if (delay > 280) {
      await vi.advanceTimersByTimeAsync(280)
      expect(wrapper.get('[role="status"]').text()).toContain('页面加载中…')
      expect(wrapper.get('[role="status"]').text()).toContain('正在准备页面内容')
    }
    await vi.advanceTimersByTimeAsync(delay > 280 ? delay - 280 : delay)
    await flushPromises()
    expect(wrapper.get('[data-testid="async-page"]').text()).toBe('ready')
    expect(mode.viewPending?.value).toBe(false)
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
  } finally {
    wrapper.unmount(); mode.admin = true; mode.desktop = false
    vi.useRealTimers()
  }
})

it('keeps the current async view pending when a retired route resolves', async () => {
  mode.admin = false; mode.desktop = true
  let releaseOld!: () => void, releaseCurrent!: () => void
  const old = new Promise<void>(resolve => { releaseOld = resolve })
  const current = new Promise<void>(resolve => { releaseCurrent = resolve })
  const page = (ready: Promise<void>, text: string) => ({ async setup() { await ready; return () => h('section', text) } })
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/old', component: page(old, 'old') }, { path: '/current', component: page(current, 'current') },
  ] })
  await router.push('/old')
  const wrapper = mount(App, { global: { plugins: [router] } })
  try {
    await flushPromises()
    expect(mode.viewPending?.value).toBe(true)
    await router.push('/current'); await flushPromises()
    releaseOld(); await flushPromises()
    expect(mode.viewPending?.value).toBe(true)
    releaseCurrent(); await flushPromises()
    expect(mode.viewPending?.value).toBe(false)
    expect(wrapper.text()).toContain('current')
  } finally { wrapper.unmount(); mode.admin = true; mode.desktop = false }
})

it('does not release a new account view when the old account setup resolves', async () => {
  mode.admin = false; mode.desktop = true
  const account = useAccountProfileStore()
  account.loaded = true; account.localUserId = 101
  let releaseOld!: () => void, releaseCurrent!: () => void
  const old = new Promise<void>(resolve => { releaseOld = resolve })
  const current = new Promise<void>(resolve => { releaseCurrent = resolve })
  let mounts = 0
  const page = { async setup() { const own = ++mounts; await (own === 1 ? old : current); return () => h('section', `view-${own}`) } }
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/private', component: page }] })
  await router.push('/private')
  const wrapper = mount(App, { global: { plugins: [router] } })
  try {
    await flushPromises()
    expect(mode.viewPending?.value).toBe(true)
    account.localUserId = 202
    await flushPromises()
    releaseOld(); await flushPromises()
    expect(mode.viewPending?.value).toBe(true)
    releaseCurrent(); await flushPromises()
    expect(mode.viewPending?.value).toBe(false)
    expect(wrapper.text()).toContain('view-2')
  } finally { wrapper.unmount(); mode.admin = true; mode.desktop = false }
})
