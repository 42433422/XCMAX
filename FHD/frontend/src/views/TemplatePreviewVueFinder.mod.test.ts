import { describe, expect, it, vi } from 'vitest'
import { defineComponent, nextTick, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { assembleTemplatePreview, TEMPLATE_SEARCH_STORAGE_KEY } from '../../../mods/bridge/xcagi-erp-domain-bridge/frontend/views/template-preview/assemble'
import TemplatePreviewView from '../../../mods/bridge/xcagi-erp-domain-bridge/frontend/views/TemplatePreviewView.vue'
import { useTpVueFinder } from '../../../mods/bridge/xcagi-erp-domain-bridge/frontend/views/template-preview/useTpVueFinder'
import type { TemplatePreviewCtx } from '../../../mods/bridge/xcagi-erp-domain-bridge/frontend/views/template-preview/assemble'
import type { TplRecord } from '../../../mods/bridge/xcagi-erp-domain-bridge/frontend/views/template-preview/tpTemplateMeta'

const listTemplates = vi.hoisted(() => vi.fn())
vi.mock('@/api/templatePreview', () => ({ default: { listTemplates } }))

vi.mock('@/components/template/vuefinder', () => ({ ArrayDriver: class { constructor(public options: unknown) {} }, VueFinder: { props: ['driver'], template: `<div><p v-for="file in driver.options.files.value.filter(e => e.type === 'file')" :key="file.path">{{ file.basename }}</p></div>` }, VueFinderPlugin: { install() {} }, zhCN: {} }))

function setup() {
  const records = ref<TplRecord[]>([
    { id: 'first/id', name: '同名模板', category: 'excel' },
    { id: 'second', name: '同名模板', category: 'excel' },
  ])
  const previewTemplate = vi.fn()
  const finder = useTpVueFinder({
    filteredTemplates: records, getTemplateScopeLabel: () => '销售/出货', previewTemplate,
  } as unknown as TemplatePreviewCtx)
  return { records, previewTemplate, finder }
}

describe('template library record identity', () => {
  it('keeps duplicate display names independently selectable and previewable', () => {
    const { records, previewTemplate, finder } = setup()
    const files = finder.entries.value.filter(entry => entry.type === 'file')
    expect(files[0].basename).toBe(files[1].basename)
    expect(files[0].path).not.toBe(files[1].path)
    for (const [index, file] of files.entries()) {
      finder.onSelect([file])
      // The view passes this exact record to edit/replace/delete actions too.
      expect(finder.selectedTemplate.value?.id).toBe(records.value[index].id)
      const preventDefault = vi.fn()
      finder.onFileDclick({ item: file, preventDefault })
      expect(preventDefault).toHaveBeenCalledOnce()
      expect(previewTemplate).toHaveBeenLastCalledWith(records.value[index])
    }
  })

  it('refreshes selected data by ID after a rename and clears it after removal', async () => {
    const { records, finder } = setup()
    const file = finder.entries.value.find(entry => entry.type === 'file')!
    finder.onSelect([file])
    records.value = [{ ...records.value[0], name: '重命名', filename: 'new.xlsx' }, records.value[1]]
    await nextTick()
    expect(finder.entries.value.find(entry => entry.path === file.path)?.basename).toBe('重命名.xlsx')
    expect(finder.selectedTemplate.value).toEqual(records.value[0])
    records.value = [records.value[1]]
    await nextTick()
    expect(finder.selectedTemplate.value).toBeNull()
    finder.onSelect([file])
    expect(finder.selectedTemplate.value).toBeNull()
    finder.onSelect([])
    expect(finder.selectedTemplate.value).toBeNull()
  })
})


it('applies route scope/keyword and both global-search handoffs to the actual finder entries', async () => {
  listTemplates.mockResolvedValue({ success: true, templates: [
    { id: 'db:1', name: 'Alpha 出货', category: 'word', business_scope: 'orders' },
    { id: 'db:2', name: 'Beta 出货', category: 'word', business_scope: 'orders' },
    { id: 'db:3', name: 'Alpha 产品', category: 'word', business_scope: 'products' },
  ] })
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/templates', component: { template: '<div />' } },
  ] })
  await router.push('/templates?scope=orders&keyword=Alpha')
  const wrapper = mount(defineComponent({
    setup() { return useTpVueFinder(assembleTemplatePreview()) },
    template: '<p v-for="file in entries.filter(e => e.type === \'file\')" :key="file.path">{{ file.basename }}</p>',
  }), { global: { plugins: [router] } })
  try {
    await flushPromises()
    expect(wrapper.text()).toBe('Alpha 出货.docx')
    await router.push('/templates?scope=products&keyword=Alpha')
    await flushPromises()
    expect(wrapper.text()).toBe('Alpha 产品.docx')
    await router.push('/templates?scope=orders&keyword=Beta')
    await flushPromises()
    expect(wrapper.text()).toBe('Beta 出货.docx')
    window.dispatchEvent(new CustomEvent('xcagi:template-search', { detail: { keyword: 'Alpha' } }))
    await nextTick()
    expect(wrapper.text()).toBe('Alpha 出货.docx')
    await router.push('/templates?scope=orders&keyword=missing')
    await flushPromises()
    expect(wrapper.text()).toBe('')
    sessionStorage.setItem(TEMPLATE_SEARCH_STORAGE_KEY, 'Beta')
  } finally { wrapper.unmount() }
  const handoffRouter = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/templates', component: { template: '<div />' } },
  ] })
  await handoffRouter.push('/templates?scope=orders')
  const remounted = mount(defineComponent({
    setup() { return useTpVueFinder(assembleTemplatePreview()) },
    template: '<p v-for="file in entries.filter(e => e.type === \'file\')" :key="file.path">{{ file.basename }}</p>',
  }), { global: { plugins: [handoffRouter] } })
  try {
    await flushPromises()
    expect(remounted.text()).toBe('Beta 出货.docx')
    expect(sessionStorage.getItem(TEMPLATE_SEARCH_STORAGE_KEY)).toBeNull()
  } finally { remounted.unmount(); sessionStorage.removeItem(TEMPLATE_SEARCH_STORAGE_KEY) }
})


