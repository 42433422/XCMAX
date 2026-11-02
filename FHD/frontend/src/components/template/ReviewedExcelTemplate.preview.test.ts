import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { updateProductReadAccountScope } from '@/utils/productReadAccountScope'
import ReviewedExcelTemplate from './ReviewedExcelTemplate.vue'
import type { useReviewedDocuments } from '@/composables/useReviewedDocuments'

const api = vi.hoisted(() => ({ archiveClassifyExcel: vi.fn(), reviewedExcelIdentity: vi.fn(), analyzeClassification: vi.fn(), autoSlices: vi.fn(), reviewExcel: vi.fn(), refineReviewedExcel: vi.fn(), previewReviewedIntake: vi.fn(), saveReviewedExcel: vi.fn() }))
vi.mock('@/api/templatePreview', () => ({ default: api }))
vi.mock('@/api/xcmaxMarketProxy', () => ({ default: { llmResolveChatDefault: vi.fn() } }))
const titles: Record<string, string[]> = { 'class-first.xlsx': ['报价单', '采购合同'], 'class-second.xlsx': ['送货单'] }
const sheet = { sheet: 'Sheet1', sheet_state: 'visible', processable: true, labels: ['template'], checked_cells: 2, evidence: [], regions: [{ range: 'A1:B2', labels: ['template'], checked_cells: 2, evidence: [], parent_heading: '', dependency_status: 'ready', needs_confirmation: false, header_cells: [], merged_ranges: [], possible_shared_context: [] }] }
const layout = (value: string) => [{ sheet: 'Sheet1', widths: [20], rows: [{ height: 20, cells: [{ cell: 'A1', value, formula: false, rowspan: 1, colspan: 1, bold: false, italic: false, font_size: 11, font_color: '', fill: '', align: 'left' }] }], truncated: false }]
function reviewed(name: string, id = `review-${name}`, version = 'v1') {
  const candidates = [0, 1, 2].map(i => ({ id: `${name}-${i}`, label: `方案${i + 1}`, explanation: `${name}候选${i + 1}`, clear: [{ sheet: 'Sheet1', cell: 'A2' }] }))
  return { review_id: id, sha256: `sha-${name}`, layout: layout(`${name}原件`), cells: [], sheets: ['Sheet1'], proposal: { version, parent_version: null, candidates, evidence: [], model: { status: 'returned', login_authorization: { status: 'authorized' } }, result_previews: candidates.map(candidate => ({ candidate_id: candidate.id, sha256: candidate.id, layout: layout(`${name}${candidate.label}`), layout_truncated: false })) } }
}
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done }); return { promise, resolve } }
let wrapper: VueWrapper, host: HTMLElement
const button = (label: string) => wrapper.findAll('button').find(el => el.text() === label)!
const capsules = () => wrapper.findAll('[data-document-key]')
const capsule = (name: string) => capsules().find(el => el.attributes('aria-label')?.split('，')[0] === name)!
const state = () => wrapper.vm.$.setupState as Record<string, unknown>
async function stage(names = ['first.xlsx', 'second.xlsx']) {
  Object.defineProperty(wrapper.get('input[type=file]').element, 'files', { configurable: true, value: names.map(name => new File(['synthetic workbook'], name)) })
  await wrapper.get('input[type=file]').trigger('change')
}
async function start() { await button('开始处理').trigger('click'); await flushPromises() }
beforeEach(() => {
  vi.resetAllMocks(); updateProductReadAccountScope({ tenantId: 1, localUserId: 'multi-A', accountKind: 'local' })
  api.archiveClassifyExcel.mockImplementation(async (form: FormData) => ({ name: (form.get('file') as File).name, status: 'classified', classification_id: `class-${(form.get('file') as File).name}`, version: 'archive-v1', sheets: [sheet] }))
  api.reviewedExcelIdentity.mockResolvedValue({ actor: '1:7', login_authorization: { status: 'authorized', operations: { classification: 'authorized', template_candidates: 'authorized' } } })
  api.analyzeClassification.mockResolvedValue({ version: 'model-v2', model_status: 'returned', sheets: [sheet] })
  api.autoSlices.mockImplementation(async (id: string) => ({ slices: titles[id].map((title, index) => ({ index, basis: 'model_group', confirmed: false, sha256: `${id}-${index}`, filename: `${title}.xlsx`, display_name: title, fragments: [{ sheet: 'Sheet1', range: 'A1:B2' }] })) }))
  api.reviewExcel.mockImplementation(async (form: FormData) => reviewed(titles[String(form.get('classification_id'))][Number(form.get('auto_slice_index'))]))
  api.previewReviewedIntake.mockImplementation(async (form: FormData) => ({ intake: { run_id: `run-${form.get('review_id')}`, mod_id: '', candidate_sha256: 'candidate', knowledge: { action: 'new', documents: 1 }, business: { id: `run-${form.get('review_id')}`, target_type: 'knowledge', status: 'preview_ready', preview_revision: 'revision', summary: { new: 1, update: 0, skip: 0, error: 0 } } } }))
  api.saveReviewedExcel.mockImplementation(async (form: FormData) => ({ template_id: `saved-${form.get('review_id')}` }))
  api.refineReviewedExcel.mockResolvedValue({ review_id: 'child-报价单', proposal: reviewed('报价单新版', 'child-报价单', 'v2').proposal })
  host = document.createElement('div'); document.body.append(host); wrapper = mount(ReviewedExcelTemplate, { attachTo: host, props: { archiveOnSelect: true } })
})
afterEach(() => { wrapper.unmount(); host.remove(); vi.restoreAllMocks() })

