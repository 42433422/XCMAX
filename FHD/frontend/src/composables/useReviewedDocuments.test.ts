import { defineComponent, h } from 'vue'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useReviewedDocuments, type DocumentProposal, type DocumentReview, type DocumentSlice, type ReviewedDocument } from './useReviewedDocuments'

const api = vi.hoisted(() => ({ reviewExcel: vi.fn(), previewReviewedIntake: vi.fn(), saveReviewedExcel: vi.fn(), refineReviewedExcel: vi.fn(), downloadClassificationSource: vi.fn() }))
const elt = vi.hoisted(() => ({ run: vi.fn() }))
const runtime = vi.hoisted(() => ({ modId: '' }))
vi.mock('@/api/templatePreview', () => ({ default: api }))
vi.mock('@/api/elt', () => ({ eltApi: elt }))
vi.mock('@/utils/xcagiStorageKeys', () => ({ readActiveExtensionModIdFromStorage: () => runtime.modId }))

const layout = (value: string) => [{ sheet: 'Sheet1', widths: [20], rows: [{ height: 20, cells: [{ cell: 'A1', value, formula: false, rowspan: 1, colspan: 1, bold: true, italic: false, font_size: 11, font_color: '', fill: '', align: 'left' }] }], truncated: false }]
function proposal(id: string, version = `${id}-v1`): DocumentProposal {
  const candidates = [0, 1, 2].map(index => ({ id: `${id}-candidate-${index}`, label: `候选${index + 1}`, explanation: '专用合成候选', clear: index ? [{ sheet: 'Sheet1', cell: `A${index + 1}` }] : [] }))
  return { version, parent_version: null, candidates, evidence: [], model: { status: 'returned', login_authorization: { status: 'authorized' } }, result_previews: candidates.map(candidate => ({ candidate_id: candidate.id, sha256: candidate.id, layout: layout(candidate.id), layout_truncated: false })) }
}
const review = (id: string): DocumentReview => ({ review_id: id, sha256: `source-${id}`, layout: layout(`原件-${id}`), proposal: proposal(id) })
const slice = (index = 0, name = '报价单', sha = `slice-${index}`): DocumentSlice => ({ index, basis: 'model_group', confirmed: false, sha256: sha, filename: `${name}.xlsx`, display_name: name, fragments: [{ sheet: 'Sheet1', range: 'A1:D4' }] })
function readyIntake(form: FormData, revision = 'ready-revision') {
  const runId = `run-${form.get('review_id')}-${form.get('candidate_id')}`
  return { intake: { run_id: runId, mod_id: runtime.modId, candidate_sha256: 'synthetic-candidate', knowledge: { action: 'new', documents: 1 }, business: { id: runId, target_type: 'customer_products', status: 'preview_ready', preview_revision: revision, summary: { new: 1, update: 0, skip: 0, error: 0, executed: 0 } } } }
}
function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (error: unknown) => void
  const promise = new Promise<T>((finish, fail) => { resolve = finish; reject = fail })
  return { promise, resolve, reject }
}
let controller: ReturnType<typeof useReviewedDocuments>
let wrapper: VueWrapper
let scope: { live: boolean }
let captureLive: boolean
const saved = vi.fn()
function register(id: string, name = '报价单', source = `${id}.xlsx`, version = 'classification-v1', index = 0, sha = `sha-${id}`) {
  return controller.register(id, version, slice(index, name, sha), new File(['synthetic-only'], source))
}
async function generated(id: string, name = '报价单') {
  const doc = register(id, name)
  await controller.generate(doc)
  return doc
}
async function selected(doc: ReviewedDocument, index = 0) {
  controller.choose(doc, index); await flushPromises()
}
beforeEach(() => {
  vi.resetAllMocks(); runtime.modId = ''; scope = { live: true }; captureLive = true
  api.reviewExcel.mockImplementation(async (form: FormData) => review(`review-${form.get('classification_id')}`))
  api.previewReviewedIntake.mockImplementation(async (form: FormData) => readyIntake(form))
  api.saveReviewedExcel.mockResolvedValue({ template_id: 'synthetic-template' })
  api.refineReviewedExcel.mockImplementation(async (form: FormData) => ({ review_id: String(form.get('review_id')), proposal: proposal(String(form.get('review_id')), 'refined-v2') }))
  wrapper = mount(defineComponent({ setup() {
    controller = useReviewedDocuments({ capture: () => { const captured = scope, accepted = captureLive; return () => captured.live && accepted }, outcomeUnknown: error => !!(error as { outcome_unknown?: boolean } | null)?.outcome_unknown, saved })
    return () => h('div')
  } }))
})
afterEach(() => { if (wrapper.exists()) wrapper.unmount(); vi.useRealTimers() })

