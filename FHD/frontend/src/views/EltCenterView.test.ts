import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { readActiveExtensionModIdFromStorage } from '@/utils/xcagiStorageKeys'
enableAutoUnmount(afterEach)
const { archive, legacy } = vi.hoisted(() => ({
  archive: {
    reviewedExcelIdentity: vi.fn(),
    archiveClassifyExcel: vi.fn(),
    confirmClassification: vi.fn(),
    reviewExcel: vi.fn(),
    saveReviewedExcel: vi.fn(),
    previewReviewedIntake: vi.fn(),
    archiveAssets: vi.fn(),
    refineReviewedExcel: vi.fn(),
    analyzeClassification: vi.fn(), autoSlices: vi.fn(), recentClassifications: vi.fn(),
  },
  legacy: {
    capabilities: vi.fn(), templates: vi.fn(), runs: vi.fn(), targetConfigs: vi.fn(),
    autoIngestBatches: vi.fn().mockResolvedValue([]),
    run: vi.fn(), upload: vi.fn(), preview: vi.fn(), execute: vi.fn(),
  },
}))
vi.mock('@/api/templatePreview', () => ({ default: archive }))
vi.mock('@/api/elt', () => ({ eltApi: legacy }))
vi.mock('@/api/auth', () => ({ authApi: { getCurrentUser: vi.fn().mockResolvedValue({ success: true, data: { permissions: ['elt.read'] } }) } }))
vi.mock('@/api/xcmaxMarketProxy', () => ({ default: { llmResolveChatDefault: vi.fn().mockResolvedValue({ ok: true, provider: 'platform', model: 'default-chat' }) } }))

function region(range: string, label = 'unknown') {
  return { range, labels: [label], checked_cells: 4, parent_heading: label, dependency_status: '待确认', needs_confirmation: true,
    header_cells: [], merged_ranges: [], possible_shared_context: [], evidence: [] }
}
const parts = () => [region('A1:D4', 'process'), region('A5:D8', 'material'), region('A9:D12', 'inspection')]
const classification = (regions = parts()) => ({ name: '生产单.xlsx', classification_id: 'production', version: 'v1', status: 'classified', confirmed: false,
  model_status: 'not_called', sheets: [{ sheet: '生产单', labels: ['production'], checked_cells: 12, evidence: [], regions }] })
const layout = (value: string) => [{ sheet: '生产单', widths: [20], rows: [{ height: 20, cells: [{ cell: 'A1', value, formula: false,
  rowspan: 1, colspan: 1, bold: true, italic: false, font_size: 11, font_color: '', fill: '', align: 'left' }] }], truncated: false }]
