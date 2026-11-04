import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const adminDutyGraphHealthMock = vi.fn()
vi.mock('@/api/xcmaxMarketProxy', () => ({
  default: {
    adminDutyGraphHealth: (...args: unknown[]) => adminDutyGraphHealthMock(...args),
  },
}))

import { useDutyRosterLoopStatus, normalizeDutyRosterLoopStatus } from './useDutyRosterLoopStatus'

describe('normalizeDutyRosterLoopStatus', () => {
  it('does not manufacture installed packages when inventory is absent', () => {
    const status = normalizeDutyRosterLoopStatus({ ok: true, staffing: { planned_count: 10 } })
    expect(status.localKnown).toBe(false)
    expect(status.catalogKnown).toBe(false)
    expect(status.localInstalledCount).toBe(0)
    expect(status.catalogRegisteredCount).toBe(0)
    expect(normalizeDutyRosterLoopStatus({ ok: false, success: true }).ok).toBe(false)
  })

  it('reads the operations fallback inventory and deduplicates package IDs', () => {
    const status = normalizeDutyRosterLoopStatus({ success: true, staffing: { planned_count: 5, missing_employees: [] }, missing_local_employee_packs: ['e1', ' e1 '], extra_local_employee_pack_ids: ['extra'] })
    expect(status.localKnown).toBe(true)
    expect(status.missingLocalIds).toEqual(['e1'])
    expect(status.localInstalledCount).toBe(4)
    expect(status.extraIds).toEqual(['extra'])
  })

  it('uses the complete local inventory even when the catalog also has a gap', () => {
    const status = normalizeDutyRosterLoopStatus({ success: true, planned_employee_ids: ['e1', 'e2', 'e3'], local_employee_pack_ids: ['e3'], staffing: { planned_count: 3, missing_employees: ['e2'] }, missing_local_employee_packs: ['e1'] })
    expect(status.missingLocalIds).toEqual(['e1', 'e2'])
    expect(status.localInstalledCount).toBe(1)
    expect(normalizeDutyRosterLoopStatus({ ok: true, staffing: { missing_employees: [null], missing_local_employee_packs: 'unknown' } }).catalogKnown).toBe(false)
  })

  it('returns empty status for null payload', () => {
    const s = normalizeDutyRosterLoopStatus(null)
    expect(s.ok).toBe(false)
    expect(s.source).toBe('unknown')
    expect(s.missingCatalogIds).toEqual([])
    expect(s.missingLocalIds).toEqual([])
    expect(s.extraIds).toEqual([])
    expect(s.schedulerRunning).toBeNull()
    expect(s.checkedAt).toBeGreaterThan(0)
    expect(s.message).toBe('')
  })

  it('returns empty status for undefined payload', () => {
    const s = normalizeDutyRosterLoopStatus(undefined)
    expect(s.ok).toBe(false)
    expect(s.source).toBe('unknown')
  })

  it('returns empty status for non-object payload', () => {
    const s = normalizeDutyRosterLoopStatus('not-an-object' as never)
    expect(s.ok).toBe(false)
    expect(s.source).toBe('unknown')
  })

  it('parses staffing block correctly', () => {
    const payload = {
      ok: true,
      source: 'api',
      staffing: {
        planned_count: 10,
        registered_count: 8,
        local_installed_count: 9,
        missing_employees: ['emp-1', 'emp-2'],
        missing_local_employee_packs: ['emp-3'],
        extra_employees: ['emp-99'],
      },
    }
    const s = normalizeDutyRosterLoopStatus(payload)
    expect(s.ok).toBe(true)
    expect(s.source).toBe('api')
    expect(s.plannedCount).toBe(10)
    expect(s.catalogRegisteredCount).toBe(8)
    expect(s.localInstalledCount).toBe(9)
    expect(s.missingCatalogIds).toEqual(['emp-1', 'emp-2'])
    expect(s.missingLocalIds).toEqual(['emp-3'])
    expect(s.extraIds).toEqual(['emp-99'])
    expect(s.missingCatalogCount).toBe(2)
    expect(s.missingLocalCount).toBe(1)
    expect(s.extraCount).toBe(1)
  })

  it('uses fallback planned count when missing', () => {
    const s = normalizeDutyRosterLoopStatus({})
    // plannedFallback = ALL_PLANNED_YUANGON_PKG_IDS.size
    expect(s.plannedCount).toBeGreaterThan(0)
  })

  it('computes catalogRegisteredCount fallback from planned - missing', () => {
    const payload = {
      staffing: {
        planned_count: 10,
        missing_employees: ['a', 'b'],
      },
    }
    const s = normalizeDutyRosterLoopStatus(payload)
    expect(s.catalogRegisteredCount).toBe(8) // 10 - 2
  })

  it('computes localInstalledCount fallback from planned - missing local', () => {
    const payload = {
      staffing: {
        planned_count: 10,
        missing_local_employee_packs: ['x'],
      },
    }
    const s = normalizeDutyRosterLoopStatus(payload)
    expect(s.localInstalledCount).toBe(9) // 10 - 1
  })

  it('catalogRegisteredCount fallback clamps to 0', () => {
    const payload = {
      staffing: {
        planned_count: 2,
        missing_employees: ['a', 'b', 'c', 'd'],
      },
    }
    const s = normalizeDutyRosterLoopStatus(payload)
    expect(s.catalogRegisteredCount).toBe(0) // Math.max(0, 2 - 4)
  })

  it('ok is false when health.ok is explicitly false', () => {
    const s = normalizeDutyRosterLoopStatus({ ok: false })
    expect(s.ok).toBe(false)
  })

  it('ok is false when no explicit healthy field is present', () => {
    const s = normalizeDutyRosterLoopStatus({})
    expect(s.ok).toBe(false)
  })

  it('accepts explicit success and healthy compatibility fields', () => {
    expect(normalizeDutyRosterLoopStatus({ success: true }).ok).toBe(true)
    expect(normalizeDutyRosterLoopStatus({ healthy: true }).ok).toBe(true)
  })

  it('source falls back to unknown when empty', () => {
    const s = normalizeDutyRosterLoopStatus({ source: '' })
    expect(s.source).toBe('unknown')
  })

  it('source falls back to unknown when whitespace', () => {
    const s = normalizeDutyRosterLoopStatus({ source: '   ' })
    expect(s.source).toBe('unknown')
  })

  it('message prefers staffing.error over health.message', () => {
    const s = normalizeDutyRosterLoopStatus({
      message: 'top message',
      staffing: { error: 'staffing error' },
    })
    expect(s.message).toBe('staffing error')
  })

  it('message uses health.message when no staffing.error', () => {
    const s = normalizeDutyRosterLoopStatus({
      message: 'top message',
    })
    expect(s.message).toBe('top message')
  })

  it('message is empty when neither staffing.error nor health.message', () => {
    const s = normalizeDutyRosterLoopStatus({})
    expect(s.message).toBe('')
  })

  it('schedulerRunning is true when scheduler.running is true', () => {
    const s = normalizeDutyRosterLoopStatus({
      scheduler: { running: true },
    })
    expect(s.schedulerRunning).toBe(true)
  })

  it('schedulerRunning is true when scheduler.started is true', () => {
    const s = normalizeDutyRosterLoopStatus({
      scheduler: { started: true },
    })
    expect(s.schedulerRunning).toBe(true)
  })

  it('schedulerRunning is null when scheduler.running is not boolean', () => {
    const s = normalizeDutyRosterLoopStatus({
      scheduler: { running: 'yes' },
    })
    expect(s.schedulerRunning).toBeNull()
  })

  it('schedulerRunning is null when no scheduler block', () => {
    const s = normalizeDutyRosterLoopStatus({})
    expect(s.schedulerRunning).toBeNull()
  })

  it('schedulerJobCount from employee_cron_jobs', () => {
    const s = normalizeDutyRosterLoopStatus({
      employee_cron_jobs: [{ id: 1 }, { id: 2 }],
    })
    expect(s.schedulerJobCount).toBe(2)
  })

  it('schedulerJobCount from scheduler.jobs when no employee_cron_jobs', () => {
    const s = normalizeDutyRosterLoopStatus({
      scheduler: { jobs: [{ id: 1 }] },
    })
    expect(s.schedulerJobCount).toBe(1)
  })

  it('schedulerJobCount is 0 when neither exists', () => {
    const s = normalizeDutyRosterLoopStatus({})
    expect(s.schedulerJobCount).toBe(0)
  })

  it('extraIds from staffing.extra_employees', () => {
    const s = normalizeDutyRosterLoopStatus({
      staffing: { extra_employees: ['a', 'b'] },
    })
    expect(s.extraIds).toEqual(['a', 'b'])
  })

  it('extraIds falls back to health.extra_local_employee_pack_ids', () => {
    const s = normalizeDutyRosterLoopStatus({
      extra_local_employee_pack_ids: ['x', 'y'],
    })
    expect(s.extraIds).toEqual(['x', 'y'])
  })

  it('stringArray filters falsy and trims values', () => {
    const s = normalizeDutyRosterLoopStatus({
      staffing: {
        missing_employees: ['  a  ', '', null, 'b', undefined, '  '],
      },
    })
    expect(s.missingCatalogIds).toEqual(['a', 'b'])
  })

  it('numberValue returns fallback for non-finite', () => {
    const s = normalizeDutyRosterLoopStatus({
      staffing: {
        planned_count: 'not-a-number',
      },
    })
    expect(s.plannedCount).toBeGreaterThan(0) // fallback
  })

  it('handles employee_scheduler alias for scheduler', () => {
    const s = normalizeDutyRosterLoopStatus({
      employee_scheduler: { running: true, jobs: [{ id: 1 }] },
    })
    expect(s.schedulerRunning).toBe(true)
    expect(s.schedulerJobCount).toBe(1)
  })

  it('planned_local_installed_count takes precedence over staffing.local_installed_count', () => {
    const s = normalizeDutyRosterLoopStatus({
      planned_local_installed_count: 7,
      staffing: {
        planned_count: 10,
        local_installed_count: 9,
      },
    })
    expect(s.localInstalledCount).toBe(7)
  })

  it('registered_count takes precedence over fallback', () => {
    const s = normalizeDutyRosterLoopStatus({
      staffing: {
        planned_count: 10,
        registered_count: 5,
        missing_employees: ['a'],
      },
    })
    expect(s.catalogRegisteredCount).toBe(5)
  })

  it('planned_count from health.planned_count when staffing.planned_count missing', () => {
    const s = normalizeDutyRosterLoopStatus({
      planned_count: 15,
    })
    expect(s.plannedCount).toBe(15)
  })

  it('registered_count from health.registered_count when staffing.registered_count missing', () => {
    const s = normalizeDutyRosterLoopStatus({
      registered_count: 6,
    })
    expect(s.catalogRegisteredCount).toBe(6)
  })
})

