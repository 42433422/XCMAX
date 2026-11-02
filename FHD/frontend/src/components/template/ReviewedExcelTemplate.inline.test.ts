import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { updateProductReadAccountScope } from '@/utils/productReadAccountScope'
import ReviewedExcelTemplate from './ReviewedExcelTemplate.vue'

const api = vi.hoisted(() => ({
  archiveClassifyExcel: vi.fn(), confirmClassification: vi.fn(), reviewExcel: vi.fn(),
  refineReviewedExcel: vi.fn(), previewReviewedIntake: vi.fn(), reviewedExcelIdentity: vi.fn(),
  analyzeClassification: vi.fn(), autoSlices: vi.fn(), recentClassifications: vi.fn(),
}))
vi.mock('@/api/templatePreview', () => ({ default: api }))
vi.mock('@/api/xcmaxMarketProxy', () => ({ default: { llmResolveChatDefault: vi.fn() } }))

const classified = (name = 'synthetic.xlsx') => ({
  name, status: 'classified', classification_id: name, version: 'v1', confirmed: false,
  sheets: [{ sheet: 'Sheet1', labels: ['unknown'], checked_cells: 1, evidence: [], regions: [{
    range: 'A1:B2', labels: ['unknown'], checked_cells: 1, evidence: [], parent_heading: '',
    dependency_status: '待确认', needs_confirmation: true, header_cells: [], merged_ranges: [], possible_shared_context: [],
  }] }],
})
const authorization = { status: 'authorized', operations: { classification: 'authorized', template_candidates: 'authorized' } }
const reviewed = (id = 'model-review') => ({
  review_id: id, sha256: 'synthetic-sha', cells: [], sheets: ['Sheet1'],
  layout: [{ sheet: 'Sheet1', widths: [], rows: [], truncated: false }],
  selected_region: { selection_basis: 'model_group' },
  proposal: { version: 'v1', parent_version: null, candidates: [0, 1, 2].map(i => ({
    id: `candidate-${i}`, label: `候选${i + 1}`, explanation: '合成模型建议', clear: [],
  })), result_previews: [0, 1, 2].map(i => ({ candidate_id: `candidate-${i}`, sha256: `candidate-sha-${i}`, layout: [], layout_truncated: false })), evidence: [], model: { status: 'returned', login_authorization: authorization } },
})
const modelSlice = (index = 0, sheet = 'Sheet1') => ({
  index, basis: 'model_group', confirmed: false, sha256: `slice-${index}`,
  filename: `synthetic-${index}.xlsx`, display_name: index ? '采购合同' : '报价单', fragments: [{ sheet, range: 'A1:B2' }],
})
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(finish => { resolve = finish })
  return { promise, resolve }
}
let wrapper: VueWrapper
const button = (text: string) => wrapper.findAll('button').find(el => el.text() === text)!
async function stageFile(name = 'synthetic.xlsx') {
  const source = new File(['synthetic source, unchanged'], name)
  const input = wrapper.get('input[type=file]')
  Object.defineProperty(input.element, 'files', { configurable: true, value: [source] })
  await input.trigger('change')
  return source
}
async function start() { await button('开始处理').trigger('click'); await flushPromises() }
async function openDocument(index = 0) { await wrapper.findAll('[data-document-key]')[index].trigger('click'); await flushPromises() }
function enableModelPipeline(slices = [modelSlice()]) {
  api.reviewedExcelIdentity.mockResolvedValue({ actor: '1:7', login_authorization: authorization })
  api.analyzeClassification.mockResolvedValue({ version: 'model-v2', model_status: 'returned', sheets: classified().sheets })
  api.autoSlices.mockResolvedValue({ slices })
  api.reviewExcel.mockResolvedValue(reviewed())
  api.refineReviewedExcel.mockResolvedValue({ review_id: 'model-review', proposal: { ...reviewed().proposal, version: 'refined-v2', parent_version: 'v1' } })
}
beforeEach(() => {
  vi.resetAllMocks()
  updateProductReadAccountScope({ tenantId: 1, localUserId: 'inline-A', accountKind: 'local' })
  api.archiveClassifyExcel.mockImplementation(async (form: FormData) => classified((form.get('file') as File).name))
  api.recentClassifications.mockResolvedValue({ files: [] })
  enableModelPipeline()
  wrapper = mount(ReviewedExcelTemplate, { props: { archiveOnSelect: true } })
})
afterEach(() => { wrapper.unmount(); vi.restoreAllMocks() })