function review(id: string) {
  const candidates = [0, 1, 2].map(index => ({ id: `candidate-${index}`, label: `候选${index + 1}`, explanation: '保留未确认内容', clear: [] }))
  return { review_id: id, sha256: 'original-sha', cells: [], sheets: ['生产单'], model: 'returned', layout: layout('生产单原件'),
    selected_region: { selection_basis: 'model_group' }, proposal: { version: `${id}-v1`, parent_version: null,
      candidates, evidence: [], model: { status: 'returned' },
      result_previews: candidates.map(candidate => ({ candidate_id: candidate.id, sha256: `sha-${candidate.id}`, layout: layout(candidate.label), layout_truncated: false })) } }
}
async function setup(runId = '') {
  const EltCenterView = (await import('./EltCenterView.vue')).default
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/business-docking', component: EltCenterView }, { path: '/template-preview', component: { template: '<div>模板库</div>' } }] })
  await router.push({ path: '/business-docking', query: runId ? { run_id: runId } : {} })
  await router.isReady()
  const wrapper = mount(EltCenterView, { global: { plugins: [router] } })
  await flushPromises()
  const button = (text: string) => wrapper.findAll('button').find(item => item.text() === text)!
  const choose = async () => {
    const input = wrapper.get('input[type="file"][multiple]')
    const source = new File(['工艺、原料、检验说明'], '生产单.xlsx')
    Object.defineProperty(input.element, 'files', { configurable: true, value: [source] })
    await input.trigger('change'); await flushPromises()
    const start = wrapper.findAll('button').find(item => item.text() === '开始处理')
    if (start) { await start.trigger('click'); await flushPromises() }
    return source
  }
  const openDocument = async () => { await wrapper.get('[data-document-key]').trigger('click'); await flushPromises() }
  return { wrapper, router, button, choose, openDocument }
}
beforeEach(() => {
  vi.clearAllMocks()
  legacy.autoIngestBatches.mockResolvedValue([])
  archive.reviewedExcelIdentity.mockResolvedValue({ actor: '1:7' })
  archive.archiveClassifyExcel.mockResolvedValue(classification())
  archive.analyzeClassification.mockResolvedValue({ version: 'model-v2', model_status: 'returned', sheets: classification().sheets })
  archive.autoSlices.mockResolvedValue({ slices: [{ index: 0, basis: 'model_group', confirmed: false, sha256: 'production-slice',
    filename: '生产单.xlsx', display_name: '生产单', fragments: [{ sheet: '生产单', range: 'A1:D12' }] }] })
  archive.reviewExcel.mockImplementation(async (form: FormData) => review(`review-${form.get('classification_id')}-${form.get('auto_slice_index')}`))
  archive.refineReviewedExcel.mockImplementation(async (form: FormData) => ({ review_id: String(form.get('review_id')),
    proposal: { ...review(String(form.get('review_id'))).proposal, version: 'refined-v2', parent_version: String(form.get('parent_version')) } }))
  archive.recentClassifications.mockResolvedValue({ files: [] })
  archive.saveReviewedExcel.mockResolvedValue({ template_id: '21' })
  archive.previewReviewedIntake.mockResolvedValue({ intake: { run_id: 'intake-1', mod_id: readActiveExtensionModIdFromStorage(), candidate_sha256: 'sha', knowledge: { action: 'new', documents: 1 }, business: { id: 'intake-1', status: 'preview_ready', preview_revision: 'rev-1', target_type: 'customer_products', summary: { new: 2, update: 0, skip: 0, error: 0, executed: 0 } } } })
  legacy.capabilities.mockResolvedValue({ targets: [], transforms: [], compatibility_presets: [], inputs: {}, limits: {} })
  legacy.templates.mockResolvedValue([]); legacy.runs.mockResolvedValue([]); legacy.targetConfigs.mockResolvedValue([])
})
afterEach(() => vi.restoreAllMocks())

