import { beforeEach, describe, expect, it, vi } from 'vitest'
const http = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('./core', () => ({ api: http }))
import { catalogPricesApi, type CatalogEditRequest } from './catalogPrices'
import agentRunsApi from './agentRuns'
const headers = { headers: { 'X-XCAGI-Active-Mod-Id': 'selected-mod' } }
const base = '/api/elt/owned-mixed-v1/products'
beforeEach(() => vi.clearAllMocks())
describe('protected catalog transport', () => {
  it('binds every read to the explicit selected Mod without ERP routing', async () => {
    await catalogPricesApi.list('name', 'selected-mod')
    await catalogPricesApi.read(7, 'selected-mod')
    await catalogPricesApi.lookup('original-uuid', 'selected-mod')
    await catalogPricesApi.verify('original-uuid', 'selected-mod')
    expect(http.get.mock.calls).toEqual([
      [base, { keyword: 'name' }, headers],
      [`${base}/7`, {}, headers],
      [`${base}/edits/original-uuid`, {}, headers],
      [`${base}/edits/original-uuid/verification`, {}, headers],
    ])
    expect(http.post).not.toHaveBeenCalled()
  })
  it('sends one original request and uses existing run continuation with the same Mod header', async () => {
    const body: CatalogEditRequest = { operation_id: 'original-uuid', revision: 'revision', action: 'correct_price', price: '1.00', period_start: null, period_end: null, selected_sources: ['source'], reason: 'correction', confirmed: true }
    await catalogPricesApi.submit(7, body, 'selected-mod')
    await agentRunsApi.continueRun('run-a', { approval_grant: 'grant' }, 'selected-mod')
    expect(http.post.mock.calls).toEqual([
      [`${base}/7/edits`, body, headers],
      ['/api/agent/runs/run-a/continue', { approval_grant: 'grant' }, headers],
    ])
  })
  it('reconciles only the original operation with exact explicit confirmation and selected Mod', async () => {
    await catalogPricesApi.reconcile('original/uuid', 'selected-mod')
    expect(http.post).toHaveBeenCalledExactlyOnceWith(`${base}/edits/original%2Fuuid/reconciliation`, { confirmed: true }, headers)
    expect(http.get).not.toHaveBeenCalled()
    expect(() => catalogPricesApi.reconcile('original', '')).toThrow('必须明确选择 Mod')
  })
  it.each([409, 401, 422])('does not replay or replace reconciliation on HTTP %s', async status => {
    http.post.mockRejectedValueOnce(Object.assign(new Error(String(status)), { status }))
    await expect(catalogPricesApi.reconcile('original', 'selected-mod')).rejects.toThrow(String(status))
    expect(http.post).toHaveBeenCalledOnce(); expect(http.get).not.toHaveBeenCalled()
  })
  it('rejects a missing explicit Mod before any request', () => {
    expect(() => catalogPricesApi.list('x', '')).toThrow('必须明确选择 Mod')
    expect(http.get).not.toHaveBeenCalled()
  })
  it('does not automatically replay a lost response', async () => {
    http.post.mockRejectedValueOnce(new Error('lost response'))
    await expect(catalogPricesApi.submit(7, {} as CatalogEditRequest, 'selected-mod')).rejects.toThrow('lost response')
    expect(http.post).toHaveBeenCalledOnce()
  })
})
