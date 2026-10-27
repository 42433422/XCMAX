import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, reactive } from 'vue'
import { webcrypto } from 'node:crypto'
import { setRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'
import { productReadAccountEpoch, updateProductReadAccountScope } from '@/utils/productReadAccountScope'
import type { CatalogProduct } from '@/api/catalogPrices'

const api = vi.hoisted(() => ({ list: vi.fn(), submit: vi.fn(), lookup: vi.fn(), verify: vi.fn(), reconcile: vi.fn(), permissions: vi.fn(), proceed: vi.fn() }))
vi.mock('@/api/auth', () => ({ authApi: { getCurrentUser: api.permissions } }))
vi.mock('@/api/catalogPrices', () => ({ catalogPricesApi: api }))
vi.mock('@/api/agentRuns', () => ({ default: { continueRun: api.proceed } }))
const mods = reactive({ activeModId: 'mod-a' })
vi.mock('@/stores/mods', () => ({ useModsStore: () => mods }))
import { catalogPeriod, useAssistantCatalogPrices } from './useAssistantCatalogPrices'

const source = { source_id: 'source-a', epoch: 'epoch-a', protocol: 'etl-owned-mixed-v1' }
const revision = 'a'.repeat(64), serverDigest = 'b'.repeat(64)
const scopes: ReturnType<typeof effectScope>[] = []
function account(user = 7, tenantId = 5) {
  const value = { tenantId, localUserId: user }
  setRuntimeTenantStorageScopeInput(value); updateProductReadAccountScope(value)
}
function product(): CatalogProduct {
  return { id: 11, name: '私人产品', model_number: 'PRIVATE-11', unit: '私人客户', price: '12.50', currency: 'CNY', price_unit: 'kg', revision, source: { ...source }, history: [
    { source_key: 'src-null-1', price: '12.50', period_start: null, period_end: null, period_label: null, effective: true },
    { source_key: 'src-null-2', price: '13.00', period_start: null, period_end: null, period_label: null, effective: true },
    { source_key: 'src-old', price: '9.00', period_start: '2025-01-01', period_end: '2025-12-31', period_label: '2025', effective: false },
  ] }
}
function create() {
  const scope = effectScope(); scopes.push(scope)
  const verified = vi.fn()
  return { editor: scope.run(() => useAssistantCatalogPrices(verified))!, verified }
}
async function ready() {
  const state = create(), editor = state.editor
  editor.selected.value = true; await editor.search('PRIVATE')
  const row = editor.rows.value[0]
  Object.assign(editor.draftFor(row.id), { price: '15', reason: ' 核对原始凭证 ', period_start: '2026-01-01', period_end: '2026-12-31', confirmed: true })
  return { ...state, row }
}
function original() {
  return JSON.parse(localStorage.getItem(Object.keys(localStorage).find(k => k.startsWith('xcagi-catalog-price-operation-v1:'))!)!)
}
function response(completed = false) {
  const body = api.submit.mock.calls.at(-1)![1]
  const params = { ...body, product_id: 11, currency: 'CNY', price_unit: 'kg', selected_observations: product().history.filter(h => body.selected_sources.includes(h.source_key)) }
  return {
    success: true,
    data: { run_id: 'run-a', user_id: '7', message: '', status: completed ? 'completed' : 'waiting_user', metadata: { runtime_context: { tenant_id: 5, mod_id: 'mod-a' } },
      steps: [{ step_id: 'step-a', node_id: 'catalog-node', tool_id: 'catalog_products_v1', action: body.action, params, status: completed ? 'completed' : 'waiting_user', output: completed ? { success: true, business_verification: { verified: true } } : {} }], tool_calls: [] },
    approval: { run_id: 'run-a', step_id: 'step-a', tool_id: 'catalog_products_v1', action: body.action, grant: 'approval-a' },
    operation: { state: completed ? 'verified' : 'pending', operation_id: body.operation_id, run_id: 'run-a', request_digest: serverDigest },
  }
}
function verification(currentMatches = true) {
  return { success: true, data: { verified: true, outcome: 'saved', historical_effect_verified: true, fresh_save: false, current_matches: currentMatches, business_action_id: 'action-a', operation_id: original().operation, run_id: 'run-a', request_digest: serverDigest, product: { ...product(), revision: 'c'.repeat(64), price: '15.00' } } }
}

beforeEach(() => {
  localStorage.clear(); vi.clearAllMocks(); mods.activeModId = 'mod-a'; account()
  vi.stubGlobal('crypto', webcrypto)
  const held = new Set<string>()
  Object.defineProperty(navigator, 'locks', { configurable: true, value: { request: async (key: string, _options: unknown, fn: (lock: object | null) => Promise<unknown>) => {
    if (held.has(key)) return fn(null)
    held.add(key); try { return await fn({}) } finally { held.delete(key) }
  } } })
  api.list.mockResolvedValue({ success: true, capability: 'catalog_prices_v1', source, data: [product()] })
  api.submit.mockResolvedValue({ success: true, data: { run_id: 'run-a' } })
  api.proceed.mockResolvedValue({ success: true })
  api.permissions.mockResolvedValue({ success: true, data: { user: { id: 7 }, permissions: ['product.view', 'dataset.read', 'etl.execute', 'product.edit', 'dataset.write', 'etl.template.manage'] } })
})
afterEach(() => { scopes.splice(0).forEach(scope => scope.stop()); vi.unstubAllGlobals() })

describe('protected catalog source and readback', () => {
  it('requires an explicit selection, never queries on creation and binds capability/source', async () => {
    const { editor } = create()
    expect(editor.selected.value).toBe(false); expect(api.list).not.toHaveBeenCalled()
    await editor.search('x'); expect(api.list).not.toHaveBeenCalled()
    editor.selected.value = true; await editor.search('x')
    expect(editor.rows.value[0].unit).toBe('私人客户')
    expect(editor.rows.value[0].price_unit).toBe('kg')
  })
  it.each(['capability', 'source', 'revision', 'dimension', 'missing'])('rejects unverified list %s without fallback', async kind => {
    const bad = { success: true, capability: 'catalog_prices_v1', source, data: [product()] }
    if (kind === 'capability') bad.capability = 'legacy'
    if (kind === 'source') bad.data[0].source.epoch = 'other'
    if (kind === 'revision') bad.data[0].revision = 'not-cas'
    if (kind === 'dimension') bad.data[0].price_unit = ''
    if (kind === 'missing') bad.success = false
    api.list.mockResolvedValue(bad)
    const { editor } = create(); editor.selected.value = true; await editor.search('x')
    expect(editor.rows.value).toEqual([]); expect(editor.error.value).not.toBe('')
    expect(api.submit).not.toHaveBeenCalled()
  })
  it.each(['account', 'mod', 'deselect'])('retires late reads after %s change', async kind => {
    let resolve!: (value: unknown) => void
    api.list.mockReturnValue(new Promise(r => { resolve = r }))
    const { editor } = create(); editor.selected.value = true
    const pending = editor.search('x')
    if (kind === 'account') { account(8); account(7) }
    if (kind === 'mod') { mods.activeModId = 'mod-b'; mods.activeModId = 'mod-a' }
    if (kind === 'deselect') { editor.selected.value = false; editor.selected.value = true }
    resolve({ success: true, capability: 'catalog_prices_v1', source, data: [product()] }); await pending
    expect(editor.rows.value).toEqual([]); expect(editor.loading.value).toBe(false)
  })
  it('does not infer dates for null or half-marked periods', () => {
    expect(catalogPeriod(null, null)).toBe('未标注期间')
    expect(catalogPeriod(null, '2026-12-31')).toBe('未标注起日 至 2026-12-31')
  })
})

describe('reviewed repeatable price edits', () => {
  it('registers UUID+hash only, approves once, verifies same source and enables a new CAS revision', async () => {
    const { editor, row, verified } = await ready()
    await editor.submit(row)
    const saved = original()
    expect(saved.operation).toMatch(/^[0-9a-f-]{36}$/); expect(saved.digest).toMatch(/^[0-9a-f]{64}$/)
    const text = JSON.stringify(saved)
    for (const secret of [row.name, row.unit, row.model_number, '15.00', '核对原始凭证']) expect(text).not.toContain(secret)
    expect(api.submit.mock.calls[0][1]).toMatchObject({ price: '15.00', revision, reason: '核对原始凭证', selected_sources: [], confirmed: true })
    await editor.submit(row); expect(api.submit).toHaveBeenCalledOnce()
    api.lookup.mockResolvedValue(response()); await editor.check(row)
    expect(editor.statusFor(11)?.canApprove).toBe(true); expect(api.proceed).not.toHaveBeenCalled()
    await editor.check(row, true); await editor.check(row, true)
    expect(api.proceed).toHaveBeenCalledOnce(); expect(verified).not.toHaveBeenCalled()
    api.lookup.mockResolvedValue(response(true)); api.verify.mockResolvedValue(verification())
    await editor.check(row)
    expect(editor.statusFor(11)?.state).toBe('verified'); expect(verified).toHaveBeenCalledWith(11)
    expect(localStorage.length).toBe(0)
    const next = editor.rows.value[0]
    Object.assign(editor.draftFor(11), { price: '16.00', reason: '第二次', period_start: '2027-01-01', period_end: '2027-12-31', confirmed: true })
    await editor.submit(next)
    expect(api.submit).toHaveBeenCalledTimes(2)
    expect(api.submit.mock.calls[1][1].revision).toBe('c'.repeat(64))
    expect(api.submit.mock.calls[1][1].operation_id).not.toBe(saved.operation)
  })
  it('corrects an unmarked period with all conflicting source observations and readonly dimensions', async () => {
    const { editor, row } = await ready()
    editor.selectMode(row, 'correct_price'); editor.selectCorrection(row, 'src-null-1')
    Object.assign(editor.draftFor(11), { price: '14.2', reason: '纠错', confirmed: true, period_start: '2099-01-01', period_end: '2099-12-31' })
    await editor.submit(row)
    expect(api.submit.mock.calls[0][1]).toMatchObject({ action: 'correct_price', price: '14.20', period_start: null, period_end: null, selected_sources: ['src-null-1', 'src-null-2'] })
    expect(api.submit.mock.calls[0][1]).not.toHaveProperty('unit')
    api.lookup.mockResolvedValue(response()); await editor.check(row)
    expect(editor.statusFor(11)?.preview).toMatchObject({ period_start: null, period_end: null, currency: 'CNY', price_unit: 'kg' })
    expect(editor.statusFor(11)?.preview?.observations.map(o => o.price)).toEqual(['12.50', '13.00'])
  })
  it.each(['lost', 'no-run'])('recovers %s initial response by original UUID, never resubmits', async kind => {
    const { editor, row } = await ready()
    if (kind === 'lost') api.submit.mockRejectedValueOnce(new Error('response lost'))
    else api.submit.mockResolvedValueOnce({ success: false })
    await editor.submit(row)
    expect(original().runId).toBe('')
    const reloaded = await ready()
    api.lookup.mockResolvedValue(response())
    await reloaded.editor.check(reloaded.row)
    expect(api.lookup).toHaveBeenCalledWith(original().operation, 'mod-a')
    expect(reloaded.editor.statusFor(11)?.canApprove).toBe(true)
    await reloaded.editor.submit(reloaded.row); expect(api.submit).toHaveBeenCalledOnce()
  })
  it('keeps lost approval unknown and does not consume the grant twice', async () => {
    const { editor, row } = await ready(); await editor.submit(row)
    api.lookup.mockResolvedValue(response()); api.proceed.mockRejectedValueOnce(new Error('lost approval'))
    await editor.check(row, true); await editor.check(row, true)
    expect(api.proceed).toHaveBeenCalledOnce(); expect(original().approvalSent).toBe(true)
    expect(editor.statusFor(11)?.canApprove).toBe(false)
  })
  it.each(['running', 'unknown', 'waiting_user'])('recovers durable commit while host run remains %s using read-only verification', async status => {
    const { editor, row, verified } = await ready(); await editor.submit(row)
    const run = response(true)
    run.data.status = status
    run.data.steps[0].status = 'running'
    run.data.steps[0].output = { success: false, business_verification: { verified: false } }
    api.lookup.mockResolvedValue(run); api.verify.mockResolvedValue(verification())
    await editor.check(row)
    expect(verified).toHaveBeenCalledWith(11)
    expect(editor.statusFor(11)?.state).toBe('verified')
    expect(api.proceed).not.toHaveBeenCalled(); expect(api.submit).toHaveBeenCalledOnce()
  })
  it.each(['failed', 'waiting_user'])('clears only a proven no-effect rejection despite %s host status and requires a fresh explicit request', async status => {
    const { editor, row, verified } = await ready(); await editor.submit(row)
    const oldOperation = original().operation
    const run = response(status !== 'waiting_user'); run.data.status = status; run.operation.state = 'rejected'
    const proof = verification(false)
    Object.assign(proof.data, { outcome: 'rejected_no_effect', historical_effect_verified: false, reason_code: 'review_precondition_changed' })
    proof.data.product.price = '16.00'
    api.lookup.mockResolvedValue(run); api.verify.mockResolvedValue(proof)
    await editor.check(row)
    expect(editor.statusFor(11)?.message).toBe('未保存：审核前态已变化，请重新核对再提交')
    expect(verified).not.toHaveBeenCalled(); expect(api.proceed).not.toHaveBeenCalled(); expect(localStorage.length).toBe(0)
    const refreshed = editor.rows.value[0]
    expect(refreshed.price).toBe('16.00'); expect(editor.canEdit(refreshed)).toBe(true)
    expect(editor.draftFor(11).confirmed).toBe(false)
    await editor.submit(refreshed); expect(api.submit).toHaveBeenCalledOnce()
    Object.assign(editor.draftFor(11), { price: '17.00', reason: '重新审核', period_start: '2027-01-01', period_end: '2027-12-31', confirmed: true })
    await editor.submit(refreshed)
    expect(api.submit).toHaveBeenCalledTimes(2)
    expect(api.submit.mock.calls[1][1].operation_id).not.toBe(oldOperation)
    expect(api.submit.mock.calls[1][1].revision).toBe('c'.repeat(64))
  })
  it.each(['missing-reason', 'wrong-reason', 'current-matches', 'unverified', 'wrong-source', 'unknown-outcome'])('retains UNKNOWN for incomplete rejected proof: %s', async kind => {
    const { editor, row, verified } = await ready(); await editor.submit(row)
    const proof = { ...verification(false), data: { ...verification(false).data, outcome: 'rejected_no_effect', historical_effect_verified: false, reason_code: 'review_precondition_changed' } }
    if (kind === 'missing-reason') delete (proof.data as Partial<typeof proof.data>).reason_code
    if (kind === 'wrong-reason') proof.data.reason_code = 'worker_unknown'
    if (kind === 'current-matches') proof.data.current_matches = true
    if (kind === 'unverified') proof.data.verified = false
    if (kind === 'wrong-source') proof.data.product.source.epoch = 'other'
    if (kind === 'unknown-outcome') proof.data.outcome = 'unknown'
    const run = response(true); run.data.status = 'failed'; run.operation.state = 'rejected'
    api.lookup.mockResolvedValue(run); api.verify.mockResolvedValue(proof)
    await editor.check(row); await editor.submit(row)
    expect(editor.statusFor(11)?.state).toBe('unknown'); expect(localStorage.length).toBe(1)
    expect(api.submit).toHaveBeenCalledOnce(); expect(verified).not.toHaveBeenCalled()
  })
  it('reports later verified changes without replaying or retaining a stale revision', async () => {
    const { editor, row, verified } = await ready(); await editor.submit(row)
    api.lookup.mockResolvedValue(response(true)); api.verify.mockResolvedValue(verification(false))
    await editor.check(row)
    expect(editor.statusFor(11)?.message).toContain('后续变更'); expect(verified).not.toHaveBeenCalled()
    expect(editor.rows.value[0].revision).toBe('c'.repeat(64)); expect(api.submit).toHaveBeenCalledOnce()
  })
})

describe('fail-closed boundaries', () => {
  it.each(['amount', 'too-large', 'date', 'missing-date', 'same-date', 'reason', 'long-reason', 'confirmation', 'partial-conflict'])('rejects %s locally before persisting or submitting', async kind => {
    const { editor, row } = await ready(), draft = editor.draftFor(11)
    if (kind === 'amount') draft.price = '1e2'
    if (kind === 'too-large') draft.price = '100000000'
    if (kind === 'date') draft.period_start = '2026-02-30'
    if (kind === 'missing-date') draft.period_start = ''
    if (kind === 'reason') draft.reason = ' '
    if (kind === 'long-reason') draft.reason = 'r'.repeat(501)
    if (kind === 'same-date') draft.period_end = draft.period_start
    if (kind === 'confirmation') draft.confirmed = false
    if (kind === 'partial-conflict') { draft.action = 'correct_price'; draft.selected_sources = ['src-null-1'] }
    await editor.submit(row)
    expect(api.submit).not.toHaveBeenCalled(); expect(localStorage.length).toBe(0)
    expect(editor.canEdit(row)).toBe(true)
  })
  it.each(['owner', 'tenant', 'mod', 'amount', 'period', 'observation', 'operation', 'source', 'tool', 'already-started', 'unknown'])('does not approve mismatched %s', async kind => {
    const { editor, row } = await ready(); await editor.submit(row)
    const result = response(), step = result.data.steps[0]
    if (kind === 'owner') result.data.user_id = '8'
    if (kind === 'tenant') result.data.metadata.runtime_context.tenant_id = 8
    if (kind === 'mod') result.data.metadata.runtime_context.mod_id = 'other'
    if (kind === 'amount') step.params.price = '99.00'
    if (kind === 'period') step.params.period_start = null
    if (kind === 'observation') step.params.selected_observations = [product().history[0]]
    if (kind === 'operation') result.operation.operation_id = crypto.randomUUID()
    if (kind === 'source') row.source.epoch = 'replaced'
    if (kind === 'tool') step.tool_id = 'products'
    if (kind === 'already-started') result.data.tool_calls = [{ call_id: 'started' }] as never[]
    if (kind === 'unknown') Object.assign(step.output, { outcome: 'unknown' })
    api.lookup.mockResolvedValue(result); await editor.check(row, true)
    expect(api.proceed).not.toHaveBeenCalled(); expect(editor.statusFor(11)?.state).toBe('unknown')
    expect(localStorage.length).toBe(1)
  })
  it.each(['readback', 'epoch', 'digest', 'run', 'product', 'revision', 'business-action'])('retains original on bad verification %s', async kind => {
    const { editor, row, verified } = await ready(); await editor.submit(row)
    const proof = verification()
    if (kind === 'readback') proof.data.verified = false
    if (kind === 'epoch') proof.data.product.source.epoch = 'new'
    if (kind === 'digest') proof.data.request_digest = 'd'.repeat(64)
    if (kind === 'run') proof.data.run_id = 'wrong'
    if (kind === 'product') proof.data.product.id = 99
    if (kind === 'revision') proof.data.product.revision = ''
    if (kind === 'business-action') proof.data.business_action_id = ''
    api.lookup.mockResolvedValue(response(true)); api.verify.mockResolvedValue(proof)
    await editor.check(row)
    expect(verified).not.toHaveBeenCalled(); expect(localStorage.length).toBe(1)
    expect(editor.canEdit(row)).toBe(false)
  })
  it('blocks writes without navigator locks', async () => {
    const { editor, row } = await ready()
    Object.defineProperty(navigator, 'locks', { configurable: true, value: undefined })
    await editor.submit(row); expect(api.submit).not.toHaveBeenCalled()
    expect(editor.statusFor(11)?.message).toContain('跨窗口')
  })
  it('blocks two windows sharing the original operation marker', async () => {
    const a = await ready(), b = await ready()
    await Promise.all([a.editor.submit(a.row), b.editor.submit(b.row)])
    expect(api.submit).toHaveBeenCalledOnce(); expect(b.editor.canEdit(b.row)).toBe(false)
  })
  it('keeps an unknown original after lookup failure, including 404', async () => {
    const { editor, row } = await ready(); await editor.submit(row)
    api.lookup.mockRejectedValue(new Error('404 original not found'))
    await editor.check(row); await editor.submit(row)
    expect(api.submit).toHaveBeenCalledOnce(); expect(localStorage.length).toBe(1)
    expect(editor.statusFor(11)?.state).toBe('unknown')
  })
  it('does not dispatch when the original marker cannot be persisted', async () => {
    const { editor, row } = await ready()
    const fail = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('storage unavailable') })
    try {
      await editor.submit(row)
      expect(api.submit).not.toHaveBeenCalled()
      expect(editor.statusFor(11)?.message).toContain('storage unavailable')
    } finally { fail.mockRestore() }
  })
  it('never overwrites a malformed original marker', async () => {
    const { editor, row } = await ready(); await editor.submit(row)
    const key = Object.keys(localStorage)[0]
    localStorage.setItem(key, '{broken')
    await editor.submit(row); await editor.check(row)
    expect(api.submit).toHaveBeenCalledOnce(); expect(api.lookup).not.toHaveBeenCalled()
    expect(localStorage.getItem(key)).toBe('{broken'); expect(editor.canEdit(row)).toBe(false)
  })
  it('does not show another account a late initial run response or lose the original UUID', async () => {
    const { editor, row } = await ready()
    let resolve!: (value: unknown) => void
    api.submit.mockReturnValueOnce(new Promise(r => { resolve = r }))
    const saving = editor.submit(row)
    await vi.waitFor(() => expect(api.submit).toHaveBeenCalledOnce())
    const saved = original()
    account(8); resolve({ success: true, data: { run_id: 'late-run' } }); await saving
    expect(editor.selected.value).toBe(false); expect(editor.rows.value).toEqual([])
    account(7)
    expect(original().operation).toBe(saved.operation); expect(original().runId).toBe('')
  })
  it('preserves original after a stale verification arrives across Mod navigation', async () => {
    const { editor, row, verified } = await ready(); await editor.submit(row)
    const proof = verification()
    let resolve!: (value: unknown) => void
    api.lookup.mockResolvedValue(response(true))
    api.verify.mockReturnValueOnce(new Promise(r => { resolve = r }))
    const checking = editor.check(row)
    await vi.waitFor(() => expect(api.verify).toHaveBeenCalledOnce())
    mods.activeModId = 'other'; mods.activeModId = 'mod-a'
    resolve(proof); await checking
    expect(verified).not.toHaveBeenCalled(); expect(localStorage.length).toBe(1)
    expect(editor.rows.value).toEqual([])
  })
  it('only accepts the newest query result', async () => {
    const { editor } = create(); editor.selected.value = true
    let resolve!: (value: unknown) => void
    api.list.mockReturnValueOnce(new Promise(r => { resolve = r }))
    const old = editor.search('old')
    await editor.search('new')
    resolve({ success: true, capability: 'catalog_prices_v1', source, data: [{ ...product(), id: 99 }] }); await old
    expect(editor.rows.value.map(row => row.id)).toEqual([11])
  })

})


