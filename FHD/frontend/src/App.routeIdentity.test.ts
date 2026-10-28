import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { onMounted, reactive, ref } from 'vue'
import { expect, it, vi } from 'vitest'
import App from './App.vue'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'

const mode = vi.hoisted(() => ({ admin: true, desktop: false }))

vi.mock('./components/MainLayout.vue', () => ({ default: { template: '<main><slot /></main>' } }))
vi.mock('@/components/shell/LegacyFloatPanels.vue', () => ({ default: { render: () => null } }))
vi.mock('@/components/shell/AppGlobalProviders.vue', () => ({ default: { render: () => null } }))
vi.mock('@/components/aiopen/VirtualCursorOverlay.vue', () => ({ default: { render: () => null } }))
vi.mock('@/composables/useAppBoot', () => ({ useAppBoot: () => ({ hideChrome: false, appReady: true, isAdminConsoleSpa: () => mode.admin }) }))
vi.mock('@/utils/desktopShell', () => ({ isDesktopShell: () => mode.desktop }))
vi.mock('@/stores/accountProfile', () => ({ useAccountProfileStore: () => account }))
vi.mock('@/composables/usePrivateDeliverySync', () => ({ usePrivateDeliverySync: () => undefined }))
const account = reactive({ impersonatingMarketUserId: null as number | null })

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

it('caches desktop pages without a transition and clears cached pages on account change', async () => {
  mode.admin = false
  mode.desktop = true
  let mounts = 0
  const page = { setup() { const draft = ref(''); onMounted(() => mounts++); return { draft } }, template: '<section><input v-model="draft" /></section>' }
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/one', component: page }, { path: '/two', component: { template: '<div>two</div>' } }] })
  await router.push('/one')
  const wrapper = mount(App, { global: { plugins: [router] } })
  await flushPromises()
  await wrapper.get('input').setValue('保留草稿')
  await router.push('/two'); await flushPromises()
  await router.push('/one'); await flushPromises()
  expect(mounts).toBe(1)
  expect(wrapper.get('input').element.value).toBe('保留草稿')
  await router.push('/two'); await flushPromises()
  productReadAccountEpoch.value++
  await router.push('/one'); await flushPromises()
  expect(mounts).toBe(2)
  expect(wrapper.get('input').element.value).toBe('')
  await wrapper.get('input').setValue('不可跨身份读取')
  await router.push('/two'); await flushPromises()
  account.impersonatingMarketUserId = 42
  await router.push('/one'); await flushPromises()
  expect(mounts).toBe(3)
  expect(wrapper.get('input').element.value).toBe('')
  wrapper.unmount()
  account.impersonatingMarketUserId = null
  mode.admin = true
  mode.desktop = false
})
