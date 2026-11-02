import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import EltCenterView from './EltCenterView.vue'

const archive = vi.hoisted(() => ({
  reviewedExcelIdentity: vi.fn(),
  archiveClassifyExcel: vi.fn(),
  confirmClassification: vi.fn(),
  reviewExcel: vi.fn(),
  analyzeClassification: vi.fn(), autoSlices: vi.fn(), recentClassifications: vi.fn(), previewReviewedIntake: vi.fn(),
}))
const legacy = vi.hoisted(() => ({ upload: vi.fn(), preview: vi.fn(), execute: vi.fn() }))
vi.mock('@/api/templatePreview', () => ({ default: archive }))
vi.mock('@/api/elt', () => ({ eltApi: legacy }))
vi.mock('@/api/xcmaxMarketProxy', () => ({
  default: { llmResolveChatDefault: vi.fn().mockResolvedValue({ ok: true, provider: 'platform', model: 'default-chat' }) },
}))

const authorization = { status: 'authorized', operations: { classification: 'authorized', template_candidates: 'authorized' } }
function classified(name: string) {
  return {
    name,
    status: 'classified',
    classification_id: `classification:${name}`,
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

const layout = (value: string) => [{ sheet: '生产单', widths: [20], rows: [{ height: 20, cells: [{ cell: 'A1', value,
  formula: false, rowspan: 1, colspan: 1, bold: true, italic: false, font_size: 11, font_color: '', fill: '', align: 'left' }] }], truncated: false }]
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
    model: 'returned',
    layout: layout(`原件 ${id}`),
    selected_region: { selection_basis: 'model_group' },
    proposal: {
      version: `${id}-v1`,
      parent_version: null,
      candidates,
      evidence: [],
      model: { status: 'returned', login_authorization: authorization },
      result_previews: candidates.map(candidate => ({
        candidate_id: candidate.id,
        sha256: `${id}-${candidate.id}`,
        layout: layout(candidate.label),
        layout_truncated: false,
      })),
    },
  }
}