describe('explicit original-operation reconciliation', () => {
  async function pending(currentMatches = true) {
    const state = await ready(); await state.editor.submit(state.row)
    const run = response(true); run.operation.state = 'pending'; run.data.status = 'running'
    api.lookup.mockResolvedValue(run); api.verify.mockResolvedValue(verification(currentMatches))
    await state.editor.check(state.row)
    return state
  }
  it.each([true, false])('GET history/current_matches=%s never clears a pending HOST marker or writes', async matches => {
    const { editor, row, verified } = await pending(matches)
    expect(localStorage.length).toBe(1); expect(editor.canEdit(row)).toBe(false)
    expect(editor.statusFor(11)?.canReconcile).toBe(true)
    expect(editor.statusFor(11)?.message).toContain('HOST 原操作尚未终结')
    expect(api.reconcile).not.toHaveBeenCalled(); expect(api.proceed).not.toHaveBeenCalled(); expect(verified).not.toHaveBeenCalled()
    await editor.submit(row); expect(api.submit).toHaveBeenCalledOnce()
  })
  it('cancel and a bare confirm preserve evidence without POST', async () => {
    const { editor, row } = await pending(), before = JSON.stringify(original())
    await editor.confirmReconciliation(row); expect(api.reconcile).not.toHaveBeenCalled()
    editor.requestReconciliation(row); expect(editor.reconciliationFor(11)).toBe(original().operation)
    editor.cancelReconciliation(); await editor.confirmReconciliation(row)
    expect(editor.reconciliationFor(11)).toBeUndefined(); expect(JSON.stringify(original())).toBe(before)
    expect(api.reconcile).not.toHaveBeenCalled()
  })
  it.each([true, false])('explicit confirm finalizes once, preserving historical current_matches=%s meaning', async matches => {
    const { editor, row, verified } = await pending(matches), operation = original().operation
    api.reconcile.mockResolvedValue(verification(matches))
    editor.requestReconciliation(row)
    await Promise.all([editor.confirmReconciliation(row), editor.confirmReconciliation(row)])
    expect(api.reconcile).toHaveBeenCalledExactlyOnceWith(operation, 'mod-a')
    expect(api.submit).toHaveBeenCalledOnce(); expect(api.proceed).not.toHaveBeenCalled()
    expect(localStorage.length).toBe(0); expect(editor.statusFor(11)?.state).toBe('verified')
    expect(editor.statusFor(11)?.message).toContain('本次未重新保存')
    expect(verified).toHaveBeenCalledTimes(matches ? 1 : 0)
  })
  it('explicitly finalizes a proven no-effect rejection without reporting a saved price', async () => {
    const { editor, row, verified } = await pending(), proof = verification(false)
    Object.assign(proof.data, { outcome: 'rejected_no_effect', historical_effect_verified: false, reason_code: 'review_precondition_changed' })
    api.reconcile.mockResolvedValue(proof)
    editor.requestReconciliation(row); await editor.confirmReconciliation(row)
    expect(localStorage.length).toBe(0); expect(verified).not.toHaveBeenCalled()
    expect(editor.statusFor(11)?.message).toContain('未保存')
  })
  it.each([409, 401, 422])('failed read-only verification HTTP %s never becomes reconciliation', async status => {
    const { editor, row } = await pending(), before = JSON.stringify(original())
    api.verify.mockRejectedValueOnce(Object.assign(new Error(String(status)), { status }))
    await editor.check(row)
    expect(api.reconcile).not.toHaveBeenCalled(); expect(JSON.stringify(original())).toBe(before)
    expect(editor.statusFor(11)?.canReconcile).not.toBe(true)
  })
  it.each([409, 401, 422])('HTTP %s retains original marker and never retries automatically', async status => {
    const { editor, row } = await pending(), before = JSON.stringify(original())
    api.reconcile.mockRejectedValueOnce(Object.assign(new Error(String(status)), { status }))
    editor.requestReconciliation(row); await editor.confirmReconciliation(row)
    await editor.confirmReconciliation(row); await editor.submit(row)
    expect(api.reconcile).toHaveBeenCalledOnce(); expect(api.submit).toHaveBeenCalledOnce()
    expect(JSON.stringify(original())).toBe(before); expect(editor.statusFor(11)?.state).toBe('unknown')
  })
  it.each(['account', 'tenant', 'mod', 'epoch', 'deselect', 'search'])('invalidates confirmation after %s navigation without losing original marker', async kind => {
    const { editor, row } = await pending(), before = JSON.stringify(original())
    editor.requestReconciliation(row)
    if (kind === 'account') { account(8); account(7) }
    if (kind === 'tenant') { account(7, 6); account() }
    if (kind === 'mod') { mods.activeModId = 'other'; mods.activeModId = 'mod-a' }
    if (kind === 'epoch') productReadAccountEpoch.value++
    if (kind === 'deselect') { editor.selected.value = false; editor.selected.value = true }
    if (kind === 'search') await editor.search('new')
    await editor.confirmReconciliation(row)
    expect(api.reconcile).not.toHaveBeenCalled(); expect(JSON.stringify(original())).toBe(before)
  })
  it.each(['read-only', 'revoked', 'foreign-user', 'unavailable'])('does not reconcile with %s current permissions', async kind => {
    const { editor, row } = await pending()
    editor.requestReconciliation(row)
    if (kind === 'unavailable') api.permissions.mockRejectedValue(new Error('401'))
    else api.permissions.mockResolvedValue({ success: true, data: { user: { id: kind === 'foreign-user' ? 8 : 7 }, permissions: ['product.view', 'dataset.read'] } })
    await editor.confirmReconciliation(row)
    expect(api.reconcile).not.toHaveBeenCalled(); expect(localStorage.length).toBe(1)
    await editor.check(row)
    expect(api.verify).toHaveBeenCalled(); expect(editor.statusFor(11)?.canReconcile).toBe(false)
  })
  it.each(['operation', 'source', 'revision', 'digest', 'fresh-save', 'historical-proof'])('rejects bad POST receipt %s without clearing evidence', async kind => {
    const { editor, row, verified } = await pending(), proof = verification()
    if (kind === 'operation') proof.data.operation_id = crypto.randomUUID()
    if (kind === 'source') proof.data.product.source.epoch = 'other'
    if (kind === 'revision') proof.data.product.revision = ''
    if (kind === 'digest') proof.data.request_digest = 'd'.repeat(64)
    if (kind === 'fresh-save') proof.data.fresh_save = true
    if (kind === 'historical-proof') proof.data.historical_effect_verified = false
    api.reconcile.mockResolvedValue(proof)
    editor.requestReconciliation(row); await editor.confirmReconciliation(row)
    expect(localStorage.length).toBe(1); expect(verified).not.toHaveBeenCalled()
  })
  it('drops a late POST after context change and recovers only by terminal lookup plus GET', async () => {
    const { editor, row, verified } = await pending(), proof = verification()
    let resolve!: (value: unknown) => void
    api.reconcile.mockReturnValueOnce(new Promise(r => { resolve = r }))
    editor.requestReconciliation(row); const confirming = editor.confirmReconciliation(row)
    await vi.waitFor(() => expect(api.reconcile).toHaveBeenCalledOnce())
    mods.activeModId = 'other'; mods.activeModId = 'mod-a'
    resolve(proof); await confirming
    expect(localStorage.length).toBe(1); expect(verified).not.toHaveBeenCalled()
    editor.selected.value = true; await editor.search('again')
    api.lookup.mockResolvedValue(response(true)); api.verify.mockResolvedValue(proof)
    await editor.check(editor.rows.value[0])
    expect(localStorage.length).toBe(0); expect(api.reconcile).toHaveBeenCalledOnce()
  })
})
