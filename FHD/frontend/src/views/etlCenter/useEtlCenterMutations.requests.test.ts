import { flushPromises } from '@vue/test-utils'
import { computed, effectScope, type EffectScope } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { EtlRun, EtlRunRow } from '@/api/etl'
import { createEtlCenterState } from './etlCenterState'
import { createEtlCenterDerived } from './useEtlCenterDerived'
import { createEtlCenterRuns } from './useEtlCenterRuns'
import { createEtlCenterDraftActions } from './useEtlCenterDraftActions'

const api = vi.hoisted(() => ({ run: vi.fn(), rows: vi.fn(), runs: vi.fn(), execute: vi.fn(),
  retry: vi.fn(), replay: vi.fn(), rollback: vi.fn(), patchDraft: vi.fn(),
  capabilities: vi.fn(), templates: vi.fn(), targetConfigs: vi.fn() }))
vi.mock('@/api/etl', () => ({ etlApi: api }))
vi.mock('@/utils/etlProductInvalidation', () => ({ createEtlProductInvalidation: () => ({
  read: (request: () => unknown) => request(), readMany: (request: () => unknown) => request(),
  mutate: (_run: EtlRun, request: () => unknown) => request(),
}) }))
const scopes: EffectScope[] = []
function run(id = 'A', revision = `${id}-rev`): EtlRun {
  return { id, status: 'preview_ready', upload_id: id, file_name: `${id}.csv`, file_sha256: id,
    target_type: 'products', stage: 'preview_ready', progress: 100, preview_revision: revision,
    total_rows: 1, processed_rows: 1, summary: { new: 1, update: 0, skip: 0, error: 0, executed: 0 },
    draft: {}, details: {}, source_features: {}, receipt: {}, reversible: true }
}
function row(): EtlRunRow {
  return { id: 1, provenance: {}, source: {}, normalized: {}, validation_issues: [],
    suggested_action: 'new', final_action: 'new' } as EtlRunRow
}
function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (reason: Error) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
function fixture() {
  const scope = effectScope()
  scopes.push(scope)
  return scope.run(() => {
    const state = createEtlCenterState()
    state.currentRun.value = run()
    state.runRows.value = [row()]
    state.rowTotal.value = 1
    state.reviewedPreviewRevision.value = 'A-rev'
    const derived = createEtlCenterDerived({ state })
    const router = { replace: vi.fn().mockResolvedValue(undefined) }
    const actions = createEtlCenterRuns({ state, route: { query: {} }, router,
      canExecute: derived.canExecute, canRollback: computed(() => true),
      shipmentTemplateCandidates: derived.shipmentTemplateCandidates, bulkNewRows: derived.bulkNewRows })
    actions.syncDraft()
    const draft = createEtlCenterDraftActions({ state, currentCapability: derived.currentCapability, ...actions })
    return { state, actions, draft, router, scope }
  })!
}
type Fixture = ReturnType<typeof fixture>
const mutations = [
  { name: 'row override', api: 'patchDraft', start: (f: Fixture) => f.actions.overrideRow(row(), { target: { value: 'skip' } } as unknown as Event) },
  { name: 'bulk override', api: 'patchDraft', start: (f: Fixture) => f.actions.bulkOverride('skip') },
  { name: 'mapping save', api: 'patchDraft', start: (f: Fixture) => f.draft.saveMappings() },
  { name: 'retry', api: 'retry', start: (f: Fixture) => f.actions.retryRun() },
  { name: 'replay', api: 'replay', start: (f: Fixture) => f.actions.replayRun() },
  { name: 'rollback', api: 'rollback', start: (f: Fixture) => f.actions.rollbackRun() },
  { name: 'execute', api: 'execute', start: (f: Fixture) => f.actions.executeCurrentRun() },
] as const

beforeEach(() => {
  vi.resetAllMocks()
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  api.run.mockImplementation(async id => run(id))
  api.rows.mockImplementation(async (id, page) => ({ items: [row()], total: 1, page, page_size: 50, preview_revision: `${id}-rev` }))
  api.runs.mockResolvedValue([])
  api.capabilities.mockResolvedValue({ enabled: true, targets: [] })
  api.templates.mockResolvedValue([])
  api.targetConfigs.mockResolvedValue([])
})
afterEach(() => { scopes.splice(0).forEach(scope => scope.stop()); vi.restoreAllMocks(); vi.clearAllTimers(); vi.useRealTimers() })

