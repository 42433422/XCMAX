import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { updateProductReadAccountScope } from '@/utils/productReadAccountScope'
import ReviewedExcelTemplate from './ReviewedExcelTemplate.vue'
import type { useReviewedDocuments } from '@/composables/useReviewedDocuments'

const api = vi.hoisted(() => ({ archiveClassifyExcel: vi.fn(), reviewedExcelIdentity: vi.fn(), analyzeClassification: vi.fn(), autoSlices: vi.fn(), templateFamilies: vi.fn(), reviewExcel: vi.fn(), recentClassifications: vi.fn(), saveReviewedExcel: vi.fn(), previewReviewedIntake: vi.fn() }))
vi.mock('@/api/templatePreview', () => ({ default: api }))
vi.mock('@/api/xcmaxMarketProxy', () => ({ default: { llmResolveChatDefault: vi.fn() } }))
const sheet = { sheet: 'Sheet1', sheet_state: 'visible', processable: true, labels: ['template'], checked_cells: 1, evidence: [], regions: [{ range: 'A1:B2', labels: ['template'], checked_cells: 1, evidence: [], parent_heading: '', dependency_status: 'ready', needs_confirmation: false, header_cells: [], merged_ranges: [], possible_shared_context: [] }] }
const modelResult = () => ({ version: 'model-v2', model_status: 'returned', sheets: [sheet] })
const checkpoint = (phase = 'failed') => ({ phase, version: 'v1', completed: 0, total: 2, max_calls: 1, calls_in_round: 1, message: '本轮预算已用完' })
const slice = (index = 0) => ({ index, basis: 'model_group', confirmed: false, sha256: `slice-${index}`, filename: `单据${index}.xlsx`, display_name: `单据${index}`, fragments: [{ sheet: 'Sheet1', range: 'A1:B2' }] })
function review(id = 'synthetic-review') {
  const candidates = [0, 1, 2].map(index => ({ id: `${id}-${index}`, label: `候选${index}`, explanation: '', clear: [] }))
  const layout = [{ sheet: 'Sheet1', widths: [], rows: [], truncated: false }]
  return { review_id: id, sha256: 'source', layout, proposal: { version: 'p1', parent_version: null, candidates, evidence: [], model: { status: 'returned' }, result_previews: candidates.map(candidate => ({ candidate_id: candidate.id, sha256: candidate.id, layout, layout_truncated: false })) } }
}
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done }); return { promise, resolve } }
let wrapper: VueWrapper, sourceNames: string[]
const startButton = () => wrapper.get('.elt-composer__start')
const stopButton = () => wrapper.get('.elt-composer__retry')
const state = () => wrapper.vm.$.setupState as Record<string, unknown>
async function start() { await startButton().trigger('click'); await flushPromises() }
async function stage(names = ['a.xlsx']) {
  sourceNames = names
  Object.defineProperty(wrapper.get('input[type=file]').element, 'files', { configurable: true, value: names.map(name => new File(['synthetic'], name)) })
  await wrapper.get('input[type=file]').trigger('change')
}
beforeEach(() => {
  vi.resetAllMocks(); sourceNames = []; updateProductReadAccountScope({ tenantId: 1, localUserId: 'recovery-A', accountKind: 'local' })
  api.archiveClassifyExcel.mockImplementation(async (form: FormData) => { const name = (form.get('file') as File).name; return { name, sha256: `sha-${name}`, status: 'classified', classification_id: name, version: 'v1', sheets: [sheet] } })
  api.reviewedExcelIdentity.mockResolvedValue({ actor: '1:7' })
  api.analyzeClassification.mockImplementation(async () => modelResult())
  api.templateFamilies.mockResolvedValue({ families: [{ members: [0], reason: '独立' }, { members: [1], reason: '独立' }] })
  api.autoSlices.mockResolvedValue({ slices: [slice()] }); api.reviewExcel.mockResolvedValue(review())
  api.recentClassifications.mockImplementation(async () => ({ files: sourceNames.map(name => ({ classification_id: name, sha256: `sha-${name}`, checkpoint: checkpoint(), latest: { version: 'v1' } })) }))
  wrapper = mount(ReviewedExcelTemplate, { props: { archiveOnSelect: true } })
})
afterEach(() => { wrapper.unmount(); vi.restoreAllMocks() })

