import { flushPromises } from '@vue/test-utils'
import { computed, effectScope, type EffectScope } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { EtlRun, EtlRunRow } from '@/api/etl'
import { createEtlCenterState } from './etlCenterState'
import { createEtlCenterDerived } from './useEtlCenterDerived'
import { createEtlCenterRuns } from './useEtlCenterRuns'

const api = vi.hoisted(() => ({ run: vi.fn(), rows: vi.fn(), runs: vi.fn(), execute: vi.fn(), capabilities: vi.fn(), templates: vi.fn(), targetConfigs: vi.fn() }))
vi.mock('@/api/etl', () => ({ etlApi: api }))
vi.mock('@/utils/etlProductInvalidation', () => ({ createEtlProductInvalidation: () => ({ read: (fn: () => unknown) => fn(), readMany: (fn: () => unknown) => fn(), mutate: (_run: EtlRun, fn: () => unknown) => fn() }) }))
const scopes: EffectScope[] = []
function run(id = 'A', status = 'preview_ready'): EtlRun {
  return { id, status, upload_id: id, file_name: `${id}.csv`, file_sha256: id, target_type: 'products', stage: status, progress: 100,
    preview_revision: `${id}-rev`, total_rows: 120, processed_rows: 120, summary: { new: 120, update: 0, skip: 0, error: 0, executed: 0 },
    draft: {}, details: {}, source_features: {}, receipt: {}, reversible: true }
}
function rows(label = 'current', revision = 'A-rev', page = 1, total = 120) {
  return { items: [{ id: 1, provenance: {}, normalized: { label }, validation_issues: [] } as EtlRunRow], total, page, page_size: 50, preview_revision: revision }
}
function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (reason: Error) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
function fixture(initial = run()) {
  const scope = effectScope()
  scopes.push(scope)
  return scope.run(() => {
    const state = createEtlCenterState()
    state.currentRun.value = initial
    const derived = createEtlCenterDerived({ state })
    const router = { replace: vi.fn().mockResolvedValue(undefined) }
    const actions = createEtlCenterRuns({ state, route: { query: {} }, router, canExecute: derived.canExecute, canRollback: computed(() => true), shipmentTemplateCandidates: derived.shipmentTemplateCandidates, bulkNewRows: derived.bulkNewRows })
    actions.syncDraft()
    return { state, actions, derived, router, scope }
  })!
}
beforeEach(() => {
  vi.resetAllMocks()
  api.run.mockImplementation(async id => run(id))
  api.rows.mockImplementation(async (id, page) => rows('current', `${id}-rev`, page))
  api.runs.mockResolvedValue([])
})
afterEach(() => { scopes.splice(0).forEach(scope => scope.stop()); vi.clearAllTimers(); vi.useRealTimers() })

