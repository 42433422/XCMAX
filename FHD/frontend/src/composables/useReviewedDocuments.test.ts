import { defineComponent, h } from 'vue'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useReviewedDocuments, type DocumentProposal, type DocumentReview, type DocumentSlice, type ReviewedDocument } from './useReviewedDocuments'

const autoApproval = vi.hoisted(() => vi.fn())
vi.mock('@/composables/useAutomaticDockingApproval', () => ({ approveDockingIfAutomatic: autoApproval }))
const api = vi.hoisted(() => ({ reviewExcel: vi.fn(), reviewedCandidateResult: vi.fn(), previewReviewedIntake: vi.fn(), reviewedIntakeStatus: vi.fn(), retryReviewedIntake: vi.fn(), saveReviewedExcel: vi.fn(), refineReviewedExcel: vi.fn(), downloadClassificationSource: vi.fn() }))
const elt = vi.hoisted(() => ({ run: vi.fn(), autoIngestProgress: vi.fn() }))
const runtime = vi.hoisted(() => ({ modId: '' }))
vi.mock('@/api/templatePreview', () => ({ default: api }))
vi.mock('@/api/elt', () => ({ eltApi: elt }))
vi.mock('@/utils/xcagiStorageKeys', () => ({ readActiveExtensionModIdFromStorage: () => runtime.modId }))

const layout = (value: string) => [{ sheet: 'Sheet1', widths: [20], rows: [{ height: 20, cells: [{ cell: 'A1', value, formula: false, rowspan: 1, colspan: 1, bold: true, italic: false, font_size: 11, font_color: '', fill: '', align: 'left' }] }], truncated: false }]
function proposal(id: string, version = `${id}-v1`): DocumentProposal {
  const candidates = [0, 1, 2].map(index => ({ id: `${id}-candidate-${index}`, label: `候选${index + 1}`, explanation: '专用合成候选', clear: index ? [{ sheet: 'Sheet1', cell: `A${index + 1}` }] : [] }))
  return { version, parent_version: null, candidates, evidence: [], model: { status: 'returned' }, result_previews: candidates.map(candidate => ({ candidate_id: candidate.id, sha256: candidate.id, layout: layout(candidate.id), layout_truncated: false })) }
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
  controller.choose(doc, index); void controller.prepare(doc); await flushPromises()
}
beforeEach(() => {
  vi.resetAllMocks(); autoApproval.mockResolvedValue({ attempted: false, accepted: false }); elt.autoIngestProgress.mockResolvedValue({ status: 'awaiting_approval' }); runtime.modId = ''; scope = { live: true }; captureLive = true
  api.reviewExcel.mockImplementation(async (form: FormData) => review(`review-${form.get('classification_id')}`))
  api.previewReviewedIntake.mockImplementation(async (form: FormData) => readyIntake(form))
  api.saveReviewedExcel.mockResolvedValue({ template_id: 'synthetic-template', auto_ingest: { success: true, status: 'awaiting_approval', batch_id: 'batch-test' } })
  api.refineReviewedExcel.mockImplementation(async (form: FormData) => ({ review_id: String(form.get('review_id')), proposal: proposal(String(form.get('review_id')), 'refined-v2') }))
  wrapper = mount(defineComponent({ setup() {
    controller = useReviewedDocuments({ capture: () => { const captured = scope, accepted = captureLive; return () => captured.live && accepted }, outcomeUnknown: error => !!(error as { outcome_unknown?: boolean } | null)?.outcome_unknown, saved })
    return () => h('div')
  } }))
})
afterEach(() => { if (wrapper.exists()) wrapper.unmount(); vi.useRealTimers() })