describe('useDutyRosterLoopStatus', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    adminDutyGraphHealthMock.mockReset()
  })

  it('returns expected API shape', () => {
    const hook = useDutyRosterLoopStatus()
    expect(hook.status).toBeDefined()
    expect(hook.loading).toBeDefined()
    expect(hook.error).toBeDefined()
    expect(hook.ready).toBeDefined()
    expect(hook.healthLabel).toBeDefined()
    expect(hook.detailLine).toBeDefined()
    expect(typeof hook.refresh).toBe('function')
  })

  it('initializes with empty status', () => {
    const hook = useDutyRosterLoopStatus()
    expect(hook.status.value.ok).toBe(false)
    expect(hook.status.value.source).toBe('loading')
    expect(hook.loading.value).toBe(false)
    expect(hook.error.value).toBe('')
  })

  it('keeps initial package inventory unverified', () => {
    const hook = useDutyRosterLoopStatus()
    expect(hook.healthLabel.value).toBe('待核实')
  })

  it('healthLabel is 读取中 when loading and no checkedAt', () => {
    const hook = useDutyRosterLoopStatus()
    // 模拟 loading 状态
    hook.loading.value = true
    expect(hook.healthLabel.value).toBe('读取中')
  })

  it('ready is false initially', () => {
    const hook = useDutyRosterLoopStatus()
    expect(hook.ready.value).toBe(false)
  })

  it('invalidates stale inventory after a failed refresh and rejects incomplete healthy replies', async () => {
    adminDutyGraphHealthMock.mockResolvedValueOnce({ ok: true, staffing: { planned_count: 2, missing_employees: [], missing_local_employee_packs: [] } })
    const hook = useDutyRosterLoopStatus()
    await hook.refresh()
    expect(hook.ready.value).toBe(true)
    adminDutyGraphHealthMock.mockRejectedValueOnce(new Error('读取失败'))
    await hook.refresh()
    expect(hook.status.value.localKnown).toBe(false)
    expect(hook.ready.value).toBe(false)
    adminDutyGraphHealthMock.mockResolvedValueOnce({ ok: true })
    await hook.refresh()
    expect(hook.ready.value).toBe(false)
    expect(hook.detailLine.value).toContain('待核实')
  })

  it('refresh fetches health and updates status', async () => {
    const payload = {
      ok: true,
      source: 'api',
      staffing: {
        planned_count: 5,
        registered_count: 5,
        local_installed_count: 5,
        missing_employees: [],
        missing_local_employee_packs: [],
      },
    }
    adminDutyGraphHealthMock.mockResolvedValue(payload)
    const hook = useDutyRosterLoopStatus()
    await hook.refresh()
    expect(adminDutyGraphHealthMock).toHaveBeenCalled()
    expect(hook.status.value.ok).toBe(true)
    expect(hook.status.value.source).toBe('api')
    expect(hook.status.value.plannedCount).toBe(5)
    expect(hook.loading.value).toBe(false)
    expect(hook.error.value).toBe('')
  })

  it('refresh handles API error', async () => {
    adminDutyGraphHealthMock.mockRejectedValue(new Error('network down'))
    const hook = useDutyRosterLoopStatus()
    await hook.refresh()
    expect(hook.error.value).toBe('network down')
    expect(hook.loading.value).toBe(false)
    expect(hook.status.value.ok).toBe(false)
    expect(hook.status.value.message).toBe('network down')
  })

  it('refresh handles non-Error rejection', async () => {
    adminDutyGraphHealthMock.mockRejectedValue('string error')
    const hook = useDutyRosterLoopStatus()
    await hook.refresh()
    expect(hook.error.value).toBe('string error')
    expect(hook.loading.value).toBe(false)
  })

  it('ready is true when ok and no missing', async () => {
    const payload = {
      ok: true,
      staffing: {
        planned_count: 5,
        registered_count: 5,
        local_installed_count: 5,
        missing_employees: [],
        missing_local_employee_packs: [],
      },
    }
    adminDutyGraphHealthMock.mockResolvedValue(payload)
    const hook = useDutyRosterLoopStatus()
    await hook.refresh()
    expect(hook.ready.value).toBe(true)
    expect(hook.healthLabel.value).toBe('编制包已对齐')
  })

  it('healthLabel is 本机缺包 when missingLocalCount > 0', async () => {
    const payload = {
      ok: true,
      staffing: {
        planned_count: 5,
        missing_local_employee_packs: ['emp-1'],
      },
    }
    adminDutyGraphHealthMock.mockResolvedValue(payload)
    const hook = useDutyRosterLoopStatus()
    await hook.refresh()
    expect(hook.healthLabel.value).toBe('本机缺包')
  })

  it('healthLabel is Catalog 缺岗 when missingCatalogCount > 0', async () => {
    const payload = {
      ok: true,
      staffing: {
        planned_count: 5,
        missing_employees: ['emp-1'],
      },
    }
    adminDutyGraphHealthMock.mockResolvedValue(payload)
    const hook = useDutyRosterLoopStatus()
    await hook.refresh()
    expect(hook.healthLabel.value).toBe('Catalog 缺岗')
  })

  it('does not infer package health from an empty failed response', async () => {
    const payload = { ok: false }
    adminDutyGraphHealthMock.mockResolvedValue(payload)
    const hook = useDutyRosterLoopStatus()
    await hook.refresh()
    expect(hook.healthLabel.value).toBe('待核实')
  })

  it('healthLabel is 接口异常 when error is set', async () => {
    adminDutyGraphHealthMock.mockRejectedValue(new Error('fail'))
    const hook = useDutyRosterLoopStatus()
    await hook.refresh()
    expect(hook.healthLabel.value).toBe('接口异常')
  })

  it('healthLabel is 待校验 when ok but not ready and no missing', async () => {
    const payload = {
      ok: true,
      staffing: {
        planned_count: 0, // plannedCount=0 → ready=false
      },
    }
    adminDutyGraphHealthMock.mockResolvedValue(payload)
    const hook = useDutyRosterLoopStatus()
    await hook.refresh()
    expect(hook.healthLabel.value).toBe('待核实')
  })

  it('detailLine returns error when set', async () => {
    adminDutyGraphHealthMock.mockRejectedValue(new Error('detail error'))
    const hook = useDutyRosterLoopStatus()
    await hook.refresh()
    expect(hook.detailLine.value).toBe('detail error')
  })

  it('detailLine returns status.message when set', async () => {
    const payload = {
      ok: true,
      message: 'custom message',
    }
    adminDutyGraphHealthMock.mockResolvedValue(payload)
    const hook = useDutyRosterLoopStatus()
    await hook.refresh()
    expect(hook.detailLine.value).toBe('custom message')
  })

  it('detailLine returns formatted line when no error and no message', async () => {
    const payload = {
      ok: true,
      staffing: {
        planned_count: 10,
        registered_count: 8,
        local_installed_count: 9,
        missing_employees: ['missing-a', 'missing-b'],
        missing_local_employee_packs: ['missing-c'],
      },
    }
    adminDutyGraphHealthMock.mockResolvedValue(payload)
    const hook = useDutyRosterLoopStatus()
    await hook.refresh()
    expect(hook.detailLine.value).toContain('10')
    expect(hook.detailLine.value).toContain('9')
    expect(hook.detailLine.value).toContain('8')
  })

  it('refresh clears error before fetching', async () => {
    adminDutyGraphHealthMock.mockRejectedValueOnce(new Error('first'))
    adminDutyGraphHealthMock.mockResolvedValueOnce({ ok: true })
    const hook = useDutyRosterLoopStatus()
    await hook.refresh()
    expect(hook.error.value).toBe('first')
    await hook.refresh()
    expect(hook.error.value).toBe('')
  })
})
