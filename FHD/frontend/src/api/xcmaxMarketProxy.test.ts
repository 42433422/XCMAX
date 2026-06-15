import { describe, it, expect, vi, beforeEach } from 'vitest'

const apiGet = vi.fn()
const apiPost = vi.fn()
const apiPut = vi.fn()
const apiDelete = vi.fn()

vi.mock('@/api/core', () => ({
  default: {
    get: (...a: unknown[]) => apiGet(...a),
    post: (...a: unknown[]) => apiPost(...a),
    put: (...a: unknown[]) => apiPut(...a),
    delete: (...a: unknown[]) => apiDelete(...a),
  },
}))

import xcmaxMarketProxy, { isLocalDutyApiAvailable } from './xcmaxMarketProxy'

describe('xcmaxMarketProxy', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPost.mockReset()
    apiPut.mockReset()
    apiDelete.mockReset()
    vi.resetModules()
  })

  it('marketReq dispatches GET by default', async () => {
    apiGet.mockResolvedValue({ ok: 1 })
    await xcmaxMarketProxy.adminListNoKeyEmployees()
    expect(apiGet).toHaveBeenCalledWith('/api/xcmax/market-proxy/admin/duty-graph/no-key-employees')
  })

  it('marketReq dispatches POST', async () => {
    apiPost.mockResolvedValue({})
    await xcmaxMarketProxy.adminAlignSingleEmployeeLlmToAuto('pkg 1', true)
    expect(apiPost).toHaveBeenCalled()
    const url = apiPost.mock.calls[0][0] as string
    expect(url).toContain('dry_run=true')
  })

  it('adminDutyGraphRunStart posts body', async () => {
    apiPost.mockResolvedValue({})
    await xcmaxMarketProxy.adminDutyGraphRunStart({ a: 1 })
    expect(apiPost).toHaveBeenCalledWith('/api/xcmax/market-proxy/admin/duty-graph/runs', { a: 1 })
  })

  it('adminEmployeeExecutionMetrics builds query string', async () => {
    apiGet.mockResolvedValue({})
    await xcmaxMarketProxy.adminEmployeeExecutionMetrics('e1', { limit: 10, offset: 5, user_id: 3 })
    const url = apiGet.mock.calls[0][0] as string
    expect(url).toContain('limit=10')
    expect(url).toContain('offset=5')
    expect(url).toContain('user_id=3')
  })

  it('adminEmployeeExecutionMetrics without params omits query', async () => {
    apiGet.mockResolvedValue({})
    await xcmaxMarketProxy.adminEmployeeExecutionMetrics('e1')
    const url = apiGet.mock.calls[0][0] as string
    expect(url.endsWith('/execution-metrics')).toBe(true)
  })

  it('llmChat posts provider/model/messages', async () => {
    apiPost.mockResolvedValue({})
    await xcmaxMarketProxy.llmChat('openai', 'gpt', [{ role: 'user' }], 256)
    expect(apiPost).toHaveBeenCalledWith(
      '/api/xcmax/market-proxy/llm/chat',
      expect.objectContaining({ provider: 'openai', model: 'gpt', max_tokens: 256 }),
    )
  })

  it('workbenchGetSession and butler start use admin endpoints', async () => {
    apiGet.mockResolvedValue({})
    apiPost.mockResolvedValue({})
    await xcmaxMarketProxy.workbenchGetSession('s1')
    expect(apiGet).toHaveBeenCalledWith('/api/xcmax/admin/all-hands-report/sessions/s1')
    await xcmaxMarketProxy.butlerAllHandsReportStartSession({ x: 1 })
    expect(apiPost).toHaveBeenCalledWith('/api/xcmax/admin/all-hands-report/sessions', { x: 1 })
  })
})

describe('xcmaxMarketProxy local duty api probe', () => {
  beforeEach(() => {
    vi.resetModules()
    apiGet.mockReset()
    apiPost.mockReset()
  })

  it('isLocalDutyApiAvailable true when health resolves', async () => {
    apiGet.mockResolvedValue({})
    const mod = await import('./xcmaxMarketProxy')
    expect(await mod.isLocalDutyApiAvailable()).toBe(true)
  })

  it('getEmployeeStatus returns empty status on 404', async () => {
    apiGet.mockResolvedValueOnce({})
    apiGet.mockRejectedValueOnce({ status: 404 })
    const mod = await import('./xcmaxMarketProxy')
    const r = (await mod.default.getEmployeeStatus('emp1')) as { deployed: boolean; employee_id: string }
    expect(r.deployed).toBe(false)
    expect(r.employee_id).toBe('emp1')
  })

  it('getEmployeeManifest returns empty manifest when not found', async () => {
    apiGet.mockResolvedValueOnce({})
    apiGet.mockRejectedValueOnce({ message: '员工不存在' })
    const mod = await import('./xcmaxMarketProxy')
    const r = (await mod.default.getEmployeeManifest('emp2')) as { handlers: unknown[]; employee_id: string }
    expect(r.handlers).toEqual([])
    expect(r.employee_id).toBe('emp2')
  })

  it('adminDutyGraphHealth falls back when local api unavailable (404 probe)', async () => {
    apiGet.mockRejectedValueOnce({ status: 404 })
    apiGet.mockRejectedValueOnce({ status: 404 })
    const mod = await import('./xcmaxMarketProxy')
    const r = (await mod.default.adminDutyGraphHealth()) as { ok: boolean; source: string }
    expect(r.ok).toBe(true)
    expect(r.source).toContain('fallback')
  })

  it('getEmployeeStatus returns empty status when local api unavailable', async () => {
    apiGet.mockRejectedValueOnce({ status: 404 })
    const mod = await import('./xcmaxMarketProxy')
    const r = (await mod.default.getEmployeeStatus('emp3')) as { deployed: boolean }
    expect(r.deployed).toBe(false)
  })
})