describe('archive round recovery and stopping', () => {
  it('closes on save immediately and keeps late receipts in their own capsule', async () => {
    const saving = deferred<{ template_id: string }>()
    api.saveReviewedExcel.mockReturnValueOnce(saving.promise)
    api.previewReviewedIntake.mockReturnValue(new Promise(() => {}))
    api.autoSlices.mockResolvedValue({ slices: [slice(0), slice(1)] })
    await stage(); await start()
    await wrapper.findAll('.reviewed-template__candidate-capsule')[0].trigger('click')
    await wrapper.findAll('.reviewed-template__select-candidate')[0].trigger('click')
    await wrapper.findAll('button').find(button => button.text() === '保存模板')!.trigger('click')
    await flushPromises()
    expect(wrapper.find('.reviewed-document-picker').exists()).toBe(false)
    expect(wrapper.findAll('.reviewed-template__candidate-capsule')[0].text()).toContain('保存中')
    await wrapper.findAll('.reviewed-template__candidate-capsule')[1].trigger('click')
    saving.resolve({ template_id: 'saved-first' }); await flushPromises()
    expect(wrapper.find('.reviewed-document-picker').exists()).toBe(true)
    expect(wrapper.findAll('.reviewed-template__candidate-capsule')[0].text()).toContain('已保存·后台核对中')
    expect(wrapper.findAll('.reviewed-template__candidate-capsule')[1].text()).not.toContain('已保存')
  })

  it('continues an exhausted failure on the visible action once and ignores duplicate clicks', async () => {
    api.analyzeClassification.mockRejectedValueOnce(new Error('本轮调用失败'))
    await stage(); await start()
    expect(startButton().text()).toBe('继续处理')
    expect(startButton().attributes('aria-label')).toBe('继续处理（a.xlsx）')
    expect(api.analyzeClassification).toHaveBeenCalledTimes(1)
    await (state().classify as () => Promise<void>)(); await flushPromises()
    expect(api.analyzeClassification).toHaveBeenCalledTimes(1)
    const pending = deferred<ReturnType<typeof modelResult>>()
    api.analyzeClassification.mockReturnValueOnce(pending.promise)
    startButton().element.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    startButton().element.dispatchEvent(new MouseEvent('click', { bubbles: true })); await flushPromises()
    expect(api.analyzeClassification).toHaveBeenCalledTimes(2)
    const form = api.analyzeClassification.mock.calls[1][1] as FormData
    expect([form.get('retry_authorized'), form.get('continue_authorized'), form.get('version')]).toEqual([null, null, 'v1'])
    pending.resolve(modelResult()); await flushPromises()
    expect(wrapper.findAll('[data-document-key]')).toHaveLength(1)
    expect(startButton().text()).toBe('开始处理'); expect(wrapper.find('.elt-composer__retry').exists()).toBe(false)
    await start(); expect(api.analyzeClassification).toHaveBeenCalledTimes(2)
    expect(wrapper.emitted('stage')?.some(args => args[0] === 'template')).toBe(true)
  })

  it('does not automatically retry again after a continued round fails', async () => {
    api.analyzeClassification.mockRejectedValue(new Error('本轮调用失败'))
    await stage(); await start(); await start()
    expect(api.analyzeClassification).toHaveBeenCalledTimes(2)
    expect(startButton().text()).toBe('继续处理')
    expect(wrapper.findAll('[data-document-key]')).toHaveLength(0)
    await flushPromises(); expect(api.analyzeClassification).toHaveBeenCalledTimes(2)
    expect((api.analyzeClassification.mock.calls[0][1] as FormData).get('continue_authorized')).toBeNull()
    expect((api.analyzeClassification.mock.calls[1][1] as FormData).get('continue_authorized')).toBeNull()
  })

  it('binds a continued round to one failed source/version instead of sharing it with the next source', async () => {
    api.analyzeClassification.mockRejectedValueOnce(new Error('a失败')).mockRejectedValueOnce(new Error('b失败'))
    await stage(['a.xlsx', 'b.xlsx']); await start()
    expect(startButton().attributes('aria-label')).toBe('继续处理（a.xlsx）')
    await start()
    expect(api.analyzeClassification.mock.calls.map(call => call[0])).toEqual(['a.xlsx', 'b.xlsx', 'a.xlsx'])
    expect(startButton().attributes('aria-label')).toBe('继续处理（b.xlsx）')
    expect((api.analyzeClassification.mock.calls[1][1] as FormData).get('continue_authorized')).toBeNull()
    expect((api.analyzeClassification.mock.calls[2][1] as FormData).get('continue_authorized')).toBeNull()
  })

  it('does not reuse a retired round action for a newly staged file', async () => {
    api.analyzeClassification.mockRejectedValueOnce(new Error('a失败'))
    await stage(); await start(); const oldKey = startButton().attributes('data-round-approval')!
    await stage(['b.xlsx'])
    ;(state().startProcessing as (key: string) => void)(oldKey); await flushPromises()
    expect(api.analyzeClassification.mock.calls.at(-1)![0]).toBe('b.xlsx')
    expect((api.analyzeClassification.mock.calls.at(-1)![1] as FormData).get('continue_authorized')).toBeNull()
  })

  it('continues saved batches automatically after a round budget pause', async () => {
    api.analyzeClassification.mockResolvedValueOnce({ ...modelResult(), phase: 'paused', checkpoint: { ...checkpoint('paused'), completed: 1 }, version: 'v1', model_status: 'not_called' })
    await stage(); await start()
    expect(api.analyzeClassification).toHaveBeenCalledTimes(2)
    expect((api.analyzeClassification.mock.calls[1][1] as FormData).get('version')).toBe('v1')
    expect(api.reviewExcel).toHaveBeenCalled()
  })

  it('continues bounded format repairs even before a batch completes', async () => {
    for (const rounds of [1, 2]) api.analyzeClassification.mockResolvedValueOnce({ ...modelResult(), phase: 'paused', checkpoint: { ...checkpoint('paused'), repair_rounds: rounds }, version: 'v1', model_status: 'not_called' })
    await stage(); await start()
    expect(api.analyzeClassification).toHaveBeenCalledTimes(3)
    expect(api.reviewExcel).toHaveBeenCalled()
  })

  it('stops automatic continuation if paused batches make no progress', async () => {
    api.analyzeClassification.mockResolvedValue({ ...modelResult(), phase: 'paused', checkpoint: checkpoint('paused'), version: 'v1', model_status: 'not_called' })
    await stage(); await start()
    expect(api.analyzeClassification).toHaveBeenCalledTimes(2)
    expect(startButton().text()).toBe('继续处理')
    expect(api.reviewExcel).not.toHaveBeenCalled()
  })

  it('stops after an in-flight classification without starting the next file or model slices, and resumes only on Start', async () => {
    const pending = deferred<ReturnType<typeof modelResult>>()
    api.analyzeClassification.mockReturnValueOnce(pending.promise)
    await stage(['a.xlsx', 'b.xlsx']); await start(); await stopButton().trigger('click')
    expect(stopButton().attributes('disabled')).toBeDefined()
    pending.resolve(modelResult()); await flushPromises()
    expect(api.analyzeClassification.mock.calls.map(call => call[0])).toEqual(['a.xlsx'])
    expect(api.autoSlices).not.toHaveBeenCalled(); expect(api.reviewExcel).not.toHaveBeenCalled()
    expect(wrapper.get('[role=status]').text()).toBe('已停止后续处理。')
    expect(wrapper.find('.elt-composer__retry').exists()).toBe(false)
    await start()
    expect(api.analyzeClassification.mock.calls.map(call => call[0])).toEqual(['a.xlsx', 'b.xlsx'])
    expect(api.archiveClassifyExcel).toHaveBeenCalledTimes(2)
    expect(api.reviewExcel).toHaveBeenCalledTimes(2)
  })

  it('keeps a real in-flight candidate result but stops the remaining document and file queue without executing a draft', async () => {
    const pending = deferred<ReturnType<typeof review>>()
    api.autoSlices.mockResolvedValue({ slices: [slice(0), slice(1)] }); api.reviewExcel.mockReturnValueOnce(pending.promise)
    await stage(['a.xlsx', 'b.xlsx']); await wrapper.get('.elt-composer__input').setValue('单据0保留备注'); await start()
    expect(api.reviewExcel).toHaveBeenCalledTimes(1)
    await stopButton().trigger('click'); pending.resolve(review('finished-inflight')); await flushPromises()
    const controller = state().documentWorkspace as ReturnType<typeof useReviewedDocuments>
    expect(controller.documents.value[0].review?.review_id).toBe('finished-inflight')
    expect(controller.documents.value[0].unknown).toBe(false)
    expect(api.reviewExcel).toHaveBeenCalledTimes(1); expect(api.analyzeClassification).toHaveBeenCalledTimes(1)
    expect((wrapper.get('.elt-composer__input').element as HTMLTextAreaElement).value).toBe('单据0保留备注')
    await wrapper.get('.elt-composer__input').setValue(''); await start()
    expect(api.reviewExcel).toHaveBeenCalledTimes(4)
    expect(api.analyzeClassification).toHaveBeenCalledTimes(2)
  })
})
