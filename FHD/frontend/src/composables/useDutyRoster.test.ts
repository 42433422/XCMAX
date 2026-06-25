import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const getDutyRosterMock = vi.fn()
vi.mock('@/api/system', () => ({
  systemApi: {
    getDutyRoster: (...args: unknown[]) => getDutyRosterMock(...args),
  },
}))

// useDutyRoster 使用模块级单例 state，需在每个测试前重置模块
let useDutyRoster: typeof import('./useDutyRoster')['useDutyRoster']

describe('useDutyRoster', () => {
  beforeEach(async () => {
    setActivePinia(createPinia())
    getDutyRosterMock.mockReset()
    // 重置模块级单例 state
    vi.resetModules()
    const mod = await import('./useDutyRoster')
    useDutyRoster = mod.useDutyRoster
  })

  it('returns expected API shape', () => {
    const roster = useDutyRoster()
    expect(typeof roster.areas.value).toBe('object')
    expect(roster.allPlannedIds.value instanceof Set).toBe(true)
    expect(typeof roster.employeeLabels.value).toBe('object')
    expect(typeof roster.employeeDescriptions.value).toBe('object')
    expect(typeof roster.departments.value).toBe('object')
    expect(roster.loading.value).toBe(false)
    expect(roster.error.value).toBeNull()
    expect(typeof roster.refresh).toBe('function')
    expect(typeof roster.ensureLoaded).toBe('function')
  })

  it('returns fallback areas when no data loaded', () => {
    const roster = useDutyRoster()
    const areas = roster.areas.value
    expect(Object.keys(areas).length).toBeGreaterThan(0)
  })

  it('returns fallback allPlannedIds when no data loaded', () => {
    const roster = useDutyRoster()
    expect(roster.allPlannedIds.value.size).toBeGreaterThan(0)
  })

  it('ensureLoaded fetches duty roster from API', async () => {
    const sampleData = {
      areas: { 'test-area': { label: '测试', ids: ['emp-1'] } },
      departments: { dept: { id: 1 } },
      employee_labels: { 'emp-1': '员工1' },
      employee_descriptions: { 'emp-1': '描述1' },
      all_planned_ids: ['emp-1'],
      schema_version: 1,
    }
    getDutyRosterMock.mockResolvedValue({ data: sampleData })
    const roster = useDutyRoster()
    await roster.ensureLoaded()
    expect(getDutyRosterMock).toHaveBeenCalled()
    expect(roster.areas.value).toEqual(sampleData.areas)
    expect(roster.allPlannedIds.value).toEqual(new Set(['emp-1']))
    expect(roster.employeeLabels.value).toEqual(sampleData.employee_labels)
    expect(roster.employeeDescriptions.value).toEqual(sampleData.employee_descriptions)
    expect(roster.departments.value).toEqual(sampleData.departments)
    expect(roster.loading.value).toBe(false)
    expect(roster.error.value).toBeNull()
  })

  it('ensureLoaded handles API error and keeps fallback', async () => {
    getDutyRosterMock.mockRejectedValue(new Error('network'))
    const roster = useDutyRoster()
    await roster.ensureLoaded()
    expect(roster.loading.value).toBe(false)
    expect(roster.error.value).toBeInstanceOf(Error)
    expect(roster.error.value?.message).toBe('network')
    // fallback 数据仍可用
    expect(Object.keys(roster.areas.value).length).toBeGreaterThan(0)
  })

  it('ensureLoaded handles non-Error rejection', async () => {
    getDutyRosterMock.mockRejectedValue('string error')
    const roster = useDutyRoster()
    await roster.ensureLoaded()
    expect(roster.error.value).toBeInstanceOf(Error)
  })

  it('refresh forces a new fetch even when data exists', async () => {
    const data1 = {
      areas: { a: { label: 'A', ids: ['1'] } },
      departments: {},
      employee_labels: {},
      employee_descriptions: {},
      all_planned_ids: ['1'],
      schema_version: 1,
    }
    const data2 = { ...data1, all_planned_ids: ['1', '2'] }
    getDutyRosterMock.mockResolvedValueOnce({ data: data1 })
    getDutyRosterMock.mockResolvedValueOnce({ data: data2 })
    const roster = useDutyRoster()
    await roster.ensureLoaded()
    expect(roster.allPlannedIds.value).toEqual(new Set(['1']))
    await roster.refresh()
    expect(roster.allPlannedIds.value).toEqual(new Set(['1', '2']))
  })

  it('ensureLoaded returns cached data without refetch', async () => {
    const data = {
      areas: { a: { label: 'A', ids: ['1'] } },
      departments: {},
      employee_labels: {},
      employee_descriptions: {},
      all_planned_ids: ['1'],
      schema_version: 1,
    }
    getDutyRosterMock.mockResolvedValue({ data })
    const roster = useDutyRoster()
    await roster.ensureLoaded()
    const callCountAfterFirst = getDutyRosterMock.mock.calls.length
    await roster.ensureLoaded()
    expect(getDutyRosterMock.mock.calls.length).toBe(callCountAfterFirst)
  })

  it('handles response without data field', async () => {
    getDutyRosterMock.mockResolvedValue({})
    const roster = useDutyRoster()
    await roster.ensureLoaded()
    expect(roster.error.value).toBeNull()
    // fallback 仍可用
    expect(Object.keys(roster.areas.value).length).toBeGreaterThan(0)
  })

  it('handles response with empty all_planned_ids', async () => {
    const data = {
      areas: {},
      departments: {},
      employee_labels: {},
      employee_descriptions: {},
      all_planned_ids: [],
      schema_version: 1,
    }
    getDutyRosterMock.mockResolvedValue({ data })
    const roster = useDutyRoster()
    await roster.ensureLoaded()
    // 空 all_planned_ids 时回退到 FALLBACK_IDS
    expect(roster.allPlannedIds.value.size).toBeGreaterThan(0)
  })

  it('ensureLoaded reuses in-flight promise', async () => {
    const data = {
      areas: { a: { label: 'A', ids: ['1'] } },
      departments: {},
      employee_labels: {},
      employee_descriptions: {},
      all_planned_ids: ['1'],
      schema_version: 1,
    }
    getDutyRosterMock.mockResolvedValue({ data })
    const roster = useDutyRoster()
    // 同时发起两个 ensureLoaded，应复用同一 promise
    const p1 = roster.ensureLoaded()
    const p2 = roster.ensureLoaded()
    await Promise.all([p1, p2])
    expect(getDutyRosterMock).toHaveBeenCalledTimes(1)
  })
})
