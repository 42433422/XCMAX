import { computed, onBeforeUnmount, ref } from 'vue'
import templatePreviewApi from '@/api/templatePreview'
import { eltApi, type EltRun } from '@/api/elt'
import { readActiveExtensionModIdFromStorage } from '@/utils/xcagiStorageKeys'

export type DocumentCell = { cell: string; value: string; formula: boolean; rowspan: number; colspan: number; bold: boolean; italic: boolean; font_size: number; font_color: string; fill: string; align: string }
export type DocumentLayout = { sheet: string; widths: number[]; rows: { height: number; cells: DocumentCell[] }[]; truncated: boolean }
export type DocumentCandidate = { id: string; label: string; explanation: string; clear: { sheet: string; cell: string }[] }
export type DocumentProposal = { version: string; parent_version: string | null; candidates: DocumentCandidate[]; result_previews?: { candidate_id: string; sha256: string; layout: DocumentLayout[]; layout_truncated: boolean }[]; evidence: unknown[]; model: { status: string; login_authorization?: { status: string }; [key: string]: unknown } }
export type DocumentReview = { review_id: string; sha256: string; proposal: DocumentProposal; versions?: DocumentProposal[]; layout?: DocumentLayout[]; usage_restrictions?: string[]; [key: string]: unknown }
export type DocumentSlice = { index: number; basis: string; confirmed: boolean; sha256: string; filename: string; display_name?: string; fragments: { sheet: string; range: string }[] }
type Intake = { run_id: string; mod_id: string; candidate_sha256: string; knowledge: { action: string; documents: number }; business: EltRun }
type Receipt = { review_id: string; proposal_version: string; template_id: string; candidate_id: string }
export type ReviewedDocument = {
  key: string; classificationId: string; classificationVersion: string; slice: DocumentSlice; source: File; displayName: string
  review: DocumentReview | null; proposals: DocumentProposal[]; selectedVersion: number; candidateIndex: number
  phase: '' | 'generating' | 'refining' | 'saving'; error: string; unknown: boolean; dirty: boolean; generation: number
  requirements: string[]; receipts: Receipt[]; intake: Intake | null; intakePending: boolean; intakeError: string; intakeKey: string; intakeGeneration: number
}

