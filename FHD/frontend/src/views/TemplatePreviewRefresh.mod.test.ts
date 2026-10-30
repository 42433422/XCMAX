import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, KeepAlive } from 'vue'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import { assembleTemplatePreview } from '../../../mods/xcagi-erp-domain-bridge/frontend/views/template-preview/assemble'

const listTemplates = vi.hoisted(() => vi.fn())
vi.mock('@/api/templatePreview', () => ({ default: { listTemplates } }))
let wrapper: VueWrapper | undefined
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.clearAllMocks() })

it('shows templates saved from ETL after returning to a retained library, and retires its listener', async () => {
  let templates = [{ id: 1, name: '原有模板' }]
  listTemplates.mockImplementation(async () => ({ success: true, templates: [...templates] }))
  const library = defineComponent({
    setup: assembleTemplatePreview,
    template: '<section><p v-for="item in templates" :key="item.id">{{ item.name }}</p></section>',
  })
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/templates', component: library },
    { path: '/etl', component: { template: '<section>数据对接中心</section>' } },
  ] })
  await router.push('/templates')
  wrapper = mount(defineComponent({ components: { RouterView, KeepAlive },
    template: '<RouterView v-slot="{ Component }"><KeepAlive><component :is="Component" /></KeepAlive></RouterView>',
  }), { global: { plugins: [router] } })
  await flushPromises()
  expect(wrapper.text()).toContain('原有模板')
  expect(listTemplates).toHaveBeenCalledTimes(1)

  await router.push('/etl')
  templates = [...templates, { id: 2, name: '生产单清理模板' }]
  window.dispatchEvent(new CustomEvent('xcagi:templates-updated', { detail: { source: 'etl-center' } }))
  window.dispatchEvent(new CustomEvent('xcagi:templates-updated', { detail: { source: 'etl-center' } }))
  await flushPromises()
  expect(listTemplates).toHaveBeenCalledTimes(1)
  await router.push('/templates')
  await flushPromises()
  expect(listTemplates).toHaveBeenCalledTimes(2)
  expect(wrapper.text()).toContain('生产单清理模板')
  expect(wrapper.text()).toContain('原有模板')

  templates = [...templates, { id: 3, name: '检验说明模板' }]
  window.dispatchEvent(new CustomEvent('xcagi:templates-updated'))
  await flushPromises()
  expect(wrapper.text()).toContain('检验说明模板')
  expect(listTemplates).toHaveBeenCalledTimes(3)
  wrapper.unmount(); wrapper = undefined
  window.dispatchEvent(new CustomEvent('xcagi:templates-updated'))
  await flushPromises()
  expect(listTemplates).toHaveBeenCalledTimes(3)
})