describe('reviewed document ownership and receipts', () => {
  it('recovers a candidate completed after timeout without resending to the model', async () => {
    api.reviewExcel.mockRejectedValue({ outcome_unknown: true })
    const doc = await generated('late')
    expect(doc.unknown).toBe(true)
    expect(api.reviewExcel).toHaveBeenCalledWith(expect.any(FormData), { quiet: true })
    api.reviewedCandidateResult.mockResolvedValue({ status: 'pending' })
    await controller.recoverCandidate(doc)
    expect(doc.unknown).toBe(true)
    api.reviewedCandidateResult.mockResolvedValue({ status: 'complete', review: review('late-result') })
    await controller.recoverCandidate(doc)
    expect(doc.review?.review_id).toBe('late-result')
    expect(doc.unknown).toBe(false)
    expect(api.reviewExcel).toHaveBeenCalledTimes(1)
    expect(api.reviewedCandidateResult).toHaveBeenCalledWith('late', 'classification-v1', 0)
  })

  it('automatically checks a timed-out candidate without repeating the model request', async () => {
    vi.useFakeTimers()
    try {
      api.reviewExcel.mockRejectedValue({ outcome_unknown: true })
      api.reviewedCandidateResult.mockResolvedValueOnce({ status: 'pending' }).mockResolvedValueOnce({ status: 'complete', review: review('finished') })
      const doc = await generated('slow')
      await vi.advanceTimersByTimeAsync(15_000)
      expect(doc.unknown).toBe(true)
      await vi.advanceTimersByTimeAsync(15_000)
      expect(doc.review?.review_id).toBe('finished')
      expect(api.reviewExcel).toHaveBeenCalledTimes(1)
      expect(api.reviewedCandidateResult).toHaveBeenCalledTimes(2)
    } finally { vi.useRealTimers() }
  })

  it('offers explicit continuation when completed batches can be reused', async () => {
    api.reviewExcel.mockRejectedValueOnce({ outcome_unknown: true })
    const doc = await generated('partial')
    api.reviewedCandidateResult.mockResolvedValue({ status: 'retryable' })
    await controller.recoverCandidate(doc)
    expect(doc.unknown).toBe(false)
    expect(doc.error).toContain('剩余批次')
    expect(api.reviewExcel).toHaveBeenCalledTimes(1)
    await controller.generate(doc)
    expect(api.reviewExcel).toHaveBeenCalledTimes(2)
    expect(doc.review).toBeTruthy()
  })
  it('restores a saved candidate without starting a duplicate preview', async () => {
    api.reviewedIntakeStatus.mockResolvedValue({ status: 'outcome_unknown' })
    api.reviewExcel.mockResolvedValue({ ...review('saved'), saved_receipt: {
      review_id: 'saved', proposal_version: 'saved-v1', candidate_id: 'saved-candidate-1', template_id: 'db:1',
    } })
    const doc = await generated('saved')
    await flushPromises()
    expect(controller.saved(doc)).toBe(true)
    expect(doc.candidateIndex).toBe(1)
    expect(doc.intakeError).toContain('结果待核对')
    expect(api.previewReviewedIntake).not.toHaveBeenCalled()
    api.retryReviewedIntake.mockResolvedValue({ success: true })
    await controller.retryIntake(doc); await flushPromises()
    expect(api.retryReviewedIntake).toHaveBeenCalledWith('saved')
    expect(api.previewReviewedIntake).toHaveBeenCalledTimes(1)
  })

  it('restores the completed intake from the saved review', async () => {
    const form = new FormData(); form.set('review_id', 'saved'); form.set('candidate_id', 'saved-candidate-1')
    api.reviewExcel.mockResolvedValue({ ...review('saved'), saved_receipt: {
      review_id: 'saved', proposal_version: 'saved-v1', candidate_id: 'saved-candidate-1', template_id: 'db:1',
    } })
    api.reviewedIntakeStatus.mockResolvedValue({ status: 'created', ...readyIntake(form) })
    const doc = await generated('saved'); await flushPromises()
    expect(doc.intake?.business.status).toBe('preview_ready')
    expect(doc.intakePending).toBe(false)
    expect(doc.intakeError).toBe('')
    expect(api.previewReviewedIntake).not.toHaveBeenCalled()
  })

  it('keeps a degraded model preview visibly awaiting review', async () => {
    const doc = await generated('degraded')
    controller.choose(doc, 0)
    api.previewReviewedIntake.mockImplementation(async (form: FormData) => {
      const result = readyIntake(form)
      return { intake: { ...result.intake, detection: { degraded: true }, knowledge: { ...result.intake.knowledge, degraded: true } } }
    })
    await controller.save(doc); await flushPromises()
    expect(controller.saved(doc)).toBe(true)
    expect(doc.intakePending).toBe(false)
    expect(doc.intakeError).toContain('业务、知识模型分析未完成')
    expect(doc.intake?.business.status).toBe('preview_ready')
  })

  it('checks the existing preview after an unknown response instead of resending', async () => {
    const doc = await generated('recover')
    controller.choose(doc, 0)
    const form = new FormData(); form.set('review_id', 'review-recover'); form.set('candidate_id', 'review-recover-candidate-0')
    api.previewReviewedIntake.mockRejectedValue({ outcome_unknown: true })
    api.reviewedIntakeStatus.mockResolvedValue({ status: 'created', ...readyIntake(form) })
    await controller.save(doc); await flushPromises()
    expect(api.previewReviewedIntake).toHaveBeenCalledTimes(1)
    expect(api.reviewedIntakeStatus).toHaveBeenCalledWith('review-recover')
    expect(doc.intake?.business.status).toBe('preview_ready')
  })

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
      expect([form.get('classification_id'), form.get('classification_version'), form.get('auto_slice_index')]).toEqual([doc.classificationId, doc.classificationVersion, '0'])
      for (const key of ['use_login_notice', 'model_opt_in', 'sample_authorized', 'own_file_authorized']) expect(form.has(key)).toBe(false)
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
    expect([form.get('review_id'), form.get('candidate_id'), form.get('intake_run_id'), form.get('preview_revision')]).toEqual(['review-A', 'review-A-candidate-1', null, null])
    response.resolve({ template_id: 'template-A' }); await task
    expect(controller.saved(a)).toBe(true); expect(controller.saved(b)).toBe(false)
    expect(a.receipts[0]).toMatchObject({ review_id: 'review-A', proposal_version: 'review-A-v1', candidate_id: 'review-A-candidate-1', template_id: 'template-A' })
    const previews = api.previewReviewedIntake.mock.calls.length, modelCalls = api.reviewExcel.mock.calls.length, refinementCalls = api.refineReviewedExcel.mock.calls.length
    await controller.prepare(a); await controller.save(a); controller.choose(a, 2)
    expect(api.previewReviewedIntake).toHaveBeenCalledTimes(previews)
    expect(api.reviewExcel).toHaveBeenCalledTimes(modelCalls); expect(api.refineReviewedExcel).toHaveBeenCalledTimes(refinementCalls)
    expect(api.saveReviewedExcel).toHaveBeenCalledTimes(2)
    const calls = api.saveReviewedExcel.mock.calls.map(call => call[0] as FormData)
    expect(calls.filter(form => form.get('template_only') === 'true')).toHaveLength(1)
    expect(calls[1].get('review_id')).toBe(calls[0].get('review_id'))
    expect(calls[1].get('intake_run_id')).toBeTruthy()
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
    for (const key of ['use_login_notice', 'consent', 'sample_authorized', 'own_file_authorized']) expect(form.has(key)).toBe(false)
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
    controller.choose(a, 0); void controller.prepare(a)
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
    controller.choose(doc, 0); void controller.prepare(doc); await flushPromises()
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


it('saves the chosen template before starting background intake preparation', async () => {
  const doc = await generated('save-first')
  const pending = deferred<ReturnType<typeof readyIntake>>()
  api.previewReviewedIntake.mockReturnValue(pending.promise)
  controller.choose(doc, 0)
  expect(api.previewReviewedIntake).not.toHaveBeenCalled()
  expect(controller.canSave(doc)).toBe(true)
  await controller.save(doc)
  expect(controller.saved(doc)).toBe(true)
  expect(doc.phase).toBe('')
  expect(doc.intakePending).toBe(true)
  const form = api.saveReviewedExcel.mock.calls[0][0] as FormData
  expect(form.get('template_only')).toBe('true')
  expect(form.get('intake_run_id')).toBeNull()
})

function savedReview(id: string): DocumentReview {
  const result = review(id)
  result.saved_receipt = { review_id: id, proposal_version: result.proposal.version, candidate_id: result.proposal.candidates[0].id, template_id: 'already-saved' }
  return result
}

it('converts an archived DOCX before generation and does not send the original binary', async () => {
  const source = new Blob(['converted workbook'], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
  api.downloadClassificationSource.mockResolvedValue({ blob: async () => source })
  const doc = register('word', '报价单', 'source.docx')
  await controller.generate(doc)
  expect(api.downloadClassificationSource).toHaveBeenCalledExactlyOnceWith('word')
  const file = (api.reviewExcel.mock.calls[0][0] as FormData).get('file') as File
  expect(file.name).toBe('source.xlsx')
  expect(file.size).toBe(source.size)
  expect(doc.review).not.toBeNull()
})

it('discards an archive conversion that resolves after its document is removed', async () => {
  const response = deferred<{ blob: () => Promise<Blob> }>()
  api.downloadClassificationSource.mockReturnValue(response.promise)
  const doc = register('old', '报价单', 'source.xls')
  const task = controller.generate(doc)
  controller.prune('old', 'new-version', [])
  const blob = vi.fn().mockResolvedValue(new Blob(['old']))
  response.resolve({ blob }); await task
  expect(blob).not.toHaveBeenCalled()
  expect(api.reviewExcel).not.toHaveBeenCalled()
})

it('keeps unknown candidate results blocked and retries only the status lookup after a network error', async () => {
  vi.useFakeTimers()
  api.reviewExcel.mockRejectedValue({ outcome_unknown: true })
  const doc = await generated('unknown')
  api.reviewedCandidateResult.mockResolvedValueOnce({ status: 'unknown' }).mockRejectedValueOnce(new Error('status offline'))
  await controller.recoverCandidate(doc)
  expect(doc.error).toContain('尚未确认')
  await controller.recoverCandidate(doc)
  expect(doc.error).toBe('status offline')
  expect(doc.phase).toBe(''); expect(doc.unknown).toBe(true)
  api.reviewedCandidateResult.mockResolvedValue({ status: 'complete', review: review('recovered') })
  await vi.advanceTimersByTimeAsync(15_000)
  expect(doc.review?.review_id).toBe('recovered')
  expect(api.reviewExcel).toHaveBeenCalledTimes(1)
})

it('ignores a recovered candidate arriving after session invalidation', async () => {
  api.reviewExcel.mockRejectedValue({ outcome_unknown: true })
  const doc = await generated('revoked'), response = deferred<{ status: string; review: DocumentReview }>()
  api.reviewedCandidateResult.mockReturnValue(response.promise)
  const task = controller.recoverCandidate(doc)
  scope.live = false
  response.resolve({ status: 'complete', review: review('other-session') }); await task
  expect(doc.review).toBeNull()
  expect(controller.canSave(doc)).toBe(false)
})

it('restores a saved receipt through running and queued intake states without resaving', async () => {
  vi.useFakeTimers()
  api.reviewExcel.mockResolvedValue(savedReview('saved-running'))
  const ready = readyIntake(new FormData()).intake
  api.reviewedIntakeStatus.mockResolvedValueOnce({ status: 'running' })
    .mockResolvedValueOnce({ status: 'created', intake: { ...ready, business: { ...ready.business, status: 'queued' } } })
    .mockResolvedValueOnce({ status: 'created', intake: ready })
  const doc = await generated('saved-running'); await flushPromises()
  expect(controller.saved(doc)).toBe(true); expect(doc.intakePending).toBe(true)
  await vi.advanceTimersByTimeAsync(2000)
  expect(doc.intakePending).toBe(true)
  await vi.advanceTimersByTimeAsync(2000)
  expect(doc.intakePending).toBe(false); expect(doc.intakeError).toBe('')
  expect(doc.intake?.business.status).toBe('preview_ready')
  expect(api.saveReviewedExcel).toHaveBeenCalledTimes(1)
  expect((api.saveReviewedExcel.mock.calls[0][0] as FormData).get('intake_run_id')).toBe(doc.intake!.run_id)
})

it('does not repeat an unknown saved intake', async () => {
  const status = 'outcome_unknown'
  api.reviewExcel.mockResolvedValue(savedReview('saved-state'))
  api.reviewedIntakeStatus.mockResolvedValue({ status })
  const doc = await generated('saved-state'); await flushPromises()
  expect(controller.saved(doc)).toBe(true)
  expect(doc.intakePending).toBe(false)
  expect(doc.intakeUnknown).toBe(status === 'outcome_unknown')
  expect(doc.intakeError).toContain('待核对')
  expect(api.previewReviewedIntake).not.toHaveBeenCalled()
})

it('reports failed restoration and explicit retry errors without losing the saved receipt', async () => {
  api.reviewExcel.mockResolvedValue(savedReview('saved-error'))
  api.reviewedIntakeStatus.mockRejectedValue(new Error('lookup unavailable'))
  const doc = await generated('saved-error'); await flushPromises()
  expect(doc.intakeError).toBe('lookup unavailable'); expect(doc.intakePending).toBe(false)
  doc.intakeUnknown = true
  api.retryReviewedIntake.mockRejectedValue(new Error('retry denied'))
  await controller.retryIntake(doc)
  expect(doc.intakeError).toBe('retry denied'); expect(doc.intakeUnknown).toBe(true)
  expect(controller.saved(doc)).toBe(true)
  expect(api.previewReviewedIntake).not.toHaveBeenCalled()
})

it('explicitly resumes unknown intake and only then requests a new preview', async () => {
  api.reviewExcel.mockResolvedValue(savedReview('resume-intake'))
  api.reviewedIntakeStatus.mockResolvedValue({ status: 'outcome_unknown' })
  const doc = await generated('resume-intake'); await flushPromises()
  expect(doc.intakeUnknown).toBe(true)
  api.retryReviewedIntake.mockResolvedValue({ status: 'retryable' })
  await controller.retryIntake(doc); await flushPromises()
  expect(api.retryReviewedIntake).toHaveBeenCalledExactlyOnceWith('resume-intake')
  expect(api.previewReviewedIntake).toHaveBeenCalledTimes(1)
  expect(doc.intakeUnknown).toBe(false); expect(doc.intakePending).toBe(false)
})

it('does not prepare a revoked document after a late intake retry succeeds', async () => {
  api.reviewExcel.mockResolvedValue(savedReview('retry-late'))
  api.reviewedIntakeStatus.mockResolvedValue({ status: 'outcome_unknown' })
  const doc = await generated('retry-late'); await flushPromises()
  const response = deferred<unknown>(); api.retryReviewedIntake.mockReturnValue(response.promise)
  const task = controller.retryIntake(doc)
  controller.reset(); response.resolve({}); await task
  expect(api.previewReviewedIntake).not.toHaveBeenCalled()
})

it('stops polling a failed business preview and exposes its failure without saving', async () => {
  vi.useFakeTimers()
  api.previewReviewedIntake.mockImplementation(async (form: FormData) => {
    const result = readyIntake(form); result.intake.business.status = 'queued'; return result
  })
  elt.run.mockResolvedValue({ status: 'failed', error: { message: 'invalid source' } })
  const doc = await generated('failed-preview'); await selected(doc)
  await vi.advanceTimersByTimeAsync(800)
  expect(doc.intakePending).toBe(false); expect(doc.intakeError).toBe('invalid source')
  expect(vi.getTimerCount()).toBe(0); expect(api.saveReviewedExcel).not.toHaveBeenCalled()
})

it('reports a polling transport error and permits a deliberate fresh preparation', async () => {
  vi.useFakeTimers()
  api.previewReviewedIntake.mockImplementation(async (form: FormData) => {
    const result = readyIntake(form); result.intake.business.status = 'previewing'; return result
  })
  elt.run.mockRejectedValue(new Error('poll offline'))
  const doc = await generated('poll-error'); await selected(doc)
  await vi.advanceTimersByTimeAsync(800)
  expect(doc.intakeError).toBe('poll offline'); expect(doc.intakePending).toBe(false)
  expect(vi.getTimerCount()).toBe(0)
})

it('keeps refinement errors visible and never appends an invalid or missing receipt', async () => {
  const doc = await generated('bad-refine'), previous = doc.proposals.slice()
  api.refineReviewedExcel.mockResolvedValueOnce({ proposal: proposal('bad-refine', 'v2') })
  expect(await controller.refine(doc, '保留客户名称')).toBe(false)
  expect(doc.error).toContain('整理回执待核对'); expect(doc.proposals).toEqual(previous)
  api.refineReviewedExcel.mockRejectedValueOnce({ outcome_unknown: true })
  expect(await controller.refine(doc, '保留价格')).toBe(false)
  expect(doc.unknown).toBe(true); expect(doc.dirty).toBe(true)
  expect(doc.error).toBe('模型整理未完成。'); expect(doc.phase).toBe('')
})

it('keeps only slices still present in a refreshed classification', () => {
  const keep = register('prune', '报价单', 'a.xlsx', 'v1', 0), removed = register('prune', '报价单2', 'a.xlsx', 'v1', 1)
  controller.prune('prune', 'v1', [keep.slice])
  expect(controller.documents.value).toEqual([keep]); expect(controller.records.value[removed.key]).toBeUndefined()
})

it('does not restart recovery for a completed candidate or an expired capture', async () => {
  const ready = await generated('ready')
  await controller.recoverCandidate(ready)
  expect(api.reviewedCandidateResult).not.toHaveBeenCalled()
  api.reviewExcel.mockRejectedValue({ outcome_unknown: true })
  const unknown = await generated('expired')
  captureLive = false
  await controller.recoverCandidate(unknown)
  expect(api.reviewedCandidateResult).not.toHaveBeenCalled()
})

it('restores saved candidate intake after recovery and notifies the owner once', async () => {
  wrapper.unmount()
  const recovered = vi.fn()
  wrapper = mount(defineComponent({ setup() {
    controller = useReviewedDocuments({ capture: () => () => true, outcomeUnknown: () => true, saved, recovered })
    return () => h('div')
  } }))
  api.reviewExcel.mockRejectedValue({ outcome_unknown: true })
  const doc = await generated('saved-recovery')
  api.reviewedCandidateResult.mockResolvedValue({ status: 'complete', review: savedReview('saved-recovery') })
  api.reviewedIntakeStatus.mockResolvedValue({ status: 'not_started' })
  await controller.recoverCandidate(doc); await flushPromises()
  expect(recovered).toHaveBeenCalledExactlyOnceWith(doc)
  expect(api.reviewedIntakeStatus).toHaveBeenCalledExactlyOnceWith('saved-recovery')
  expect(controller.saved(doc)).toBe(true)
})

it('discards an archived workbook blob that finishes after scope revocation', async () => {
  const body = deferred<Blob>()
  api.downloadClassificationSource.mockResolvedValue({ blob: () => body.promise })
  const doc = register('blob-stale', '报价单', 'a.xls'), task = controller.generate(doc)
  await flushPromises(); scope.live = false
  body.resolve(new Blob(['private'])); await task
  expect(api.reviewExcel).not.toHaveBeenCalled()
})

it('leaves a saved template intact when its restoration fails business validation', async () => {
  api.reviewExcel.mockResolvedValue(savedReview('failed-business'))
  const intake = readyIntake(new FormData()).intake
  api.reviewedIntakeStatus.mockResolvedValue({ status: 'created', intake: { ...intake, business: { ...intake.business, status: 'failed', error: { message: 'source rejected' } } } })
  const doc = await generated('failed-business'); await flushPromises()
  expect(doc.intakeError).toBe('source rejected'); expect(doc.intakePending).toBe(false)
  expect(controller.saved(doc)).toBe(true)
})

it('ignores restoration returning after the saved document is removed', async () => {
  api.reviewExcel.mockResolvedValue(savedReview('stale-restore'))
  const pending = deferred<unknown>(); api.reviewedIntakeStatus.mockReturnValue(pending.promise)
  const doc = await generated('stale-restore'); await flushPromises()
  controller.reset(); pending.resolve({ status: 'created', intake: readyIntake(new FormData()).intake }); await flushPromises()
  expect(doc.intake).toBeNull(); expect(controller.documents.value).toEqual([])
})

it('does not retry intake before saving, or after a new capture has expired', async () => {
  const unsaved = await generated('unsaved')
  await controller.retryIntake(unsaved)
  api.reviewExcel.mockResolvedValue(savedReview('expired-retry'))
  api.reviewedIntakeStatus.mockResolvedValue({ status: 'outcome_unknown' })
  const doc = await generated('expired-retry'); await flushPromises()
  captureLive = false
  await controller.retryIntake(doc)
  expect(api.retryReviewedIntake).not.toHaveBeenCalled()
})

it('does not restore a saved intake when the post-generation capture has expired', async () => {
  const result = deferred<DocumentReview>(); api.reviewExcel.mockReturnValue(result.promise)
  const doc = register('expired-restore'), task = controller.generate(doc)
  captureLive = false; result.resolve(savedReview('expired-restore')); await task
  expect(controller.saved(doc)).toBe(true)
  expect(api.reviewedIntakeStatus).not.toHaveBeenCalled()
})

it('rejects an intake preview whose run and business record have different owners or identities', async () => {
  const doc = await generated('wrong-intake')
  api.previewReviewedIntake.mockImplementation(async (form: FormData) => {
    const result = readyIntake(form); result.intake.business.id = 'different-run'; return result
  })
  await selected(doc)
  expect(doc.intakeError).toBe('入库范围无法核实，请核对。')
  expect(doc.intake).toBeNull(); expect(doc.intakePending).toBe(false)
})

it('does not start preparation when a freshly captured scope has expired', async () => {
  const doc = await generated('prepare-expired')
  controller.choose(doc, 0); captureLive = false
  await controller.prepare(doc)
  expect(api.previewReviewedIntake).not.toHaveBeenCalled()
})

it('recovers saved-template intake after an uncertain preparation without resubmitting it', async () => {
  const doc = await generated('save-unknown'); controller.choose(doc, 0)
  api.previewReviewedIntake.mockRejectedValue({ outcome_unknown: true })
  api.reviewedIntakeStatus.mockResolvedValue({ status: 'outcome_unknown' })
  await controller.save(doc); await flushPromises()
  expect(controller.saved(doc)).toBe(true)
  expect(doc.intakeUnknown).toBe(true)
  expect(api.previewReviewedIntake).toHaveBeenCalledTimes(1)
  expect(api.reviewedIntakeStatus).toHaveBeenCalledTimes(1)
})

it('shows saved-but-intake-failed separately instead of dropping the template receipt', async () => {
  const doc = await generated('save-warning'); controller.choose(doc, 0)
  api.saveReviewedExcel.mockResolvedValue({ template_id: 'stored', auto_ingest: { success: false, error: 'storage unavailable' } })
  await controller.save(doc)
  expect(controller.saved(doc)).toBe(true)
  expect(doc.error).toBe('模板已保存，入库状态请核对。')
})

it('ignores refinement after the user switches to another proposal version', async () => {
  const doc = await generated('refine-stale'), response = deferred<{ review_id: string; proposal: DocumentProposal }>()
  api.refineReviewedExcel.mockReturnValue(response.promise)
  const task = controller.refine(doc, '保留客户')
  doc.proposals.push(proposal('replacement', 'other-version')); doc.selectedVersion = 1
  response.resolve({ review_id: 'refine-stale', proposal: proposal('refine-stale', 'late-version') })
  expect(await task).toBe(false)
  expect(doc.proposals.map(item => item.version)).not.toContain('late-version')
  expect(doc.requirements).toEqual([])
})

it('automatically submits a saved template with its exact ready preview, once', async () => {
  const doc = await generated('auto-write'); controller.choose(doc, 0)
  api.saveReviewedExcel.mockResolvedValueOnce({ template_id: 'synthetic-template' })
    .mockResolvedValue({ template_id: 'synthetic-template', auto_ingest: { success: true, status: 'awaiting_approval', batch_id: 'batch-1' } })
  await controller.save(doc); await flushPromises()
  expect(api.saveReviewedExcel).toHaveBeenCalledTimes(2)
  const form = api.saveReviewedExcel.mock.calls[1][0] as FormData
  expect(form.get('template_only')).toBeNull()
  expect(form.get('intake_run_id')).toBe(doc.intake!.run_id)
  expect(form.get('preview_revision')).toBe('ready-revision')
  expect(doc.ingestStatus).toBe('awaiting_approval')
  await controller.prepare(doc); await flushPromises()
  expect(api.saveReviewedExcel).toHaveBeenCalledTimes(2)
})

it('does not repeat an automatic write after an unknown response', async () => {
  const doc = await generated('unknown-write'); controller.choose(doc, 0)
  api.saveReviewedExcel.mockResolvedValueOnce({ template_id: 'synthetic-template' }).mockRejectedValue(new Error('network lost'))
  await controller.save(doc); await flushPromises()
  expect(doc.ingestStatus).toBe('outcome_unknown')
  await controller.prepare(doc); await flushPromises()
  expect(api.saveReviewedExcel).toHaveBeenCalledTimes(2)
})

it('automatically submits a new saved revision and ignores the old progress response', async () => {
  vi.useFakeTimers()
  const doc = await generated('revision-write'); controller.choose(doc, 0)
  await controller.save(doc); await flushPromises()
  const oldProgress = deferred<{ status: string }>()
  elt.autoIngestProgress.mockReturnValueOnce(oldProgress.promise)
  await vi.advanceTimersByTimeAsync(2000)
  await controller.refine(doc, '新要求')
  expect(doc.ingestStatus).toBe('')
  controller.choose(doc, 0)
  await controller.save(doc); await flushPromises()
  expect(api.saveReviewedExcel).toHaveBeenCalledTimes(4)
  expect(doc.ingestStatus).toBe('awaiting_approval')
  oldProgress.resolve({ status: 'failed' }); await flushPromises()
  expect(doc.ingestStatus).toBe('awaiting_approval')
  expect((api.saveReviewedExcel.mock.calls[3][0] as FormData).get('proposal_version')).toBe('refined-v2')
})

it('continues a saved template whose authoritative preview state is not_started', async () => {
  api.reviewExcel.mockImplementation(async () => savedReview('interrupted-save'))
  api.reviewedIntakeStatus.mockResolvedValue({ status: 'not_started' })
  const doc = await generated('interrupted-save'); await flushPromises()
  expect(api.previewReviewedIntake).toHaveBeenCalledOnce()
  expect(api.saveReviewedExcel).toHaveBeenCalledOnce()
  expect(doc.ingestStatus).toBe('awaiting_approval')
})

it('restores a completed batch without submitting or previewing it again', async () => {
  vi.useFakeTimers()
  const result = savedReview('completed-save')
  api.reviewExcel.mockResolvedValue(result)
  const form = new FormData(); form.append('review_id', result.review_id); form.append('candidate_id', result.proposal.candidates[0].id)
  const plan = readyIntake(form).intake
  plan.business.status = 'completed'
  api.reviewedIntakeStatus.mockResolvedValue({ status: 'created', intake: plan,
    auto_ingest: { success: true, batch_id: 'existing-batch', status: 'awaiting_approval' } })
  elt.autoIngestProgress.mockResolvedValue({ batch_id: 'existing-batch', status: 'applied' })
  const doc = await generated('completed-save'); await flushPromises(); await vi.advanceTimersByTimeAsync(2000)
  expect(doc.ingestStatus).toBe('applied')
  expect(api.previewReviewedIntake).not.toHaveBeenCalled()
  expect(api.saveReviewedExcel).not.toHaveBeenCalled()
})

it('uses the existing automatic approval preference and reads actual batch progress', async () => {
  autoApproval.mockResolvedValue({ attempted: true, accepted: true })
  elt.autoIngestProgress.mockResolvedValue({ batch_id: 'batch-test', status: 'applied' })
  const doc = await generated('automatic-approval'); controller.choose(doc, 0)
  await controller.save(doc); await flushPromises()
  expect(autoApproval).toHaveBeenCalledOnce()
  expect(elt.autoIngestProgress).toHaveBeenCalledWith('batch-test')
  expect(doc.ingestStatus).toBe('applied')
})