export function useReviewedDocuments(options: { capture: () => () => boolean; outcomeUnknown: (error: unknown) => boolean; saved: () => void }) {
  const records = ref<Record<string, ReviewedDocument>>({})
  const scopes = new WeakMap<object, () => boolean>()
  const documents = computed(() => Object.values(records.value))
  const timers = new Map<string, ReturnType<typeof setTimeout>>()
  function proposal(doc: ReviewedDocument) { return doc.proposals[doc.selectedVersion] }
  function saved(doc: ReviewedDocument) {
    return !doc.dirty && !!doc.review && doc.receipts.some(receipt => receipt.review_id === doc.review!.review_id && receipt.proposal_version === proposal(doc)?.version)
  }
  function current(doc: ReviewedDocument, session: () => boolean, generation: number) {
    return owned(doc) && session() && doc.generation === generation
  }
  function owned(doc: ReviewedDocument) { return records.value[doc.key] === doc && scopes.get(doc)?.() === true }
  function message(error: unknown, fallback: string) { return error instanceof Error ? error.message.slice(0, 240) : fallback }
  function clearIntake(doc: ReviewedDocument) {
    doc.intakeGeneration++; const timer = timers.get(doc.key); if (timer) clearTimeout(timer); timers.delete(doc.key)
    doc.intake = null; doc.intakePending = false; doc.intakeError = ''; doc.intakeKey = ''
  }
  function reset() { timers.forEach(clearTimeout); timers.clear(); records.value = {} }
  onBeforeUnmount(reset)
  function register(classificationId: string, classificationVersion: string, slice: DocumentSlice, source: File) {
    const key = JSON.stringify([classificationId, classificationVersion, slice.index, slice.sha256])
    if (!records.value[key]) records.value[key] = { key, classificationId, classificationVersion, slice, source,
      displayName: slice.display_name?.trim() || slice.filename.replace(/\.(xlsx|xls)$/i, ''),
      review: null, proposals: [], selectedVersion: 0, candidateIndex: -1, phase: '', error: '', unknown: false, dirty: false, generation: 0,
      requirements: [], receipts: [], intake: null, intakePending: false, intakeError: '', intakeKey: '', intakeGeneration: 0 }
    const doc = records.value[key]
    if (!scopes.has(doc)) scopes.set(doc, options.capture())
    return doc
  }
  function prune(classificationId: string, classificationVersion: string, slices: DocumentSlice[]) {
    const keys = new Set(slices.map(slice => JSON.stringify([classificationId, classificationVersion, slice.index, slice.sha256])))
    for (const doc of documents.value) if (doc.classificationId === classificationId && !keys.has(doc.key)) { clearIntake(doc); delete records.value[doc.key] }
  }
  function validate(result: DocumentReview) {
    const p = result.proposal
    if (!result.review_id || p?.model.status !== 'returned' || p.candidates.length !== 3 || p.result_previews?.length !== 3
      || new Set(p.candidates.map(candidate => candidate.id)).size !== 3 || new Set(p.result_previews.map(preview => preview.candidate_id)).size !== 3
      || p.candidates.some(candidate => !p.result_previews!.some(preview => preview.candidate_id === candidate.id)) || !result.layout?.length) throw new Error('模型候选或原件预览不完整，请核对处理记录。')
  }
  async function generate(doc: ReviewedDocument) {
    if (!owned(doc) || doc.phase || doc.unknown || doc.review) return
    const session = options.capture()
    if (!session()) return
    const generation = ++doc.generation
    doc.phase = 'generating'; doc.error = ''; clearIntake(doc)
    try {
      const form = new FormData(); let source = doc.source
      if (/\.xls$/i.test(source.name)) {
        const response = await templatePreviewApi.downloadClassificationSource(doc.classificationId)
        if (!current(doc, session, generation)) return
        const blob = await response.blob(); if (!current(doc, session, generation)) return
        source = new File([blob], source.name.replace(/\.xls$/i, '.xlsx'), { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
      }
      form.append('file', source); form.append('classification_id', doc.classificationId); form.append('classification_version', doc.classificationVersion)
      form.append('auto_slice_index', String(doc.slice.index)); form.append('use_login_notice', 'true')
      form.append('model_opt_in', 'false'); form.append('sample_authorized', 'false'); form.append('own_file_authorized', 'false')
      const result = await templatePreviewApi.reviewExcel(form) as DocumentReview
      if (!current(doc, session, generation)) return
      validate(result); doc.review = result; doc.proposals = result.versions?.length ? result.versions : [result.proposal]
      doc.selectedVersion = doc.proposals.length - 1; doc.candidateIndex = -1; doc.dirty = false
    } catch (error) {
      if (current(doc, session, generation)) { doc.unknown = options.outcomeUnknown(error); doc.error = message(error, '模型连接异常，请重试。') }
    } finally { if (current(doc, session, generation)) doc.phase = '' }
  }
  function intakeSelection(doc: ReviewedDocument) {
    const p = proposal(doc), candidate = p?.candidates[doc.candidateIndex]
    return JSON.stringify([doc.review?.review_id, p?.version, candidate?.id, candidate?.clear, doc.displayName, doc.requirements, readActiveExtensionModIdFromStorage()])
  }
  function canPrepare(doc: ReviewedDocument) {
    const p = proposal(doc)
    return owned(doc) && !!doc.review && !doc.phase && !doc.unknown && !saved(doc) && !!p?.candidates[doc.candidateIndex]
      && p.model.status === 'returned' && p.result_previews?.length === 3 && doc.selectedVersion === doc.proposals.length - 1
  }
  async function prepare(doc: ReviewedDocument) {
    if (!canPrepare(doc)) return
    const session = options.capture()
    if (!session()) return
    clearIntake(doc)
    const generation = doc.intakeGeneration, selection = intakeSelection(doc), modId = readActiveExtensionModIdFromStorage()
    const valid = () => owned(doc) && session() && doc.intakeGeneration === generation && intakeSelection(doc) === selection && modId === readActiveExtensionModIdFromStorage()
    doc.intakePending = true
    const accept = (run: EltRun) => {
      if (!valid()) return
      doc.intake!.business = run
      if (run.status === 'preview_ready' && run.preview_revision) { doc.intakeKey = selection; doc.intakePending = false }
      else if (['queued', 'previewing'].includes(run.status)) timers.set(doc.key, setTimeout(() => { void poll() }, 800))
      else { doc.intakePending = false; doc.intakeError = run.error?.message || '入库预演未完成。' }
    }
    const poll = async () => {
      if (!valid() || !doc.intake) return
      try { const run = await eltApi.run(doc.intake.run_id); if (valid()) accept(run) }
      catch (error) { if (valid()) { doc.intakePending = false; doc.intakeError = message(error, '预演状态读取失败。') } }
    }
    try {
      const p = proposal(doc), candidate = p.candidates[doc.candidateIndex], form = new FormData()
      form.append('review_id', doc.review!.review_id); form.append('proposal_version', p.version); form.append('candidate_id', candidate.id)
      form.append('selections', JSON.stringify(candidate.clear)); form.append('name', doc.displayName); form.append('composer_note', doc.requirements.join('\n').slice(0, 4000))
      const result = await templatePreviewApi.previewReviewedIntake(form) as { intake: Intake }
      if (!valid()) return
      if (!result.intake?.run_id || result.intake.mod_id !== modId || result.intake.business?.id !== result.intake.run_id) throw new Error('入库范围无法核实，请重试。')
      doc.intake = result.intake; accept(result.intake.business)
    } catch (error) { if (valid()) { doc.intakePending = false; doc.intakeError = message(error, '入库预演失败。') } }
  }
  function choose(doc: ReviewedDocument, index: number) {
    if (!owned(doc) || doc.phase || doc.unknown || saved(doc) || !Number.isInteger(index) || !proposal(doc)?.candidates[index]) return
    doc.candidateIndex = index; void prepare(doc)
  }
  function canSave(doc: ReviewedDocument) {
    const run = doc.intake?.business
    return canPrepare(doc) && !doc.intakePending && !doc.intakeError && doc.intakeKey === intakeSelection(doc)
      && doc.intake?.mod_id === readActiveExtensionModIdFromStorage() && run?.status === 'preview_ready' && !!run.preview_revision
      && [run.summary.new, run.summary.update, run.summary.skip, run.summary.error].every(value => Number.isFinite(value) && value >= 0) && run.summary.error === 0
  }
  async function save(doc: ReviewedDocument) {
    if (!canSave(doc)) return
    const session = options.capture()
    if (!session()) return
    const generation = ++doc.generation, p = proposal(doc), candidate = p.candidates[doc.candidateIndex]
    const reviewId = doc.review!.review_id, selection = intakeSelection(doc)
    doc.phase = 'saving'; doc.error = ''
    try {
      const form = new FormData(); form.append('review_id', reviewId); form.append('proposal_version', p.version); form.append('candidate_id', candidate.id)
      form.append('selections', JSON.stringify(candidate.clear)); form.append('name', doc.displayName); form.append('private_intake', 'true'); form.append('publish_to_tenant', 'false')
      form.append('intake_run_id', doc.intake!.run_id); form.append('preview_revision', doc.intake!.business.preview_revision!); form.append('valid_rows_only', 'false')
      form.append('composer_note', doc.requirements.join('\n').slice(0, 4000))
      const result = await templatePreviewApi.saveReviewedExcel(form) as { template_id?: string; auto_ingest?: { success?: boolean; error?: string } }
      if (!current(doc, session, generation) || intakeSelection(doc) !== selection) return
      if (!result.template_id?.trim()) { doc.unknown = true; throw new Error('保存回执待核对，勿重复提交。') }
      doc.receipts.push({ review_id: reviewId, proposal_version: p.version, template_id: result.template_id, candidate_id: candidate.id }); doc.dirty = false
      if (result.auto_ingest?.success === false) doc.error = '模板已保存，入库状态请核对。'
      options.saved()
    } catch (error) { if (current(doc, session, generation)) { doc.unknown ||= options.outcomeUnknown(error); doc.error = message(error, '保存结果待核对，勿重复提交。') } }
    finally { if (current(doc, session, generation)) doc.phase = '' }
  }
  async function refine(doc: ReviewedDocument, feedback: string) {
    if (!owned(doc) || !doc.review || !feedback.trim() || doc.phase || doc.unknown) return false
    if (feedback.trim().length > 1000) { doc.error = '整理要求最多 1000 字，请缩短后发送。'; return false }
    const session = options.capture()
    if (!session()) return false
    const generation = ++doc.generation, p = proposal(doc), oldReviewId = doc.review.review_id, wasDirty = doc.dirty
    doc.phase = 'refining'; doc.error = ''; doc.dirty = true; clearIntake(doc)
    try {
      const form = new FormData(); form.append('review_id', oldReviewId); form.append('parent_version', p.version); form.append('feedback', feedback.trim())
      form.append('current', JSON.stringify(p.candidates[doc.candidateIndex]?.clear || [])); form.append('use_login_notice', 'true')
      form.append('consent', 'false'); form.append('sample_authorized', 'false'); form.append('own_file_authorized', 'false')
      const result = await templatePreviewApi.refineReviewedExcel(form) as { review_id?: string; proposal: DocumentProposal }
      if (!current(doc, session, generation) || doc.review?.review_id !== oldReviewId || proposal(doc)?.version !== p.version) return false
      if (!result.review_id?.trim()) throw new Error('整理回执待核对，勿重复发送。')
      const reviewId = result.review_id
      const nextReview = { ...doc.review, review_id: reviewId, proposal: result.proposal }; validate(nextReview)
      doc.review = nextReview; doc.proposals = reviewId === oldReviewId ? [...doc.proposals, result.proposal] : [result.proposal]
      doc.selectedVersion = doc.proposals.length - 1; doc.candidateIndex = -1; doc.requirements.push(feedback.trim()); return true
    } catch (error) {
      if (current(doc, session, generation)) { doc.unknown = options.outcomeUnknown(error); if (!doc.unknown) doc.dirty = wasDirty; doc.error = message(error, '模型整理未完成。') }
      return false
    } finally { if (current(doc, session, generation)) doc.phase = '' }
  }
  function resolve(text: string) {
    const normalized = text.toLocaleLowerCase(), matches = documents.value.filter(doc => normalized.includes(doc.displayName.toLocaleLowerCase()))
    if (new Set(matches.map(doc => doc.displayName.toLocaleLowerCase())).size > 1) return null
    let exact = matches
    if (exact.length > 1) { const qualified = exact.filter(doc => normalized.includes(doc.source.name.replace(/\.(xlsx|xls)$/i, '').toLocaleLowerCase())); if (qualified.length) exact = qualified }
    return exact.length === 1 ? exact[0] : !matches.length && documents.value.length === 1 ? documents.value[0] : null
  }
  return { records, documents, proposal, saved, register, prune, reset, generate, choose, prepare, canSave, save, refine, resolve }
}
