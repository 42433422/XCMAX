import { afterEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { runtimeHealthPresentation } from './runtimeHealthPresentation'
import { useSidebarAppVersion } from './useSidebarAppVersion'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
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

describe('health timestamps and bounded retries', () => {
  function setup(fetchMock) {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-21T01:00:00Z'))
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
    vi.stubGlobal('fetch', fetchMock)
    return useSidebarAppVersion({ shouldShowAdminDeployStatus: ref(false) })
  }
  const healthy = () => ({ ok: true, json: async () => ({ status: 'healthy', version: '1.0.0.6' }) })

  it('shows no invented check time before the first completed request', async () => {
    const sidebar = setup(vi.fn().mockResolvedValue(healthy()))
    expect(sidebar.runtimeHealthCheck.value.text).toBe('尚未检测')
    expect(sidebar.runtimeHealthCheck.value.iso).toBe('')
    await sidebar.refreshHealthAppVersion()
    expect(sidebar.runtimeHealthCheck.value.iso).toBe('2026-10-21T01:00:00.000Z')
    expect(sidebar.runtimeHealthCheck.value.title).toContain('2026')
    sidebar.stopHealthPolling()
  })

  it('backs off failures for 60, 120, 240 and at most 300 seconds', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error('offline'))
    const sidebar = setup(fetchMock)
    sidebar.startHealthPolling()
    await vi.advanceTimersByTimeAsync(0)
    for (const interval of [60_000, 120_000, 240_000, 300_000, 300_000]) {
      const before = fetchMock.mock.calls.length
      await vi.advanceTimersByTimeAsync(interval - 1)
      expect(fetchMock).toHaveBeenCalledTimes(before)
      await vi.advanceTimersByTimeAsync(1)
      expect(fetchMock).toHaveBeenCalledTimes(before + 1)
    }
    expect(sidebar.runtimeHealthCheck.value.iso).toBe('2026-10-21T01:17:00.000Z')
    sidebar.stopHealthPolling()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('restores the normal 30 second cadence after recovery, including valid 503 bodies', async () => {
    const fetchMock = vi.fn().mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({ status: 'degraded', degradedReasons: ['LLM_RUNTIME_UNAVAILABLE'] }) })
      .mockResolvedValue(healthy())
    const sidebar = setup(fetchMock)
    sidebar.startHealthPolling()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(sidebar.runtimeHealth.value.tone).toBe('warning')
    await vi.advanceTimersByTimeAsync(30_000)
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(sidebar.runtimeHealth.value.tone).toBe('online')
    sidebar.stopHealthPolling()
  })

  it.each(['http', 'json', 'timeout'])('timestamps a failed %s probe without showing healthy', async (failure) => {
    const fetchMock = failure === 'timeout'
      ? vi.fn((_url, options: RequestInit) => new Promise((_resolve, reject) => options.signal?.addEventListener('abort', () => reject(new Error('timeout')))))
      : vi.fn().mockResolvedValue(failure === 'http'
        ? { ok: false, status: 500 }
        : { ok: true, json: async () => { throw new Error('invalid json') } })
    const sidebar = setup(fetchMock)
    sidebar.startHealthPolling()
    await vi.advanceTimersByTimeAsync(failure === 'timeout' ? 8_000 : 0)
    expect(sidebar.runtimeHealth.value.tone).toBe('offline')
    expect(sidebar.runtimeHealthCheck.value.iso).toBe(failure === 'timeout' ? '2026-10-21T01:00:08.000Z' : '2026-10-21T01:00:00.000Z')
    sidebar.stopHealthPolling()
  })

  it('does not let visibility and online events bypass backoff or duplicate a pending probe', async () => {
    const fetchMock = vi.fn().mockRejectedValueOnce(new Error('offline')).mockImplementation(() => new Promise(() => {}))
    const sidebar = setup(fetchMock)
    sidebar.startHealthPolling()
    await vi.advanceTimersByTimeAsync(0)
    for (let i = 0; i < 5; i++) {
      document.dispatchEvent(new Event('visibilitychange'))
      window.dispatchEvent(new Event('online'))
    }
    await vi.advanceTimersByTimeAsync(30_000)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(30_000)
    document.dispatchEvent(new Event('visibilitychange'))
    window.dispatchEvent(new Event('online'))
    await vi.advanceTimersByTimeAsync(0)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    sidebar.stopHealthPolling()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('ignores an old response after stop/start and preserves the new pending request', async () => {
    const resolves: Array<(value: unknown) => void> = []
    const fetchMock = vi.fn(() => new Promise((resolve) => resolves.push(resolve)))
    const sidebar = setup(fetchMock)
    sidebar.startHealthPolling()
    await vi.advanceTimersByTimeAsync(0)
    sidebar.stopHealthPolling()
    sidebar.startHealthPolling()
    await vi.advanceTimersByTimeAsync(0)
    resolves[0](healthy())
    await vi.advanceTimersByTimeAsync(0)
    expect(sidebar.runtimeHealthCheck.value.iso).toBe('')
    const pending = sidebar.refreshHealthAppVersion()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    resolves[1](healthy())
    await pending
    expect(sidebar.runtimeHealthCheck.value.iso).toBe('2026-10-21T01:00:00.000Z')
    sidebar.stopHealthPolling()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('skips hidden-page polling and removes event listeners on teardown', async () => {
    const fetchMock = vi.fn().mockResolvedValue(healthy())
    const sidebar = setup(fetchMock)
    sidebar.startHealthPolling()
    await vi.advanceTimersByTimeAsync(0)
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
    await vi.advanceTimersByTimeAsync(90_000)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    sidebar.stopHealthPolling()
    expect(sidebar.runtimeHealthCheck.value.iso).toBe('2026-10-21T01:00:00.000Z')
    window.dispatchEvent(new Event('online'))
    await vi.advanceTimersByTimeAsync(30_000)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})

it('aligns retries after a nonzero-duration timeout to the next normal polling tick', async () => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-10-21T01:00:00Z'))
  vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
  const fetchMock = vi.fn((_url, options: RequestInit) => new Promise((_resolve, reject) => {
    options.signal?.addEventListener('abort', () => reject(new Error('timeout')))
  }))
  vi.stubGlobal('fetch', fetchMock)
  const sidebar = useSidebarAppVersion({ shouldShowAdminDeployStatus: ref(false) })
  sidebar.startHealthPolling()
  await vi.advanceTimersByTimeAsync(8_000)
  expect(sidebar.runtimeHealthCheck.value.iso).toBe('2026-10-21T01:00:08.000Z')
  // Earliest retry is 68s; the retained 30s clock actually attempts it at 90s.
  await vi.advanceTimersByTimeAsync(81_999)
  expect(fetchMock).toHaveBeenCalledTimes(1)
  await vi.advanceTimersByTimeAsync(1)
  expect(fetchMock).toHaveBeenCalledTimes(2)
  sidebar.stopHealthPolling()
  expect(vi.getTimerCount()).toBe(0)
})


it('does not timestamp a pending request aborted by teardown', async () => {
  vi.useFakeTimers()
  const fetchMock = vi.fn((_url, options: RequestInit) => new Promise((_resolve, reject) => {
    options.signal?.addEventListener('abort', () => reject(new Error('stopped')))
  }))
  vi.stubGlobal('fetch', fetchMock)
  const sidebar = useSidebarAppVersion({ shouldShowAdminDeployStatus: ref(false) })
  sidebar.startHealthPolling()
  await vi.advanceTimersByTimeAsync(0)
  sidebar.stopHealthPolling()
  await vi.advanceTimersByTimeAsync(0)
  expect(sidebar.runtimeHealthCheck.value.iso).toBe('')
  expect(sidebar.runtimeHealth.value.tone).toBe('pending')
  expect(vi.getTimerCount()).toBe(0)
})

it('same-tick stop/start does not start a stale fetch or clear the new request', async () => {
  vi.useFakeTimers()
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: 'healthy' }) })
  vi.stubGlobal('fetch', fetchMock)
  const sidebar = useSidebarAppVersion({ shouldShowAdminDeployStatus: ref(false) })
  sidebar.startHealthPolling()
  sidebar.stopHealthPolling()
  sidebar.startHealthPolling()
  await vi.advanceTimersByTimeAsync(0)
  expect(fetchMock).toHaveBeenCalledTimes(1)
  expect(sidebar.runtimeHealth.value.tone).toBe('online')
  sidebar.stopHealthPolling()
  expect(vi.getTimerCount()).toBe(0)
})
