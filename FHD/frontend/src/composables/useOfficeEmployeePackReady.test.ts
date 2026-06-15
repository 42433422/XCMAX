import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useOfficeEmployeePackReady } from '@/composables/useOfficeEmployeePackReady'

vi.mock('@/utils/platformShellApi', () => ({
  fetchEmployeePlannerStatus: vi.fn().mockResolvedValue({
    installed_employee_pack_count: 2,
    registered_tool_count: 5,
    registered_tool_names: ['tool1', 'tool2'],
    office_catalog_count: 3,
    office_installed_count: 2,
    office_installed_ids: ['pack1', 'pack2'],
    missing_office_pack_ids: ['pack3'],
    office_ready: true,
    runtime_missing_pack_ids: [],
  }),
}))

import { fetchEmployeePlannerStatus } from '@/utils/platformShellApi'

describe('useOfficeEmployeePackReady', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('initializes with default status', () => {
    const { status, loading, ready, toolCount } = useOfficeEmployeePackReady()
    expect(status.value.office_ready).toBe(false)
    expect(loading.value).toBe(false)
    expect(ready.value).toBe(false)
    expect(toolCount.value).toBe(0)
  })

  it('refresh fetches and updates status', async () => {
    const { refresh, status, ready } = useOfficeEmployeePackReady()
    await refresh(true)
    expect(fetchEmployeePlannerStatus).toHaveBeenCalledWith(true)
    expect(status.value.office_ready).toBe(true)
    expect(ready.value).toBe(true)
  })

  it('refresh sets loading during request', async () => {
    let resolvePromise!: (v: any) => void
    ;(fetchEmployeePlannerStatus as any).mockImplementation(() => new Promise(r => { resolvePromise = r }))
    const { refresh, loading } = useOfficeEmployeePackReady()
    const promise = refresh(true)
    expect(loading.value).toBe(true)
    resolvePromise({ office_ready: false, missing_office_pack_ids: [] })
    await promise
    expect(loading.value).toBe(false)
  })

  it('refresh handles errors gracefully', async () => {
    ;(fetchEmployeePlannerStatus as any).mockRejectedValue(new Error('Network error'))
    const { refresh, loading } = useOfficeEmployeePackReady()
    await refresh(true)
    expect(loading.value).toBe(false)
  })

  it('startPolling sets up interval', () => {
    vi.useFakeTimers()
    const { startPolling } = useOfficeEmployeePackReady()
    startPolling(1500)
    vi.advanceTimersByTime(3000)
    expect(fetchEmployeePlannerStatus).toHaveBeenCalled()
    vi.useRealTimers()
  })

  it('startPolling does not start with non-positive interval', () => {
    const { startPolling } = useOfficeEmployeePackReady()
    startPolling(0)
    // Should not throw or set up polling
  })

  it('stopPolling clears interval', () => {
    vi.useFakeTimers()
    const { startPolling, stopPolling } = useOfficeEmployeePackReady()
    startPolling(1500)
    stopPolling()
    const callsBefore = (fetchEmployeePlannerStatus as any).mock.calls.length
    vi.advanceTimersByTime(5000)
    // No additional calls from polling after stop
    expect((fetchEmployeePlannerStatus as any).mock.calls.length).toBe(callsBefore)
    vi.useRealTimers()
  })

  it('missingIds returns array', () => {
    const { missingIds } = useOfficeEmployeePackReady()
    expect(Array.isArray(missingIds.value)).toBe(true)
  })

  it('toolCount returns number', () => {
    const { toolCount } = useOfficeEmployeePackReady()
    expect(typeof toolCount.value).toBe('number')
  })

  it('starts polling when pollMs > 0', async () => {
    vi.useFakeTimers()
    const { ready } = useOfficeEmployeePackReady(1500)
    // Wait for initial refresh
    await vi.advanceTimersByTimeAsync(100)
    expect(fetchEmployeePlannerStatus).toHaveBeenCalled()
    vi.useRealTimers()
  })
})
