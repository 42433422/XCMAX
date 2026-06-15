import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/api/core', () => ({
  buildFullApiUrl: (path: string) => `http://localhost${path}`,
}))

vi.mock('@/utils/safeJsonRequest', () => ({
  safeJsonRequest: vi.fn().mockResolvedValue({ success: true, data: null }),
}))

vi.mock('@/utils/tenantStorageScope', () => ({
  buildTenantScopedStorageKey: (base: string) => base,
}))

vi.mock('@/constants/kittenVisualizationEmployees', () => ({
  KITTEN_VIZ_EMPLOYEES: [
    { pkgId: 'pack-alpha', label: 'Alpha', icon: 'A' },
    { pkgId: 'pack-beta', label: 'Beta', icon: 'B' },
    { pkgId: 'pack-gamma', label: 'Gamma', icon: 'G' },
  ],
}))

import { useKittenVizEmployees } from './useKittenVizEmployees'
import { safeJsonRequest } from '@/utils/safeJsonRequest'

describe('useKittenVizEmployees', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('returns composable API', () => {
    const composable = useKittenVizEmployees()
    expect(composable.employees).toBeDefined()
    expect(composable.selected).toBeDefined()
    expect(composable.selectedPkgId).toBeDefined()
    expect(composable.installedCount).toBeDefined()
    expect(composable.loading).toBeDefined()
    expect(typeof composable.refreshInstalled).toBe('function')
    expect(typeof composable.selectEmployee).toBe('function')
  })

  it('initializes with default selected package', () => {
    const composable = useKittenVizEmployees()
    expect(composable.selectedPkgId.value).toBe('pack-alpha')
  })

  it('reads stored package id from localStorage', () => {
    localStorage.setItem('xcagi_kitten_viz_employee_pkg', 'pack-beta')
    const composable = useKittenVizEmployees()
    expect(composable.selectedPkgId.value).toBe('pack-beta')
  })

  it('falls back to first package for invalid stored value', () => {
    localStorage.setItem('xcagi_kitten_viz_employee_pkg', 'invalid-pack')
    const composable = useKittenVizEmployees()
    expect(composable.selectedPkgId.value).toBe('pack-alpha')
  })

  it('employees returns list with installed status', () => {
    const composable = useKittenVizEmployees()
    expect(composable.employees.value).toHaveLength(3)
    expect(composable.employees.value[0]).toHaveProperty('installed')
  })

  it('selected returns the matching employee', () => {
    const composable = useKittenVizEmployees()
    expect(composable.selected.value.pkgId).toBe('pack-alpha')
  })

  it('selectEmployee changes selected package', () => {
    const composable = useKittenVizEmployees()
    composable.selectEmployee('pack-beta')
    expect(composable.selectedPkgId.value).toBe('pack-beta')
  })

  it('selectEmployee persists to localStorage', () => {
    const composable = useKittenVizEmployees()
    composable.selectEmployee('pack-gamma')
    expect(localStorage.getItem('xcagi_kitten_viz_employee_pkg')).toBe('pack-gamma')
  })

  it('selectEmployee ignores invalid package id', () => {
    const composable = useKittenVizEmployees()
    composable.selectEmployee('invalid-pack')
    expect(composable.selectedPkgId.value).toBe('pack-alpha')
  })

  it('refreshInstalled updates installed ids', async () => {
    vi.mocked(safeJsonRequest).mockResolvedValueOnce({
      success: true,
      data: {
        data: {
          office_installed: [{ pack_id: 'pack-alpha' }],
          other_installed: [{ pack_id: 'pack-gamma' }],
        },
      },
    })
    const composable = useKittenVizEmployees()
    await composable.refreshInstalled()
    expect(composable.installedCount.value).toBe(2)
    expect(composable.employees.value[0].installed).toBe(true)
    expect(composable.employees.value[1].installed).toBe(false)
    expect(composable.employees.value[2].installed).toBe(true)
  })

  it('refreshInstalled handles API error', async () => {
    vi.mocked(safeJsonRequest).mockRejectedValueOnce(new Error('Network error'))
    const composable = useKittenVizEmployees()
    await composable.refreshInstalled()
    expect(composable.installedCount.value).toBe(0)
    expect(composable.loading.value).toBe(false)
  })

  it('refreshInstalled sets loading state', async () => {
    let resolvePromise: (v: any) => void
    vi.mocked(safeJsonRequest).mockImplementationOnce(
      () => new Promise((resolve) => { resolvePromise = resolve })
    )
    const composable = useKittenVizEmployees()
    const promise = composable.refreshInstalled()
    expect(composable.loading.value).toBe(true)
    resolvePromise!({ success: true, data: null })
    await promise
    expect(composable.loading.value).toBe(false)
  })

  it('installedCount returns correct count', () => {
    const composable = useKittenVizEmployees()
    expect(composable.installedCount.value).toBe(0)
  })
})