describe('reviewed document ownership and receipts', () => {
  it('keys records by classification, version, slice index and hash while preserving each actual reactive record', () => {
    const a = register('A'), same = register('A')
    expect(same).toBe(a)
    const different = [register('B'), register('A', '报价单', 'A.xlsx', 'classification-v2'), register('A', '报价单', 'A.xlsx', 'classification-v1', 1), register('A', '报价单', 'A.xlsx', 'classification-v1', 0, 'replacement-sha')]
    expect(new Set([a, ...different].map(doc => doc.key)).size).toBe(5)
    expect(controller.documents.value).toHaveLength(5)
    expect(a.displayName).toBe('报价单')
  })

  it('routes concurrent A/B generation and selection independently without duplicate model calls or implying a save', async () => {
    const a = register('A'), b = register('B', '采购合同'), pendingA = deferred<DocumentReview>(), pendingB = deferred<DocumentReview>()
    api.reviewExcel.mockImplementation((form: FormData) => form.get('classification_id') === 'A' ? pendingA.promise : pendingB.promise)
    const taskA = controller.generate(a), taskB = controller.generate(b)
    await controller.generate(a)
    expect(api.reviewExcel).toHaveBeenCalledTimes(2)
    expect([a.phase, b.phase]).toEqual(['generating', 'generating'])
    pendingB.resolve(review('B')); await taskB
    expect(b.review?.review_id).toBe('B'); expect(a.review).toBeNull()
    pendingA.resolve(review('A')); await taskA
    for (const [index, doc] of [a, b].entries()) {
      const form = api.reviewExcel.mock.calls[index][0] as FormData
      expect([form.get('classification_id'), form.get('classification_version'), form.get('auto_slice_index'), form.get('use_login_notice')]).toEqual([doc.classificationId, doc.classificationVersion, '0', 'true'])
      expect(form.get('file')).toBe(doc.source)
      expect(controller.proposal(doc).candidates).toHaveLength(3)
      expect(doc.review?.layout?.[0].rows[0].cells[0].value).toBe(`原件-${doc.classificationId}`)
      expect(doc.candidateIndex).toBe(-1)
      expect(controller.saved(doc)).toBe(false)
    }
    expect(api.previewReviewedIntake).not.toHaveBeenCalled()
    await selected(a, 1)
    expect(a.candidateIndex).toBe(1); expect(b.candidateIndex).toBe(-1)
    expect(controller.canSave(a)).toBe(true); expect(controller.saved(a)).toBe(false)
    expect(api.saveReviewedExcel).not.toHaveBeenCalled()
  })

  it('turns only the matching document green after a save receipt and refuses to prepare or save it again', async () => {
    const a = await generated('A'), b = await generated('B', '采购合同')
    await selected(a, 1); await selected(b, 2)
    const response = deferred<{ template_id: string }>()
    api.saveReviewedExcel.mockReturnValueOnce(response.promise)
    const task = controller.save(a)
    await controller.save(a)
    expect(controller.saved(a)).toBe(false); expect(api.saveReviewedExcel).toHaveBeenCalledTimes(1)
    const form = api.saveReviewedExcel.mock.calls[0][0] as FormData
    expect([form.get('review_id'), form.get('candidate_id'), form.get('intake_run_id'), form.get('preview_revision')]).toEqual(['review-A', 'review-A-candidate-1', a.intake!.run_id, 'ready-revision'])
    response.resolve({ template_id: 'template-A' }); await task
    expect(controller.saved(a)).toBe(true); expect(controller.saved(b)).toBe(false)
    expect(a.receipts[0]).toMatchObject({ review_id: 'review-A', proposal_version: 'review-A-v1', candidate_id: 'review-A-candidate-1', template_id: 'template-A' })
    const previews = api.previewReviewedIntake.mock.calls.length, modelCalls = api.reviewExcel.mock.calls.length, refinementCalls = api.refineReviewedExcel.mock.calls.length
    await controller.prepare(a); await controller.save(a); controller.choose(a, 2)
    expect(api.previewReviewedIntake).toHaveBeenCalledTimes(previews)
    expect(api.reviewExcel).toHaveBeenCalledTimes(modelCalls); expect(api.refineReviewedExcel).toHaveBeenCalledTimes(refinementCalls)
    expect(api.saveReviewedExcel).toHaveBeenCalledTimes(1)
    expect(a.candidateIndex).toBe(1); expect(controller.canSave(a)).toBe(false)
    expect(saved).toHaveBeenCalledTimes(1)
  })

  it('keeps a missing save receipt yellow and locked while another document can still save', async () => {
    const a = await generated('A'), b = await generated('B', '采购合同')
    await selected(a); await selected(b)
    api.saveReviewedExcel.mockResolvedValueOnce({})
    await controller.save(a); await controller.save(a)
    expect(a.unknown).toBe(true); expect(a.receipts).toEqual([]); expect(controller.saved(a)).toBe(false)
    expect(api.saveReviewedExcel).toHaveBeenCalledTimes(1)
    await controller.save(b)
    expect(controller.saved(b)).toBe(true); expect(controller.saved(a)).toBe(false)
    expect(saved).toHaveBeenCalledTimes(1)
  })

  it('keeps a saved fork under the same document key, retains its old receipt, and requires a fresh selection and receipt', async () => {
    const a = await generated('A'), b = await generated('B', '采购合同')
    await selected(a); await controller.save(a)
    const key = a.key, oldReceipt = { ...a.receipts[0] }, response = deferred<{ review_id: string; proposal: DocumentProposal }>()
    api.refineReviewedExcel.mockReturnValueOnce(response.promise)
    const task = controller.refine(a, '保留报价单标题')
    expect(controller.saved(a)).toBe(false)
    response.resolve({ review_id: 'A-child', proposal: proposal('A-child') }); expect(await task).toBe(true)
    expect(controller.records.value[key]).toBe(a); expect(controller.documents.value).toHaveLength(2)
    expect(a.review?.review_id).toBe('A-child'); expect(a.proposals).toHaveLength(1)
    expect(controller.proposal(a).candidates).toHaveLength(3); expect(a.candidateIndex).toBe(-1)
    expect(a.receipts).toEqual([oldReceipt]); expect(controller.saved(a)).toBe(false)
    expect(b.review?.review_id).toBe('review-B'); expect(b.requirements).toEqual([])
    const form = api.refineReviewedExcel.mock.calls[0][0] as FormData
    expect([form.get('review_id'), form.get('parent_version'), form.get('feedback')]).toEqual(['review-A', 'review-A-v1', '保留报价单标题'])
    expect([form.get('consent'), form.get('sample_authorized'), form.get('own_file_authorized')]).toEqual(['false', 'false', 'false'])
    await selected(a, 2); await controller.save(a)
    expect(controller.saved(a)).toBe(true); expect(a.receipts).toHaveLength(2)
    expect(a.receipts[0]).toEqual(oldReceipt); expect(a.receipts[1].review_id).toBe('A-child')
  })

  it('locks an unknown model outcome only for its originating document', async () => {
    const a = register('A'), b = register('B', '采购合同')
    api.reviewExcel.mockRejectedValueOnce(Object.assign(new Error('A模型结果未知'), { outcome_unknown: true }))
    await controller.generate(a); await controller.generate(a)
    expect(a.unknown).toBe(true); expect(a.error).toContain('结果未知')
    await controller.generate(b); await selected(b)
    expect(b.unknown).toBe(false); expect(controller.canSave(b)).toBe(true)
    expect(api.reviewExcel).toHaveBeenCalledTimes(2)
  })

  it.each(['duplicate-preview', 'missing-original'] as const)('rejects %s model output without presenting a saved or usable review', async malformed => {
    const result = review('malformed')
    if (malformed === 'duplicate-preview') result.proposal.result_previews![1].candidate_id = result.proposal.result_previews![0].candidate_id
    else result.layout = []
    api.reviewExcel.mockResolvedValueOnce(result)
    const doc = await generated('A')
    expect(doc.review).toBeNull(); expect(doc.proposals).toEqual([])
    expect(doc.error).toContain('不完整'); expect(doc.receipts).toEqual([])
    expect(controller.saved(doc)).toBe(false); expect(controller.canSave(doc)).toBe(false)
    expect(api.previewReviewedIntake).not.toHaveBeenCalled()
  })

  it.each(['reset', 'session'] as const)('does not send model, refinement, preparation or save requests for a retired %s document', async reason => {
    const doc = register('A')
    if (reason === 'reset') controller.reset(); else scope.live = false
    await controller.generate(doc); controller.choose(doc, 0); await controller.prepare(doc); await controller.save(doc); expect(await controller.refine(doc, '保留标题')).toBe(false)
    expect(api.reviewExcel).not.toHaveBeenCalled(); expect(api.previewReviewedIntake).not.toHaveBeenCalled()
    expect(api.refineReviewedExcel).not.toHaveBeenCalled(); expect(api.saveReviewedExcel).not.toHaveBeenCalled()
    expect(api.downloadClassificationSource).not.toHaveBeenCalled()
  })

  it('discards a late generation after reset even when a new document reuses the same key', async () => {
    const old = register('A'), response = deferred<DocumentReview>()
    api.reviewExcel.mockReturnValueOnce(response.promise)
    const task = controller.generate(old)
    controller.reset()
    const replacement = await generated('A')
    response.resolve(review('stale-A')); await task
    expect(controller.records.value[old.key]).toBe(replacement)
    expect(replacement.review?.review_id).toBe('review-A'); expect(old.review).toBeNull()
    expect(controller.documents.value).toEqual([replacement])
  })

  it.each(['generate', 'prepare', 'save', 'refine'] as const)('does not send a newly captured invalid %s operation even when registration is still live', async operation => {
    const doc = operation === 'generate' ? register('A') : await generated('A')
    if (operation !== 'generate') await selected(doc)
    api.reviewExcel.mockClear(); api.previewReviewedIntake.mockClear(); api.saveReviewedExcel.mockClear(); api.refineReviewedExcel.mockClear()
    captureLive = false
    if (operation === 'generate') await controller.generate(doc)
    else if (operation === 'prepare') await controller.prepare(doc)
    else if (operation === 'save') await controller.save(doc)
    else await controller.refine(doc, '保留标题')
    expect(api.reviewExcel).not.toHaveBeenCalled()
    expect(api.previewReviewedIntake).not.toHaveBeenCalled()
    expect(api.saveReviewedExcel).not.toHaveBeenCalled()
    expect(api.refineReviewedExcel).not.toHaveBeenCalled()
    expect(api.downloadClassificationSource).not.toHaveBeenCalled()
    expect(doc.phase).toBe('')
  })

  it('ignores old A preparation results after its candidate changes and keeps B intake independent', async () => {
    const a = await generated('A'), b = await generated('B', '采购合同'), response = deferred<ReturnType<typeof readyIntake>>()
    api.previewReviewedIntake.mockReturnValueOnce(response.promise)
    controller.choose(a, 0)
    const oldForm = api.previewReviewedIntake.mock.calls[0][0] as FormData
    await selected(a, 1); await selected(b, 2)
    const currentA = a.intake!.run_id, currentB = b.intake!.run_id
    response.resolve(readyIntake(oldForm, 'stale-revision')); await flushPromises()
    expect(a.intake?.run_id).toBe(currentA); expect(b.intake?.run_id).toBe(currentB)
    expect(a.intake?.business.preview_revision).toBe('ready-revision')
    expect(controller.canSave(a)).toBe(true); expect(controller.canSave(b)).toBe(true)
  })

  it.each([['reset', 'queued'], ['prune', 'previewing'], ['unmount', 'queued']] as const)('retires %s document polling after a %s preview without polling its stale run', async (retire, status) => {
    vi.useFakeTimers()
    api.previewReviewedIntake.mockImplementation(async (form: FormData) => {
      const result = readyIntake(form)
      result.intake.business.status = status; result.intake.business.preview_revision = ''
      return result
    })
    const doc = await generated('A'); await selected(doc)
    const staleRun = doc.intake!.run_id, baseBusiness = doc.intake!.business
    expect(doc.intakePending).toBe(true); expect(vi.getTimerCount()).toBe(1)
    let survivor: ReviewedDocument | undefined
    if (retire === 'prune') { survivor = await generated('B', '采购合同'); await selected(survivor) }
    elt.run.mockImplementation(async (id: string) => ({ ...baseBusiness, id, status: 'preview_ready', preview_revision: 'polled-ready' }))
    if (retire === 'reset') controller.reset()
    else if (retire === 'prune') controller.prune(doc.classificationId, 'classification-v2', [])
    else wrapper.unmount()
    expect(vi.getTimerCount()).toBe(survivor ? 1 : 0)
    await vi.advanceTimersByTimeAsync(5000); await flushPromises()
    expect(elt.run.mock.calls.map(call => call[0])).not.toContain(staleRun)
    if (survivor) {
      expect(elt.run).toHaveBeenCalledExactlyOnceWith(survivor.intake!.run_id)
      expect(controller.canSave(survivor)).toBe(true)
    } else expect(elt.run).not.toHaveBeenCalled()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('does not schedule polling when an old queued preparation resolves after reset', async () => {
    vi.useFakeTimers()
    const doc = await generated('A'), response = deferred<ReturnType<typeof readyIntake>>()
    api.previewReviewedIntake.mockReturnValueOnce(response.promise)
    controller.choose(doc, 0); await flushPromises()
    const stale = readyIntake(api.previewReviewedIntake.mock.calls[0][0] as FormData)
    stale.intake.business.status = 'previewing'; stale.intake.business.preview_revision = ''
    expect(doc.intakePending).toBe(true); expect(vi.getTimerCount()).toBe(0)
    controller.reset()
    const replacement = register('A')
    response.resolve(stale); await flushPromises()
    expect(controller.records.value[doc.key]).toBe(replacement)
    expect(replacement.intake).toBeNull(); expect(replacement.intakePending).toBe(false)
    expect(vi.getTimerCount()).toBe(0)
    await vi.advanceTimersByTimeAsync(5000)
    expect(elt.run).not.toHaveBeenCalled(); expect(controller.canSave(replacement)).toBe(false)
  })

  it('drops a late save receipt after reset instead of marking a replacement or another document saved', async () => {
    const a = await generated('A'); await selected(a)
    const response = deferred<{ template_id: string }>()
    api.saveReviewedExcel.mockReturnValueOnce(response.promise)
    const task = controller.save(a)
    controller.reset()
    const replacement = await generated('A'), b = await generated('B', '采购合同')
    response.resolve({ template_id: 'stale-template' }); await task
    expect(a.receipts).toEqual([]); expect(replacement.receipts).toEqual([])
    expect(controller.saved(replacement)).toBe(false); expect(controller.saved(b)).toBe(false)
    expect(saved).not.toHaveBeenCalled()
  })

  it('rejects overlong feedback locally without truncation or an unknown lock and sends all 1000 accepted characters', async () => {
    const a = await generated('A'), beforeGeneration = a.generation
    expect(await controller.refine(a, '甲'.repeat(1001))).toBe(false)
    expect(api.refineReviewedExcel).not.toHaveBeenCalled(); expect(a.unknown).toBe(false)
    expect(a.dirty).toBe(false); expect(a.phase).toBe(''); expect(a.generation).toBe(beforeGeneration)
    const accepted = '乙'.repeat(1000)
    expect(await controller.refine(a, accepted)).toBe(true)
    expect((api.refineReviewedExcel.mock.calls[0][0] as FormData).get('feedback')).toBe(accepted)
    expect(a.requirements).toEqual([accepted]); expect(a.unknown).toBe(false)
  })

  it('treats two unequal document-title mentions as ambiguous instead of choosing the longest match', () => {
    const a = register('A', '报价单'), b = register('B', '采购合同')
    expect(controller.resolve('请同时整理报价单与采购合同')).toBeNull()
    expect(controller.resolve('只整理报价单，保留抬头')).toBe(a)
    expect(controller.resolve('采购合同保留签字栏')).toBe(b)
    expect(controller.resolve('保留标题')).toBeNull()
  })

  it('requires source qualification for duplicate document titles and never guesses when that is still ambiguous', () => {
    const a = register('A', '报价单', '甲客户.xlsx'), b = register('B', '报价单', '乙客户.xlsx')
    expect(controller.resolve('整理报价单')).toBeNull()
    expect(controller.resolve('整理甲客户的报价单')).toBe(a)
    expect(controller.resolve('整理乙客户的报价单')).toBe(b)
    expect(controller.resolve('甲客户和乙客户的报价单')).toBeNull()
    register('C', '报价单', '甲客户.xlsx')
    expect(controller.resolve('整理甲客户的报价单')).toBeNull()
  })
})
