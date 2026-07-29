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

import xcmaxMarketProxy from './xcmaxMarketProxy'

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

  it('localEmployeeCronJobs reads local cron jobs', async () => {
    apiGet.mockResolvedValue([{ id: 'daily-sync' }])
    await xcmaxMarketProxy.localEmployeeCronJobs()
    expect(apiGet).toHaveBeenCalledWith('/api/xcmax/local/employee-cron/jobs')
  })

  it('localRunEmployeeCronJob posts manual run payload', async () => {
    apiPost.mockResolvedValue({ ok: true })
    await xcmaxMarketProxy.localRunEmployeeCronJob('job 1', { task: 'sync', input_data: { a: 1 } })
    expect(apiPost).toHaveBeenCalledWith(
      '/api/xcmax/local/employee-cron/jobs/job%201/run',
      { task: 'sync', input_data: { a: 1 } },
    )
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

  it('getEmployeeStatus rejects instead of fabricating an empty status on 404', async () => {
    apiGet.mockResolvedValueOnce({})
    apiGet.mockRejectedValueOnce({ status: 404 })
    const mod = await import('./xcmaxMarketProxy')
    await expect(mod.default.getEmployeeStatus('emp1')).rejects.toThrow(
      'AI 员工 emp1 的运行状态不存在',
    )
  })

  it('getEmployeeManifest rejects instead of fabricating empty handlers when not found', async () => {
    apiGet.mockResolvedValueOnce({})
    apiGet.mockRejectedValueOnce({ message: '员工不存在' })
    const mod = await import('./xcmaxMarketProxy')
    await expect(mod.default.getEmployeeManifest('emp2')).rejects.toThrow(
      'AI 员工 emp2 的 manifest 不存在',
    )
  })

  it('adminDutyGraphHealth reports unavailable when both health APIs fail', async () => {
    apiGet.mockRejectedValueOnce({ status: 404 })
    apiGet.mockRejectedValueOnce({ status: 404 })
    const mod = await import('./xcmaxMarketProxy')
    const r = (await mod.default.adminDutyGraphHealth()) as {
      ok: boolean
      source: string
      staffing: { error: string }
    }
    expect(r.ok).toBe(false)
    expect(r.source).toBe('runtime-unavailable')
    expect(r.staffing.error).toContain('均不可用')
  })

  it('getEmployeeStatus rejects when local api is unavailable', async () => {
    apiGet.mockRejectedValueOnce({ status: 404 })
    const mod = await import('./xcmaxMarketProxy')
    await expect(mod.default.getEmployeeStatus('emp3')).rejects.toThrow(
      'AI 员工运行时不可用',
    )
  })

  it('adminDutyGraphHealth preserves explicit ops fallback health', async () => {
    apiGet.mockRejectedValueOnce({ status: 404 })
    apiGet.mockResolvedValueOnce({
      success: true,
      staffing: { planned_count: 55, registered_count: 55 },
    })
    const mod = await import('./xcmaxMarketProxy')
    const r = (await mod.default.adminDutyGraphHealth()) as {
      ok: boolean
      source: string
    }
    expect(r.ok).toBe(true)
    expect(r.source).toBe('ops-fallback')
  })

  it('adminDutyGraphHealth does not promote an ambiguous ops payload to healthy', async () => {
    apiGet.mockRejectedValueOnce({ status: 404 })
    apiGet.mockResolvedValueOnce({
      staffing: { planned_count: 55, registered_count: 55 },
    })
    const mod = await import('./xcmaxMarketProxy')
    const r = (await mod.default.adminDutyGraphHealth()) as { ok: boolean }
    expect(r.ok).toBe(false)
  })

  it('executeEmployeeTask posts to local employee execute when local api is available', async () => {
    apiGet.mockResolvedValueOnce({})
    apiPost.mockResolvedValueOnce({ ok: true, source: 'local' })
    const mod = await import('./xcmaxMarketProxy')
    const r = await mod.default.executeEmployeeTask('emp 1', 'daily.brief', { topic: 'ops' })
    expect(r).toEqual({ ok: true, source: 'local' })
    expect(apiGet).toHaveBeenCalledWith('/api/xcmax/local/duty-graph/health')
    expect(apiPost).toHaveBeenCalledWith(
      '/api/xcmax/local/employees/emp%201/execute',
      { task: 'daily.brief', input_data: { topic: 'ops' } },
    )
  })

  it('executeEmployeeTask falls back to market proxy when local execute returns 404', async () => {
    apiGet.mockResolvedValueOnce({})
    apiPost.mockRejectedValueOnce({ status: 404 })
    apiPost.mockResolvedValueOnce({ ok: true, source: 'market' })
    const mod = await import('./xcmaxMarketProxy')
    const r = await mod.default.executeEmployeeTask('emp 2', 'daily.brief', { topic: 'ops' })
    expect(r).toEqual({ ok: true, source: 'market' })
    expect(apiPost).toHaveBeenNthCalledWith(
      1,
      '/api/xcmax/local/employees/emp%202/execute',
      { task: 'daily.brief', input_data: { topic: 'ops' } },
    )
    expect(apiPost).toHaveBeenNthCalledWith(
      2,
      '/api/xcmax/market-proxy/employees/emp%202/execute',
      { task: 'daily.brief', input_data: { topic: 'ops' } },
    )
  })
})
