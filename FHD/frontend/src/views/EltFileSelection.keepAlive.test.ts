import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import EltCenterView from './EltCenterView.vue'

const archive = vi.hoisted(() => ({
  archiveClassifyExcel: vi.fn(),
  confirmClassification: vi.fn(),
  reviewExcel: vi.fn(),
}))
const legacy = vi.hoisted(() => ({ upload: vi.fn(), preview: vi.fn(), execute: vi.fn() }))
vi.mock('@/api/templatePreview', () => ({ default: archive }))
vi.mock('@/api/elt', () => ({ eltApi: legacy }))
vi.mock('@/api/xcmaxMarketProxy', () => ({
  default: { llmResolveChatDefault: vi.fn().mockResolvedValue({ ok: true, provider: 'platform', model: 'default-chat' }) },
}))

function classified(name: string) {
  return {
    name,
    status: 'classified',
    classification_id: crypto.randomUUID(),
    version: 'v1',
    sheets: [{
      sheet: '生产单',
      labels: ['unknown'],
      checked_cells: 1,
      evidence: [],
      regions: [{
        range: 'A1:D4',
        labels: ['unknown'],
        checked_cells: 1,
        parent_heading: '',
        dependency_status: '待确认',
        needs_confirmation: true,
        header_cells: [],
        merged_ranges: [],
        possible_shared_context: [],
        evidence: [],
      }],
    }],
  }
}

function reviewPayload(id: string) {
  const candidates = [0, 1, 2].map(index => ({
    id: `candidate-${index}`,
    label: `候选${index + 1}`,
    explanation: '保留未确认内容',
    clear: [],
  }))
  return {
    review_id: id,
    sha256: 'sha',
    cells: [],
    sheets: ['生产单'],
    model: 'not_called',
    proposal: {
      version: `${id}-v1`,
      parent_version: null,
      candidates,
      evidence: [],
      model: { status: 'not_called' },
      result_previews: candidates.map(candidate => ({
        candidate_id: candidate.id,
        sha256: 'sha',
        layout: [],
        layout_truncated: false,
      })),
    },
  }
}

const Shell = defineComponent({ template: '<RouterView v-slot="{ Component, route }"><KeepAlive :max="12"><component :is="Component" :key="String(route.name || route.path)" /></KeepAlive></RouterView>' })
let wrapper: VueWrapper | undefined
beforeEach(() => {
  vi.clearAllMocks()
  archive.archiveClassifyExcel.mockImplementation(async (form: FormData) => classified((form.get('file') as File).name))
  archive.confirmClassification.mockImplementation(async () => ({ ...classified('confirmed.xlsx'), version: 'v2', confirmed: true }))
  archive.reviewExcel.mockImplementation(async (form: FormData) => reviewPayload(String(form.get('region_range') || 'A1:D4')))
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.restoreAllMocks() })

describe('archive selection through the actual kept-alive docking route', () => {
  it.each([
    ['same file', ['production.xlsx']],
    ['another file', ['materials.xlsx']],
    ['multiple workbooks', ['materials.xlsx', 'inspection.xlsx']],
  ] as const)('archives %s after navigating away without recreating the old business import', async (_case, names) => {
    const router = createRouter({ history: createMemoryHistory(), routes: [
      { path: '/business-docking', name: 'business-docking', component: EltCenterView },
      { path: '/products', name: 'products', component: { template: '<div>产品列表</div>' } },
      { path: '/template-preview', component: { template: '<div>模板库</div>' } },
    ] })
    await router.push('/business-docking'); await router.isReady()
    wrapper = mount(Shell, { attachTo: document.body, global: { plugins: [router] } }); await flushPromises()
    const input = wrapper.get<HTMLInputElement>('input[type="file"][multiple]')
    const choose = async (files: string[]) => {
      Object.defineProperty(input.element, 'files', { configurable: true, value: files.map(name => new File(['生产资料'], name)) })
      await input.trigger('change'); await flushPromises()
      const start = wrapper!.findAll('button').find(button => button.text() === '开始处理')
      if (!start) throw new Error('missing start processing button')
      await start.trigger('click'); await flushPromises()
    }
    await choose(['production.xlsx'])
    expect(archive.archiveClassifyExcel).toHaveBeenCalledTimes(1)
    await router.push('/products'); await flushPromises()
    await router.push('/business-docking'); await flushPromises()
    expect(wrapper.get('input[type="file"][multiple]').element).toBe(input.element)
    expect(input.element.isConnected).toBe(true)
    expect(wrapper.text()).toContain('production.xlsx')
    const resetInput = vi.spyOn(input.element, 'value', 'set')
    await choose([...names])
    expect(resetInput).toHaveBeenCalledWith('')
    expect(archive.archiveClassifyExcel).toHaveBeenCalledTimes(1 + names.length)
    // User intake hides classification DOM; success opens A4 template picker instead.
    expect(wrapper.findAll('.classification-region')).toHaveLength(0)
    expect(wrapper.findAll('.reviewed-template__preview--a4')).toHaveLength(3)
    for (const name of names) expect(wrapper.text()).toContain(name)
    expect(wrapper.find('.etl-dropzone').exists()).toBe(false)
    expect(legacy.upload).not.toHaveBeenCalled(); expect(legacy.preview).not.toHaveBeenCalled(); expect(legacy.execute).not.toHaveBeenCalled()
  })
})