const Shell = defineComponent({ template: '<RouterView v-slot="{ Component, route }"><KeepAlive :max="12"><component :is="Component" :key="String(route.name || route.path)" /></KeepAlive></RouterView>' })
let wrapper: VueWrapper | undefined
beforeEach(() => {
  vi.clearAllMocks()
  archive.reviewedExcelIdentity.mockResolvedValue({ actor: '1:7', login_authorization: authorization })
  archive.archiveClassifyExcel.mockImplementation(async (form: FormData) => classified((form.get('file') as File).name))
  archive.analyzeClassification.mockResolvedValue({ version: 'model-v2', model_status: 'returned', sheets: classified('synthetic.xlsx').sheets })
  archive.autoSlices.mockImplementation(async (id: string) => ({ slices: [{ index: 0, basis: 'model_group', confirmed: false,
    sha256: `slice:${id}`, filename: id.replace('classification:', ''), display_name: id.replace('classification:', '').replace(/\.xlsx$/, ''),
    fragments: [{ sheet: '生产单', range: 'A1:D4' }] }] }))
  archive.reviewExcel.mockImplementation(async (form: FormData) => reviewPayload((form.get('file') as File).name))
  archive.recentClassifications.mockResolvedValue({ files: [] })
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
      const sources = files.map(name => new File(['生产资料'], name))
      Object.defineProperty(input.element, 'files', { configurable: true, value: sources })
      await input.trigger('change'); await flushPromises()
      const start = wrapper!.findAll('button').find(button => button.text() === '开始处理')
      if (!start) throw new Error('missing start processing button')
      await start.trigger('click'); await flushPromises()
      return sources
    }
    const firstFiles = await choose(['production.xlsx'])
    expect(archive.archiveClassifyExcel).toHaveBeenCalledTimes(1)
    expect(archive.analyzeClassification).toHaveBeenCalledTimes(1)
    expect(archive.reviewExcel).toHaveBeenCalledTimes(1)
    expect((archive.reviewExcel.mock.calls[0][0] as FormData).get('file')).toBe(firstFiles[0])
    const firstDocumentKey = wrapper.get('[data-document-key]').attributes('data-document-key')
    await router.push('/products'); await flushPromises()
    await router.push('/business-docking'); await flushPromises()
    expect(wrapper.get('input[type="file"][multiple]').element).toBe(input.element)
    expect(input.element.isConnected).toBe(true)
    expect(wrapper.text()).toContain('production.xlsx')
    expect(wrapper.get('[data-document-key]').attributes('data-document-key')).toBe(firstDocumentKey)
    expect(archive.archiveClassifyExcel).toHaveBeenCalledTimes(1)
    expect(archive.reviewExcel).toHaveBeenCalledTimes(1)
    const resetInput = vi.spyOn(input.element, 'value', 'set')
    const nextFiles = await choose([...names])
    expect(resetInput).toHaveBeenCalledWith('')
    expect(archive.archiveClassifyExcel).toHaveBeenCalledTimes(1 + names.length)
    expect(archive.analyzeClassification).toHaveBeenCalledTimes(1 + names.length)
    expect(archive.reviewExcel).toHaveBeenCalledTimes(1 + names.length)
    expect(archive.confirmClassification).not.toHaveBeenCalled()
    for (const [index, source] of nextFiles.entries()) {
      const archiveForm = archive.archiveClassifyExcel.mock.calls[index + 1][0] as FormData
      const reviewForm = archive.reviewExcel.mock.calls[index + 1][0] as FormData
      expect(archiveForm.get('file')).toBe(source)
      expect(reviewForm.get('file')).toBe(source)
      expect([reviewForm.get('classification_id'), reviewForm.get('classification_version'), reviewForm.get('auto_slice_index'), reviewForm.get('use_login_notice')]).toEqual([`classification:${source.name}`, 'model-v2', '0', 'true'])
    }
    const firstArchive = archive.archiveClassifyExcel.mock.calls[0][0] as FormData
    expect((archive.archiveClassifyExcel.mock.calls[1][0] as FormData).get('request_key')).not.toBe(firstArchive.get('request_key'))
    // Each named model document opens its own three candidates and read-only source.
    expect(wrapper.findAll('.classification-region')).toHaveLength(0)
    expect(wrapper.findAll('.reviewed-template__preview--a4')).toHaveLength(0)
    const documents = wrapper.findAll('[data-document-key]')
    expect(documents).toHaveLength(names.length)
    expect(wrapper.find('[role=dialog]').exists()).toBe(false)
    for (const [index, name] of names.entries()) {
      await documents[index].trigger('click'); await flushPromises()
      expect(wrapper.get('[role=dialog]').attributes('aria-label')).toBe(name.replace(/\.xlsx$/, ''))
      expect(wrapper.findAll('.reviewed-template__preview--a4')).toHaveLength(4)
      expect(wrapper.get('.reviewed-document-picker__original').text()).toContain(`原件 ${name}`)
      expect(wrapper.get('.reviewed-document-picker__original').find('.reviewed-template__select-candidate').exists()).toBe(false)
      expect(wrapper.findAll('.reviewed-template__select-candidate')).toHaveLength(3)
      await wrapper.get('[aria-label="关闭可选模板"]').trigger('click'); await flushPromises()
    }
    expect(archive.reviewExcel).toHaveBeenCalledTimes(1 + names.length)
    expect(archive.previewReviewedIntake).not.toHaveBeenCalled()
    for (const name of names) expect(wrapper.text()).toContain(name)
    expect(wrapper.find('.etl-dropzone').exists()).toBe(false)
    expect(legacy.upload).not.toHaveBeenCalled(); expect(legacy.preview).not.toHaveBeenCalled(); expect(legacy.execute).not.toHaveBeenCalled()
  })
})