describe('AI document capsule workspace', () => {
  it('processes every file and true model slice, each yellow capsule opens only its own three candidates and read-only original', async () => {
    await stage(); await start()
    expect(api.analyzeClassification).toHaveBeenCalledTimes(2); expect(api.reviewExcel).toHaveBeenCalledTimes(3)
    expect(capsules().map(el => el.text())).toEqual(['报价单', '采购合同', '送货单'])
    expect(wrapper.findAll('.reviewed-template__candidate-capsule--saved')).toHaveLength(0)
    expect(wrapper.find('[role=dialog]').exists()).toBe(false)
    await capsule('报价单').trigger('click'); await flushPromises()
    const panel = wrapper.get('.reviewed-document-picker')
    expect(panel.findAll('.reviewed-template__preview--a4')).toHaveLength(4)
    expect(panel.findAll('.reviewed-template__select-candidate')).toHaveLength(3)
    expect(panel.get('.reviewed-document-picker__original').text()).toContain('报价单原件')
    expect(panel.get('.reviewed-document-picker__original').find('.reviewed-template__select-candidate').exists()).toBe(false)
    expect(panel.text()).not.toContain('采购合同原件'); expect(api.reviewExcel).toHaveBeenCalledTimes(3)
    await button('关闭').trigger('click'); await capsule('送货单').trigger('click'); await flushPromises()
    expect(wrapper.get('.reviewed-document-picker').text()).toContain('送货单原件')
    expect(wrapper.get('.reviewed-document-picker').text()).not.toContain('报价单原件')
  })
  it('keeps selection yellow, saves only that document green, and refreshes the same capsule yellow on saved-review fork', async () => {
    await stage(); await start(); const key = capsule('报价单').attributes('data-document-key')
    await capsule('报价单').trigger('click'); await flushPromises()
    await wrapper.findAll('.reviewed-template__select-candidate')[1].trigger('click'); await flushPromises()
    expect(capsule('报价单').classes()).not.toContain('reviewed-template__candidate-capsule--saved')
    await button('保存模板').trigger('click'); await flushPromises()
    expect(capsule('报价单').classes()).toContain('reviewed-template__candidate-capsule--saved')
    expect(capsule('采购合同').classes()).not.toContain('reviewed-template__candidate-capsule--saved')
    expect(wrapper.find('[role=dialog]').exists()).toBe(false)
    await wrapper.get('.elt-composer__input').setValue('报价单保留签名')
    await button('发送').trigger('click'); await flushPromises()
    expect((api.refineReviewedExcel.mock.calls[0][0] as FormData).get('review_id')).toBe('review-报价单')
    expect(capsule('报价单').attributes('data-document-key')).toBe(key)
    expect(capsule('报价单').classes()).not.toContain('reviewed-template__candidate-capsule--saved')
    const doc = (state().documentWorkspace as ReturnType<typeof useReviewedDocuments>).records.value[key!]
    expect(doc.review.review_id).toBe('child-报价单'); expect(doc.receipts).toHaveLength(1)
    await capsule('报价单').trigger('click'); await flushPromises()
    expect(wrapper.get('.reviewed-document-picker').text()).toContain('报价单新版方案1')
    expect(wrapper.findAll('.reviewed-template__select-candidate').every(el => el.attributes('aria-pressed') === 'false')).toBe(true)
  })
  it('preserves initial requirements until a real target exists and briefly clarifies multiple named targets without a request', async () => {
    await stage(); await wrapper.get('.elt-composer__input').setValue('报价单保留签名'); await start()
    expect(api.refineReviewedExcel).toHaveBeenCalledTimes(1)
    expect((wrapper.get('.elt-composer__input').element as HTMLTextAreaElement).value).toBe('')
    await wrapper.get('.elt-composer__input').setValue('报价单和采购合同都保留签名')
    await button('发送').trigger('click'); await flushPromises()
    expect(api.refineReviewedExcel).toHaveBeenCalledTimes(1)
    expect(wrapper.get('[role=alert]').text()).toBe('请明确要整理哪份模板。')
    expect((wrapper.get('.elt-composer__input').element as HTMLTextAreaElement).value).toContain('报价单和采购合同')
    expect(wrapper.find('select').exists()).toBe(false)
  })
  it('continues valid files in a mixed batch and never claims a failed candidate generation completed successfully', async () => {
    api.archiveClassifyExcel.mockImplementation(async (form: FormData) => { const name = (form.get('file') as File).name; if (name === 'bad.xlsx') throw Object.assign(new Error('文件无法解析'), { data: { outcome_unknown: false } }); return { name, status: 'classified', classification_id: `class-${name}`, version: 'archive-v1', sheets: [sheet] } })
    api.reviewExcel.mockRejectedValueOnce(Object.assign(new Error('模型连接异常'), { data: { outcome_unknown: false, retryable: true } }))
    await stage(['first.xlsx', 'bad.xlsx']); await start()
    expect(api.analyzeClassification).toHaveBeenCalledTimes(1); expect(capsules()).toHaveLength(2)
    expect(wrapper.get('[role=status]').text()).toContain('部分模板未完成')
    await capsule('报价单').trigger('click'); await flushPromises()
    expect(wrapper.get('.reviewed-document-picker [role=alert]').text()).toContain('模型连接异常')
    expect(wrapper.findAll('.reviewed-template__preview--a4')).toHaveLength(0)
  })
  it('drops retired-account refinement replies before touching the new account warning or draft', async () => {
    const pending = deferred<unknown>(); api.refineReviewedExcel.mockReturnValueOnce(pending.promise)
    await stage(); await start(); await wrapper.get('.elt-composer__input').setValue('报价单保留签名')
    await button('发送').trigger('click'); await flushPromises()
    updateProductReadAccountScope({ tenantId: 1, localUserId: 'multi-B', accountKind: 'local' }); await flushPromises()
    const warning = state().error; await wrapper.get('.elt-composer__input').setValue('新账号草稿')
    pending.resolve({ review_id: 'retired', proposal: reviewed('旧账号').proposal }); await flushPromises()
    expect(state().error).toBe(warning); expect(capsules()).toHaveLength(0)
    expect((wrapper.get('.elt-composer__input').element as HTMLTextAreaElement).value).toBe('新账号草稿')
  })
})