describe('data docking user-only intake', () => {
  it('keeps upload → document capsule → three candidates and original, without admin/classification UI', async () => {
    const { wrapper, choose, openDocument } = await setup()
    expect(wrapper.find('.elt-admin-panel').exists()).toBe(false)
    expect(wrapper.find('.elt-composer__input').exists()).toBe(true)
    expect(wrapper.text()).toContain('上传文件，挑选模板')
    const source = await choose()
    expect(archive.archiveClassifyExcel).toHaveBeenCalledTimes(1)
    expect(archive.analyzeClassification).toHaveBeenCalledTimes(1)
    expect(archive.autoSlices).toHaveBeenCalledWith('production', 'model-v2', true)
    expect(archive.confirmClassification).not.toHaveBeenCalled()
    expect(archive.reviewExcel).toHaveBeenCalledTimes(1)
    const form = archive.reviewExcel.mock.calls[0][0] as FormData
    expect(form.get('file')).toBe(source)
    expect([form.get('classification_id'), form.get('classification_version'), form.get('auto_slice_index')]).toEqual(['production', 'model-v2', '0'])
    const analysis = archive.analyzeClassification.mock.calls[0][1] as FormData
    expect(analysis.get('version')).toBe('v1')
    for (const request of [analysis, form]) for (const key of ['use_login_notice', 'model_opt_in', 'consent', 'sample_authorized', 'own_file_authorized', 'continue_authorized', 'retry_authorized']) expect(request.has(key)).toBe(false)
    expect(archive.reviewedExcelIdentity).not.toHaveBeenCalled()
    expect(wrapper.findAll('.classification-region')).toHaveLength(0)
    expect(wrapper.text()).not.toContain('管理员与档案')
    expect(wrapper.findAll('.reviewed-template__preview--a4')).toHaveLength(0)
    expect(wrapper.get('.reviewed-template__candidate-capsule').text()).toBe('生产单')
    expect(wrapper.find('[role=dialog]').exists()).toBe(false)
    await openDocument()
    expect(wrapper.get('[role=dialog]').attributes('aria-label')).toBe('生产单')
    expect(wrapper.findAll('.reviewed-template__preview--a4')).toHaveLength(4)
    expect(wrapper.get('.reviewed-document-picker__original').text()).toContain('生产单原件')
    expect(wrapper.findAll('.reviewed-template__select-candidate')).toHaveLength(3)
    expect(archive.reviewExcel).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[aria-current="step"]')?.text()).toContain('选模板')
    expect(legacy.upload).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('saves once, then continues the same selection with its prepared intake revision', async () => {
    const { wrapper, choose, openDocument, button } = await setup(); await choose()
    expect((archive.reviewExcel.mock.calls[0][0] as FormData).get('auto_slice_index')).toBe('0')
    const dispatch = vi.spyOn(window, 'dispatchEvent')
    await openDocument()
    expect(button('保存模板').attributes('disabled')).toBeDefined()
    expect(archive.previewReviewedIntake).not.toHaveBeenCalled()
    await wrapper.findAll('.reviewed-template__select-candidate')[1].trigger('click'); await flushPromises()
    expect(archive.saveReviewedExcel).not.toHaveBeenCalled()
    expect(archive.previewReviewedIntake).not.toHaveBeenCalled()
    expect(button('保存模板').attributes('disabled')).toBeUndefined()
    await button('保存模板').trigger('click'); await flushPromises()
    expect(archive.saveReviewedExcel).toHaveBeenCalledTimes(2)
    const form = archive.saveReviewedExcel.mock.calls[0][0] as FormData
    expect(['review_id', 'private_intake', 'publish_to_tenant', 'candidate_id'].map(key => form.get(key))).toEqual(['review-production-0', 'true', 'false', 'candidate-1'])
    expect([form.get('intake_run_id'), form.get('preview_revision'), form.get('template_only')]).toEqual([null, null, 'true'])
    expect(archive.previewReviewedIntake).toHaveBeenCalledTimes(1)
    const previewForm = archive.previewReviewedIntake.mock.calls[0][0] as FormData
    expect([previewForm.get('review_id'), previewForm.get('candidate_id')]).toEqual(['review-production-0', 'candidate-1'])
    const continuation = archive.saveReviewedExcel.mock.calls[1][0] as FormData
    expect(['review_id', 'proposal_version', 'candidate_id', 'selections', 'name'].map(key => continuation.get(key)))
      .toEqual(['review_id', 'proposal_version', 'candidate_id', 'selections', 'name'].map(key => form.get(key)))
    expect(['intake_run_id', 'preview_revision', 'template_only', 'private_intake', 'publish_to_tenant', 'valid_rows_only'].map(key => continuation.get(key)))
      .toEqual(['intake-1', 'rev-1', null, 'true', 'false', 'false'])
    const [saveOrder, continueOrder] = archive.saveReviewedExcel.mock.invocationCallOrder
    expect(saveOrder).toBeLessThan(archive.previewReviewedIntake.mock.invocationCallOrder[0])
    expect(archive.previewReviewedIntake.mock.invocationCallOrder[0]).toBeLessThan(continueOrder)
    expect(dispatch.mock.calls.map(([e]) => e).filter(e => e.type === 'xcagi:templates-updated')).toHaveLength(1)
    expect(wrapper.find('[role=dialog]').exists()).toBe(false)
    expect(wrapper.get('.reviewed-template__candidate-capsule--saved').attributes('aria-label')).toBe('生产单，已保存')
    wrapper.unmount()
  })

  it('accepts typed requirements in the bottom composer', async () => {
    const { wrapper, button, openDocument } = await setup()
    await wrapper.get('.elt-composer__input').setValue('保留工艺表头')
    await wrapper.get('.elt-composer__send').trigger('click')
    expect(wrapper.get('[role=alert]').text()).toContain('请先添加文件')
    expect((wrapper.get('.elt-composer__input').element as HTMLTextAreaElement).value).toBe('保留工艺表头')
    expect(archive.reviewExcel).not.toHaveBeenCalled()
    const input = wrapper.get('input[type="file"][multiple]')
    Object.defineProperty(input.element, 'files', { configurable: true, value: [new File(['工艺'], '生产单.xlsx')] })
    await input.trigger('change'); await flushPromises()
    await button('开始处理').trigger('click'); await flushPromises()
    expect(archive.reviewExcel).toHaveBeenCalledTimes(1)
    expect(archive.refineReviewedExcel).toHaveBeenCalledTimes(1)
    const form = archive.refineReviewedExcel.mock.calls[0][0] as FormData
    expect([form.get('review_id'), form.get('parent_version'), form.get('feedback')]).toEqual(['review-production-0', 'review-production-0-v1', '保留工艺表头'])
    for (const key of ['use_login_notice', 'consent', 'sample_authorized', 'own_file_authorized']) expect(form.has(key)).toBe(false)
    expect(wrapper.text()).toContain('整理要求：保留工艺表头')
    expect((wrapper.get('.elt-composer__input').element as HTMLTextAreaElement).value).toBe('')
    await openDocument()
    expect(wrapper.findAll('.reviewed-template__preview--a4')).toHaveLength(4)
    wrapper.unmount()
  })

  it('keeps archive request identity when classification fails', async () => {
    archive.archiveClassifyExcel.mockRejectedValueOnce(new Error('分类结果未知'))
    const { wrapper, choose, button } = await setup(); const source = await choose()
    expect(wrapper.get('[role=alert]').text()).toContain('分类结果未知')
    expect(wrapper.get('[role=alert]').text()).toContain('勿重新选择文件重复上传')
    expect(archive.analyzeClassification).not.toHaveBeenCalled()
    expect(archive.reviewExcel).not.toHaveBeenCalled()
    const first = archive.archiveClassifyExcel.mock.calls[0][0] as FormData
    expect(first.get('file')).toBe(source)
    expect(first.get('request_key')).toBeTruthy()
    await button('开始处理').trigger('click'); await flushPromises()
    const retry = archive.archiveClassifyExcel.mock.calls[1][0] as FormData
    expect(retry.get('request_key')).toBe(first.get('request_key'))
    expect(retry.get('file')).toBe(source)
    expect(archive.analyzeClassification).toHaveBeenCalledTimes(1)
    expect(archive.reviewExcel).toHaveBeenCalledTimes(1)
    expect(wrapper.get('[data-document-key]').text()).toBe('生产单')
    wrapper.unmount()
  })

  it('shows chatlike empty composer guidance', async () => {
    const { wrapper } = await setup()
    expect(wrapper.text()).toContain('上传文件，挑选模板')
    expect(wrapper.text()).not.toContain('历史导入任务')
    expect(wrapper.find('.elt-composer__input').exists()).toBe(true)
    expect(wrapper.find('.elt-admin-panel').exists()).toBe(false)
    expect(wrapper.find('.elt-composer__start').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('selects a candidate explicitly while the original stays read-only', async () => {
    const { wrapper, choose, openDocument } = await setup(); await choose(); await openDocument()
    const cards = wrapper.findAll('.reviewed-template__preview--a4')
    expect(cards).toHaveLength(4)
    expect(cards[0].find('.reviewed-template__select-candidate').exists()).toBe(false)
    const choices = wrapper.findAll('.reviewed-template__select-candidate')
    expect(choices.map(choice => choice.attributes('aria-pressed'))).toEqual(['false', 'false', 'false'])
    await choices[2].trigger('click'); await flushPromises()
    expect(choices.map(choice => choice.attributes('aria-pressed'))).toEqual(['false', 'false', 'true'])
    expect(cards[3].classes()).toContain('reviewed-template__preview--selected')
    expect(archive.previewReviewedIntake).not.toHaveBeenCalled()
    expect(archive.saveReviewedExcel).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