it('offers visible recovery from an empty handed-off filter and preserves other navigation', async () => {
  listTemplates.mockResolvedValue({ success: true, templates: [
    { id: 'db:1', name: 'Alpha 出货', category: 'word', business_scope: 'orders' },
    { id: 'db:2', name: 'Beta 产品', category: 'word', business_scope: 'products' },
  ] })
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/templates', component: { template: '<div />' } },
    { path: '/business-docking', component: { template: '<div />' } },
  ] })
  await router.push('/templates?scope=orders&keyword=missing&keep=yes')
  const wrapper = mount(TemplatePreviewView, { global: { plugins: [router], stubs: {
    TpCreateModal: true, TpPreviewModal: true, TpEditModal: true, TpReplaceModal: true,
  } } })
  try {
    await flushPromises()
    const reset = wrapper.get('[data-testid="reset-template-filters"]')
    expect(reset.text()).toContain('显示全部模板')
    expect(wrapper.text()).not.toContain('Alpha 出货')
    expect(wrapper.text()).not.toContain('Beta 产品')
    await reset.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query).toEqual({ keep: 'yes' })
    expect(wrapper.find('[data-testid="reset-template-filters"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('Alpha 出货')
    expect(wrapper.text()).toContain('Beta 产品')
    expect(wrapper.find('.grid-tool-card').exists()).toBe(false)
    const mapping = wrapper.get('a[href="/business-docking"]')
    expect(mapping.text()).toBe('AI 识别与映射')
    await mapping.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/business-docking')
  } finally { wrapper.unmount() }
})