describe('ETL request ownership and reviewed page', () => {
  it.each(['resolve', 'reject'] as const)('ignores an obsolete polling %s after another task is selected', async completion => {
    vi.useFakeTimers()
    const { state, actions } = fixture(run('A', 'queued'))
    const pending = deferred<EtlRun>()
    api.run.mockReturnValueOnce(pending.promise)
    actions.schedulePoll()
    vi.advanceTimersByTime(1200)
    await actions.selectRun(run('B'))
    state.pageError.value = 'B status'
    if (completion === 'resolve') pending.resolve(run('A'))
    else pending.reject(new Error('Old A failure'))
    await flushPromises()
    expect(state.currentRun.value?.id).toBe('B')
    expect(state.pageError.value).toBe('B status')
    expect(state.runRows.value[0].normalized.label).toBe('current')
  })

  it('keeps the most recent task selection when detail requests resolve out of order', async () => {
    const { state, actions, router } = fixture()
    const first = deferred<EtlRun>()
    api.run.mockReturnValueOnce(first.promise)
    const old = actions.selectRun(run('B'))
    await actions.selectRun(run('C'))
    first.resolve(run('B'))
    await old
    expect(state.currentRun.value?.id).toBe('C')
    expect(router.replace).toHaveBeenLastCalledWith({ path: '/business-docking', query: { run_id: 'C' } })
  })

  it.each(['page', 'filter', 'same query'] as const)('ignores older %s rows even when task and revision are unchanged', async change => {
    const { state, actions } = fixture()
    const first = deferred<ReturnType<typeof rows>>()
    api.rows.mockReturnValueOnce(first.promise)
    const old = actions.loadRows()
    if (change === 'page') state.rowPage.value = 2
    if (change === 'filter') state.rowActionFilter.value = 'error'
    api.rows.mockResolvedValueOnce(rows('newest', 'A-rev', state.rowPage.value))
    await actions.loadRows()
    first.resolve(rows('oldest'))
    await old
    expect(state.runRows.value[0].normalized.label).toBe('newest')
    expect(state.reviewedPreviewRevision.value).toBe('A-rev')
  })

  it('does not revive a row request after a filter changes away and back', async () => {
    const { state, actions } = fixture()
    const first = deferred<ReturnType<typeof rows>>()
    api.rows.mockReturnValueOnce(first.promise)
    const old = actions.loadRows()
    state.rowActionFilter.value = 'error'
    state.rowActionFilter.value = ''
    first.resolve(rows('oldest'))
    await old
    expect(state.runRows.value).toEqual([])
    expect(state.reviewedPreviewRevision.value).toBeNull()
  })

  it('suppresses stale row failures while reporting a current failure', async () => {
    const { state, actions } = fixture()
    const old = deferred<ReturnType<typeof rows>>()
    api.rows.mockReturnValueOnce(old.promise)
    const first = actions.loadRows()
    state.rowPage.value = 2
    await actions.loadRows()
    old.reject(new Error('Old page offline'))
    await expect(first).resolves.toBeUndefined()
    expect(state.pageError.value).toBe('')
    api.rows.mockRejectedValueOnce(new Error('Current page offline'))
    await actions.loadRows()
    expect(state.pageError.value).toBe('Current page offline')
    expect(state.reviewedPreviewRevision.value).toBeNull()
  })

  it('resets paging, filter and previous review before reading another task', async () => {
    const { state, actions } = fixture()
    state.rowPage.value = 4
    state.rowActionFilter.value = 'skip'
    state.reviewedPreviewRevision.value = 'A-rev'
    const pending = deferred<EtlRun>()
    api.run.mockReturnValueOnce(pending.promise)
    const selected = actions.selectRun(run('B'))
    expect(state.reviewedPreviewRevision.value).toBeNull()
    expect(state.rowPage.value).toBe(1)
    expect(state.rowActionFilter.value).toBe('')
    pending.resolve(run('B'))
    await selected
    expect(api.rows).toHaveBeenLastCalledWith('B', 1, 50, '')
  })

  it.each([1, 4])('never marks an empty page %i as reviewed or executable', async page => {
    const { state, actions, derived } = fixture()
    state.rowPage.value = page
    api.rows.mockResolvedValueOnce({ ...rows('', 'A-rev', page, 2), items: [] })
    await actions.loadRows()
    expect(state.reviewedPreviewRevision.value).toBeNull()
    expect(derived.canExecute.value).toBe(false)
  })

  it('does not render rows from another server revision and accepts the matching retry', async () => {
    const { state, actions, derived } = fixture()
    api.rows.mockResolvedValueOnce(rows('wrong revision', 'previous-rev'))
    await actions.loadRows()
    expect(state.runRows.value).toEqual([])
    expect(derived.canExecute.value).toBe(false)
    await actions.loadRows()
    expect(derived.canExecute.value).toBe(true)
  })

  it('does not let a stale history response replace the selected task or newer list', async () => {
    const { state, actions } = fixture()
    const pending = deferred<EtlRun[]>()
    api.runs.mockReturnValueOnce(pending.promise)
    const old = actions.refreshRuns()
    api.runs.mockResolvedValueOnce([run('B')])
    await actions.selectRun(run('B'))
    await actions.refreshRuns()
    pending.resolve([{ ...run('B'), preview_revision: 'old-B-rev' }])
    await old
    expect(state.runs.value[0].preview_revision).toBe('B-rev')
    expect(state.currentRun.value?.preview_revision).toBe('B-rev')
  })

  it('ignores polling after the Vue scope is disposed', async () => {
    vi.useFakeTimers()
    const { state, actions, scope } = fixture(run('A', 'queued'))
    const pending = deferred<EtlRun>()
    api.run.mockReturnValueOnce(pending.promise)
    actions.schedulePoll()
    vi.advanceTimersByTime(1200)
    scope.stop()
    pending.resolve(run('A', 'previewing'))
    await flushPromises()
    expect(state.currentRun.value?.status).toBe('queued')
    expect(vi.getTimerCount()).toBe(0)
  })

  it('does not restore the previous task from a failed execution readback', async () => {
    const { state, actions } = fixture()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    await actions.loadRows()
    api.execute.mockRejectedValueOnce(new Error('Synthetic execution failure'))
    const readback = deferred<EtlRun>()
    api.run.mockReturnValueOnce(readback.promise)
    const execution = actions.executeCurrentRun()
    await flushPromises()
    await actions.selectRun(run('B'))
    readback.resolve(run('A'))
    await execution
    expect(state.currentRun.value?.id).toBe('B')
    expect(state.pageError.value).toBe('')
  })
})