describe('ETL mutation response ownership', () => {
  for (const mutation of mutations) {
    it.each(['resolve', 'reject'] as const)(`ignores stale ${mutation.name} %s after selecting another task`, async completion => {
      const f = fixture()
      const pending = deferred<EtlRun>()
      api[mutation.api].mockReturnValueOnce(pending.promise)
      const old = mutation.start(f)
      expect(api[mutation.api].mock.calls[0][0]).toBe('A')
      await f.actions.selectRun(run('B'))
      f.state.pageError.value = 'B status'
      if (completion === 'resolve') pending.resolve(run('A', 'A-next'))
      else pending.reject(new Error('Old A failure'))
      await old
      expect(f.state.currentRun.value?.id).toBe('B')
      expect(f.state.currentRun.value?.preview_revision).toBe('B-rev')
      expect(f.state.pageError.value).toBe('B status')
      expect(f.state.reviewedPreviewRevision.value).toBe('B-rev')
      expect(f.router.replace).toHaveBeenLastCalledWith({ path: '/business-docking', query: { run_id: 'B' } })
      expect(f.state.busy.value).toBe(false)
    })

    it(`applies current ${mutation.name} success and releases busy`, async () => {
      const f = fixture()
      const updated = run(mutation.name === 'replay' ? 'replayed' : 'A', 'new-revision')
      api[mutation.api].mockResolvedValueOnce(updated)
      api.rows.mockResolvedValueOnce({ items: [row()], total: 1, page: 1, preview_revision: updated.preview_revision })
      await mutation.start(f)
      expect(f.state.currentRun.value?.id).toBe(updated.id)
      expect(f.state.currentRun.value?.preview_revision).toBe(updated.preview_revision)
      expect(f.state.pageError.value).toBe('')
      expect(f.state.busy.value).toBe(false)
    })

    it(`reports current ${mutation.name} failure and releases busy`, async () => {
      const f = fixture()
      api[mutation.api].mockRejectedValueOnce(new Error('Current failure'))
      await mutation.start(f)
      expect(f.state.pageError.value).toBe('Current failure')
      expect(f.state.busy.value).toBe(false)
    })
  }

  it.each(['clear', 'round trip', 'revision', 'status', 'page', 'filter', 'dispose'] as const)('ignores a retry response after %s invalidates its context', async change => {
    const f = fixture()
    const pending = deferred<EtlRun>()
    api.retry.mockReturnValueOnce(pending.promise)
    const old = f.actions.retryRun()
    if (change === 'clear') f.state.currentRun.value = null
    if (change === 'round trip') { await f.actions.selectRun(run('B')); await f.actions.selectRun(run('A')) }
    if (change === 'revision') f.state.currentRun.value!.preview_revision = 'new-local-revision'
    if (change === 'status') f.state.currentRun.value!.status = 'completed'
    if (change === 'page') f.state.rowPage.value = 2
    if (change === 'filter') f.state.rowActionFilter.value = 'skip'
    if (change === 'dispose') f.scope.stop()
    const snapshot = JSON.stringify(f.state.currentRun.value)
    f.state.pageError.value = 'Current context'
    pending.resolve(run('A', 'old-response'))
    await old
    expect(JSON.stringify(f.state.currentRun.value)).toBe(snapshot)
    expect(f.state.pageError.value).toBe('Current context')
  })

  it.each(['rows', 'history', 'router'] as const)('ignores a replay continuation after %s finishes in another task', async stage => {
    const f = fixture()
    const pending = deferred<unknown>()
    api.replay.mockResolvedValueOnce(run('replayed'))
    if (stage === 'rows') api.rows.mockReturnValueOnce(pending.promise)
    if (stage === 'history') api.runs.mockReturnValueOnce(pending.promise)
    if (stage === 'router') f.router.replace.mockReturnValueOnce(pending.promise)
    const old = f.actions.replayRun()
    await flushPromises()
    await f.actions.selectRun(run('B'))
    f.state.pageError.value = 'B status'
    pending.resolve(stage === 'rows' ? { items: [row()], total: 1, page: 1, preview_revision: 'replayed-rev' } : stage === 'history' ? [run('replayed')] : undefined)
    await old
    expect(f.state.currentRun.value?.id).toBe('B')
    expect(f.state.pageError.value).toBe('B status')
    expect(f.router.replace).toHaveBeenLastCalledWith({ path: '/business-docking', query: { run_id: 'B' } })
  })

  it('ignores a replay router failure after another task is selected', async () => {
    const f = fixture()
    const pending = deferred<undefined>()
    api.replay.mockResolvedValueOnce(run('replayed'))
    f.router.replace.mockReturnValueOnce(pending.promise)
    const old = f.actions.replayRun()
    await flushPromises()
    await f.actions.selectRun(run('B'))
    pending.reject(new Error('Old navigation failure'))
    await old
    expect(f.state.currentRun.value?.id).toBe('B')
    expect(f.state.pageError.value).toBe('')
  })

  it('retains the newer loading operation busy state when an old mutation finishes', async () => {
    const f = fixture()
    const mutation = deferred<EtlRun>()
    const loading = deferred<{ enabled: boolean; targets: [] }>()
    api.retry.mockReturnValueOnce(mutation.promise)
    const old = f.actions.retryRun()
    await f.actions.selectRun(run('B'))
    api.capabilities.mockReturnValueOnce(loading.promise)
    const newer = f.actions.bootstrap()
    mutation.resolve(run('A'))
    await old
    expect(f.state.busy.value).toBe(true)
    loading.resolve({ enabled: true, targets: [] })
    await newer
    expect(f.state.busy.value).toBe(false)
  })
})
