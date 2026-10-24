import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { onMounted, ref } from 'vue'
import { expect, it, vi } from 'vitest'
import App from './App.vue'

vi.mock('./components/MainLayout.vue', () => ({ default: { template: '<main><slot /></main>' } }))
vi.mock('@/components/shell/LegacyFloatPanels.vue', () => ({ default: { render: () => null } }))
vi.mock('@/components/shell/AppGlobalProviders.vue', () => ({ default: { render: () => null } }))
vi.mock('@/components/aiopen/VirtualCursorOverlay.vue', () => ({ default: { render: () => null } }))
vi.mock('@/composables/useAppBoot', () => ({ useAppBoot: () => ({ hideChrome: false, appReady: true, isAdminConsoleSpa: () => true }) }))
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
