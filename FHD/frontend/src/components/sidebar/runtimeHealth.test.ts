import { afterEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { runtimeHealthPresentation } from './runtimeHealthPresentation'
import { useSidebarAppVersion } from './useSidebarAppVersion'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('service health presented to the user', () => {
  it('does not claim readiness before a valid health response', () => {
    expect(runtimeHealthPresentation(null, 'checking').tone).toBe('pending')
    expect(runtimeHealthPresentation({}).tone).toBe('pending')
    expect(runtimeHealthPresentation({ status: 'unexpected' }).text).toBe('服务状态待确认')
  })

  it('distinguishes local AI readiness from a failed business service', () => {
    const state = runtimeHealthPresentation({
      status: 'degraded', runtime: { status: 'healthy' }, degradedReasons: ['LLM_RUNTIME_UNAVAILABLE'],
    })
    expect(state.text).toBe('部分 AI 能力未就绪')
    expect(state.detail).toContain('业务服务可连接')
    expect(state.detail).toContain('云端模型是否可用')
    expect(state.tone).toBe('warning')
  })

  it('prioritizes business blockers over optional AI degradation', () => {
    expect(runtimeHealthPresentation({
      status: 'degraded', runtime: { blockers: ['database_unavailable'] },
      degradedReasons: ['LLM_RUNTIME_UNAVAILABLE'],
    }).text).toBe('业务服务异常')
  })

  it('reports healthy only from an explicit successful response without blockers', () => {
    expect(runtimeHealthPresentation({ status: 'healthy', runtime: { status: 'healthy' } }).tone).toBe('online')
    expect(runtimeHealthPresentation({ status: 'healthy', degradedReasons: ['DEPENDENCY_UNAVAILABLE'] }).tone).toBe('warning')
  })
})

describe('live sidebar health', () => {
  it('uses the configured business API origin for health checks', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: 'healthy' }) })
    vi.stubGlobal('__XCMAX_API_BASE__', 'https://business.example.test')
    vi.stubGlobal('fetch', fetchMock)
    const sidebar = useSidebarAppVersion({ shouldShowAdminDeployStatus: ref(false) })
    await sidebar.refreshHealthAppVersion()
    expect(fetchMock).toHaveBeenCalledWith('https://business.example.test/api/health', expect.objectContaining({ credentials: 'include' }))
    sidebar.stopHealthPolling()
  })

  it('recovers after a connection failure and keeps the product version separate', async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce({ ok: true, json: async () => ({ status: 'healthy', version: '1.0.0.1' }) })
    vi.stubGlobal('fetch', fetchMock)
    const sidebar = useSidebarAppVersion({ shouldShowAdminDeployStatus: ref(false) })
    await sidebar.refreshHealthAppVersion()
    expect(sidebar.runtimeHealth.value.text).toBe('服务连接中断')
    await sidebar.refreshHealthAppVersion()
    expect(sidebar.runtimeHealth.value.text).toBe('系统正常')
    expect(sidebar.sidebarAppVersionText.value).toBe('v1.0.0.1')
    sidebar.stopHealthPolling()
  })

  it('shows the health body of a degraded HTTP 503 response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false, status: 503,
      json: async () => ({ status: 'degraded', degradedReasons: ['LLM_RUNTIME_UNAVAILABLE'] }),
    }))
    const sidebar = useSidebarAppVersion({ shouldShowAdminDeployStatus: ref(true) })
    await sidebar.refreshHealthAppVersion()
    expect(sidebar.runtimeHealth.value.tone).toBe('warning')
    expect(sidebar.sidebarAppVersionText.value).toBe('')
    sidebar.stopHealthPolling()
  })

  it('times out a stalled request and stops polling on teardown', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn((_url, options: RequestInit) => new Promise((_resolve, reject) => {
      options.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    }))
    vi.stubGlobal('fetch', fetchMock)
    const sidebar = useSidebarAppVersion({ shouldShowAdminDeployStatus: ref(false) })
    sidebar.startHealthPolling()
    await vi.advanceTimersByTimeAsync(8_000)
    expect(sidebar.runtimeHealth.value.text).toBe('服务连接中断')
    sidebar.stopHealthPolling()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