describe('model-required inline ELT processing', () => {
  it('runs archive → model classification → slices → model candidates once and preserves the source', async () => {
    const pending = deferred<ReturnType<typeof classified>>()
    api.archiveClassifyExcel.mockReturnValueOnce(pending.promise)
    const confirm = vi.spyOn(window, 'confirm')
    const source = await stageFile()
    await wrapper.get('.elt-composer__input').setValue('保留原范围')
    const startButton = button('开始处理').element
    startButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    startButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(wrapper.get('[role=status]').text()).toContain('归档及分类 1/1')
    expect(api.archiveClassifyExcel).toHaveBeenCalledTimes(1)
    pending.resolve(classified()); await flushPromises()
    expect(api.analyzeClassification).toHaveBeenCalledTimes(1)
    expect(api.confirmClassification).not.toHaveBeenCalled()
    expect(api.reviewExcel).toHaveBeenCalledTimes(1)
    const form = api.reviewExcel.mock.calls[0][0] as FormData
    expect(form.get('file')).toBe(source)
    expect([form.get('auto_slice_index'), form.get('use_login_notice'), form.get('sample_authorized'), form.get('own_file_authorized')]).toEqual(['0', 'true', 'false', 'false'])
    expect(api.reviewExcel.mock.invocationCallOrder[0]).toBeGreaterThan(api.autoSlices.mock.invocationCallOrder[0])
    expect(wrapper.get('[role=status]').text()).toBe('模板已生成。')
    expect(wrapper.findAll('.reviewed-template__preview--a4')).toHaveLength(0)
    expect(wrapper.get('.reviewed-template__candidate-capsule').text()).toContain('报价单')
    expect(api.previewReviewedIntake).not.toHaveBeenCalled()
    expect(wrapper.find('[role=dialog]').exists()).toBe(false)
    expect(wrapper.findAll('input[type=checkbox]')).toHaveLength(0)
    expect(confirm).not.toHaveBeenCalled()
    await start()
    expect(api.reviewExcel).toHaveBeenCalledTimes(1)
    await wrapper.get('.reviewed-template__candidate-capsule').trigger('click')
    expect(wrapper.findAll('.reviewed-template__preview--a4')).toHaveLength(4)
    expect(api.reviewExcel).toHaveBeenCalledTimes(1)
    expect(api.previewReviewedIntake).not.toHaveBeenCalled()
  })

  it.each([
    ['notice_not_published', '条款尚未发布'],
    ['login_notice_required', '没有完整的分类与模板候选授权'],
    ['model_configuration_error', '模型连接异常：平台模型配置不可用'],
    ['model_connection_error', '模型连接异常'],
  ])('stops for %s without local fallback or changing authorization', async (status, message) => {
    api.reviewedExcelIdentity.mockResolvedValue({ actor: '1:7', login_authorization: { status } })
    await stageFile(); await start()
    expect(wrapper.get('[role=alert]').text()).toContain(message)
    expect(api.analyzeClassification).not.toHaveBeenCalled()
    expect(api.reviewExcel).not.toHaveBeenCalled()
    expect(api.confirmClassification).not.toHaveBeenCalled()
    expect(wrapper.findAll('.reviewed-template__preview--a4')).toHaveLength(0)
    expect(wrapper.text()).not.toContain('当前显示本地规则候选')
    expect(wrapper.findAll('input[type=checkbox]')).toHaveLength(0)
    enableModelPipeline(); await start()
    expect(api.archiveClassifyExcel).toHaveBeenCalledTimes(1)
    expect(api.reviewExcel).toHaveBeenCalledTimes(1)
  })

  it.each(['classification', 'template_candidates'])('rejects incomplete %s authorization', async missing => {
    api.reviewedExcelIdentity.mockResolvedValue({ actor: '1:7', login_authorization: {
      ...authorization, operations: { ...authorization.operations, [missing]: 'login_notice_required' },
    } })
    await stageFile(); await start()
    expect(api.analyzeClassification).not.toHaveBeenCalled()
    expect(api.reviewExcel).not.toHaveBeenCalled()
    expect(wrapper.get('[role=alert]').text()).toContain('没有完整')
  })

  it.each(['not_called', 'unavailable'])('rejects a server %s proposal instead of presenting success', async status => {
    const result = reviewed()
    api.reviewExcel.mockResolvedValue({ ...result, proposal: { ...result.proposal, model: { status } } })
    await stageFile(); await start()
    await openDocument()
    expect(wrapper.get('[role=alert]').text()).toContain('模型候选或原件预览不完整')
    expect(wrapper.findAll('.reviewed-template__preview--a4')).toHaveLength(0)
    expect(wrapper.find('.reviewed-template__candidate-capsule--saved').exists()).toBe(false)
  })

  it('retries a known not-sent candidate failure without rearchiving or repeating classification', async () => {
    api.reviewExcel.mockRejectedValueOnce(Object.assign(new Error('模型连接异常，未发送'), {
      data: { detail: { retryable: true, outcome_unknown: false } },
    }))
    await stageFile(); await start()
    await openDocument()
    expect(wrapper.get('[role=alert]').text()).toContain('未发送')
    await start()
    expect(api.archiveClassifyExcel).toHaveBeenCalledTimes(1)
    expect(api.analyzeClassification).toHaveBeenCalledTimes(1)
    expect(api.reviewExcel).toHaveBeenCalledTimes(2)
  })

  it.each(['nested', 'production', 'network'])('locks an unknown %s candidate outcome against repeated Start and slice clicks', async envelope => {
    const state = { retryable: false, outcome_unknown: true }
    api.reviewExcel.mockRejectedValueOnce(Object.assign(new Error('模型结果未知，请核对'), {
      data: envelope === 'nested' ? { detail: state } : envelope === 'production' ? state : null,
    }))
    await stageFile(); await start(); await start()
    await openDocument()
    const workspace = (wrapper.vm.$.setupState as Record<string, unknown>).documentWorkspace as { documents: { value: { unknown: boolean }[] }; generate: (doc: unknown) => Promise<void> }
    expect(workspace.documents.value[0].unknown).toBe(true)
    await workspace.generate(workspace.documents.value[0]); await flushPromises()
    expect(api.reviewExcel).toHaveBeenCalledTimes(1)
    expect(wrapper.get('[role=alert]').text()).toContain('未知')
  })

  it('stops visibly when identity verification fails', async () => {
    api.reviewedExcelIdentity.mockRejectedValueOnce(new Error('授权状态读取失败'))
    await stageFile(); await start()
    expect(api.reviewExcel).not.toHaveBeenCalled()
    expect(wrapper.get('[role=alert]').text()).toContain('授权状态读取失败')
  })

  it('never resends an unknown classification outcome or falls back to local candidates', async () => {
    api.analyzeClassification.mockRejectedValueOnce(new Error('模型分类响应中断'))
    await stageFile(); await start(); await start()
    expect(api.analyzeClassification).toHaveBeenCalledTimes(1)
    expect(api.autoSlices).not.toHaveBeenCalled()
    expect(api.reviewExcel).not.toHaveBeenCalled()
    expect(wrapper.get('[role=alert]').text()).toContain('请求结果可能未知')
  })

  it('generates each named model document and opens only its own candidates without another request', async () => {
    enableModelPipeline([modelSlice(0), modelSlice(1)])
    await stageFile(); await start()
    expect(api.reviewExcel).toHaveBeenCalledTimes(2)
    expect(api.reviewExcel.mock.calls.map(call => (call[0] as FormData).get('auto_slice_index'))).toEqual(['0', '1'])
    const choices = wrapper.findAll('[data-document-key]')
    expect(choices).toHaveLength(2)
    expect(choices.map(choice => choice.text())).toEqual(['报价单', '采购合同'])
    await choices[1].trigger('click'); await flushPromises()
    expect(wrapper.get('[role=dialog]').attributes('aria-label')).toBe('采购合同')
    expect(wrapper.findAll('.reviewed-template__preview--a4')).toHaveLength(4)
    expect(api.reviewExcel).toHaveBeenCalledTimes(2)
  })

  it('blocks hidden model slices and retains their visibility metadata', async () => {
    enableModelPipeline([modelSlice(0, 'Hidden')])
    const visible = classified().sheets[0]
    api.archiveClassifyExcel.mockResolvedValueOnce({ ...classified(), sheets: [{ ...visible, sheet: 'Hidden', sheet_state: 'hidden', processable: false }, visible] })
    api.analyzeClassification.mockResolvedValueOnce({ version: 'model-v2', model_status: 'returned', sheets: [{ ...visible, sheet: 'Hidden' }, visible] })
    await stageFile(); await start()
    expect(api.reviewExcel).not.toHaveBeenCalled()
    expect(wrapper.findAll('[data-document-key]')).toHaveLength(0)
    expect(wrapper.text()).toContain('未识别到可处理模板')
  })

  it('analyzes every eligible source and binds each candidate request to its own file', async () => {
    const input = wrapper.get('input[type=file]')
    Object.defineProperty(input.element, 'files', { configurable: true, value: ['first.xlsx', 'second.xlsx'].map(name => new File(['synthetic'], name)) })
    await input.trigger('change'); await start()
    expect(api.archiveClassifyExcel).toHaveBeenCalledTimes(2)
    expect(api.analyzeClassification.mock.calls.map(call => call[0])).toEqual(['first.xlsx', 'second.xlsx'])
    expect(api.reviewExcel.mock.calls.map(call => ((call[0] as FormData).get('file') as File).name)).toEqual(['first.xlsx', 'second.xlsx'])
    expect(wrapper.findAll('[data-document-key]')).toHaveLength(2)
  })

  it('drops a late model classification when the account changes', async () => {
    const pending = deferred<{ version: string; model_status: string; sheets: ReturnType<typeof classified>['sheets'] }>()
    api.analyzeClassification.mockReturnValueOnce(pending.promise)
    await stageFile(); await start()
    updateProductReadAccountScope({ tenantId: 1, localUserId: 'pipeline-B', accountKind: 'local' })
    await flushPromises()
    api.reviewedExcelIdentity.mockResolvedValue({ actor: '1:8', login_authorization: { status: 'login_notice_required' } })
    await stageFile('new-account.xlsx'); await start()
    pending.resolve({ version: 'stale', model_status: 'returned', sheets: classified().sheets }); await flushPromises()
    expect(api.autoSlices).not.toHaveBeenCalled()
    expect(api.reviewExcel).not.toHaveBeenCalled()
  })

  it('uses the signed grant for feedback and leaves explicit per-file consents false', async () => {
    const proposal = reviewed().proposal
    api.refineReviewedExcel.mockResolvedValue({ review_id: 'model-review', proposal: { ...proposal, version: 'v2', parent_version: 'v1' } })
    await stageFile(); await start()
    await wrapper.get('.elt-composer__input').setValue('保留备注')
    await button('发送').trigger('click'); await flushPromises()
    const form = api.refineReviewedExcel.mock.calls[0][0] as FormData
    expect(form.get('use_login_notice')).toBe('true')
    expect([form.get('consent'), form.get('sample_authorized'), form.get('own_file_authorized')]).toEqual(['false', 'false', 'false'])
  })

  it.each(['nested', 'production', 'network'])('retains feedback draft and prevents retry of an unknown %s refinement', async envelope => {
    const state = { retryable: false, outcome_unknown: true }
    api.refineReviewedExcel.mockRejectedValueOnce(Object.assign(new Error('模型整理结果未知'), { data: envelope === 'nested' ? { detail: state } : envelope === 'production' ? state : null }))
    await stageFile(); await start()
    await wrapper.get('.elt-composer__input').setValue('保留备注')
    await button('发送').trigger('click'); await flushPromises()
    await button('发送').trigger('click'); await flushPromises()
    expect(api.refineReviewedExcel).toHaveBeenCalledTimes(1)
    expect(wrapper.get('[role=alert]').text()).toContain('待核对')
    expect((wrapper.get('.elt-composer__input').element as HTMLTextAreaElement).value).toBe('保留备注')
  })
})
