/**
 * workflowEmployeeOnboard.ts 覆盖率补齐测试
 * 重点覆盖：collectDeskEmployeeIdsFromCatalogItem 各分支、
 * autoOnboardInstalledMarketItem 全流程（employee_pack / 非 employee_pack / reload 失败 / 无 ids）、
 * autoOnboardWorkflowEmployeesForMod（deprecated 代理）、
 * autoOnboardWorkflowEmployeesFromMods（空/有员工/过滤）
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

// ── 可配置的 mock 函数（hoisted-safe，以 mock 开头）─────────
const mockReloadEmployeePacks = vi.fn()
const mockResolveEnterpriseModStack = vi.fn()
const mockDefaultHostModIdForMarketEmployee = vi.fn(() => 'host-mod-1')
const mockFilterModsForEnterpriseWorkflowRegistry = vi.fn((mods: unknown[]) => mods)
const mockFilterWorkflowRegistrySourceMods = vi.fn((mods: unknown[]) => mods)
const mockIsNonWorkflowDeskEmployeeId = vi.fn((id: string) => id === 'host_foundation')
const mockModsStoreRefresh = vi.fn(async () => {})
const mockModsStoreModsForUi = vi.fn(() => [])
const mockWfStoreRefreshRegistry = vi.fn(async () => {})
const mockWfStoreAssignHostMod = vi.fn()
const mockWfStoreEnableEmployees = vi.fn(() => [])

vi.mock('@/api/modStore', () => ({
  reloadEmployeePacks: (...a: unknown[]) => mockReloadEmployeePacks(...a),
}))

vi.mock('@/constants/enterpriseModStack', () => ({
  defaultHostModIdForMarketEmployee: (...a: unknown[]) =>
    mockDefaultHostModIdForMarketEmployee(...a),
  EnterpriseModStack: {},
}))

vi.mock('@/stores/mods', () => ({
  useModsStore: () => ({
    refresh: (...a: unknown[]) => mockModsStoreRefresh(...a),
    get modsForUi() {
      return mockModsStoreModsForUi()
    },
  }),
}))

vi.mock('@/stores/workflowAiEmployees', () => ({
  useWorkflowAiEmployeesStore: () => ({
    refreshRegistry: (...a: unknown[]) => mockWfStoreRefreshRegistry(...a),
    assignHostMod: (...a: unknown[]) => mockWfStoreAssignHostMod(...a),
    enableEmployees: (...a: unknown[]) => mockWfStoreEnableEmployees(...a),
  }),
}))

vi.mock('@/utils/enterpriseModStackApi', () => ({
  resolveEnterpriseModStack: (...a: unknown[]) => mockResolveEnterpriseModStack(...a),
}))

vi.mock('@/utils/workflowEmployeeScope', () => ({
  filterModsForEnterpriseWorkflowRegistry: (...a: unknown[]) =>
    mockFilterModsForEnterpriseWorkflowRegistry(...a),
}))

vi.mock('@/utils/modWorkflowEmployees', () => ({
  filterWorkflowRegistrySourceMods: (...a: unknown[]) =>
    mockFilterWorkflowRegistrySourceMods(...a),
  isNonWorkflowDeskEmployeeId: (id: string) => mockIsNonWorkflowDeskEmployeeId(id),
}))

import {
  collectDeskEmployeeIdsFromCatalogItem,
  autoOnboardInstalledMarketItem,
  autoOnboardWorkflowEmployeesForMod,
  autoOnboardWorkflowEmployeesFromMods,
  type MarketInstallCatalogItem,
} from './workflowEmployeeOnboard'

// ── 测试数据 ──────────────────────────────────────────────
const baseStack = {
  industryId: 'attendance',
  industryModId: 'attendance-industry',
  industryLabel: '考勤',
  customModIds: [],
  customLabels: {},
  packageModIds: ['attendance-industry'],
  hostLineModIds: ['xcagi-planner-bridge'],
  stackLabel: '考勤',
  stackShortLabel: '考勤',
}

describe('workflowEmployeeOnboard – 覆盖率补齐', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockReloadEmployeePacks.mockResolvedValue(undefined)
    mockResolveEnterpriseModStack.mockResolvedValue(baseStack)
    mockDefaultHostModIdForMarketEmployee.mockReturnValue('attendance-industry')
    mockFilterModsForEnterpriseWorkflowRegistry.mockImplementation((mods: unknown[]) => mods || [])
    mockFilterWorkflowRegistrySourceMods.mockImplementation((mods: unknown[]) => mods || [])
    mockIsNonWorkflowDeskEmployeeId.mockImplementation((id: string) => id === 'host_foundation')
    mockModsStoreRefresh.mockResolvedValue(undefined)
    mockModsStoreModsForUi.mockReturnValue([])
    mockWfStoreRefreshRegistry.mockResolvedValue(undefined)
    mockWfStoreAssignHostMod.mockImplementation(() => {})
    mockWfStoreEnableEmployees.mockReturnValue([])
  })

  // ═══════════════════════════════════════════════════════════
  // 1. collectDeskEmployeeIdsFromCatalogItem
  // ═══════════════════════════════════════════════════════════
  describe('collectDeskEmployeeIdsFromCatalogItem', () => {
    it('undefined item 返回空数组', () => {
      expect(collectDeskEmployeeIdsFromCatalogItem(undefined)).toEqual([])
    })

    it('null item 返回空数组', () => {
      expect(collectDeskEmployeeIdsFromCatalogItem(null as unknown as undefined)).toEqual([])
    })

    it('无 workflow_employees 和 employee 时返回空数组', () => {
      const item: MarketInstallCatalogItem = { id: 'pkg1' }
      expect(collectDeskEmployeeIdsFromCatalogItem(item)).toEqual([])
    })

    it('workflow_employees 优先于 employee.id', () => {
      const item: MarketInstallCatalogItem = {
        id: 'pkg1',
        workflow_employees: [
          { id: 'wf-1', label: 'WF1' },
          { id: 'wf-2', label: 'WF2' },
        ],
        employee: { id: 'emp-1', label: 'EMP1' },
      }
      expect(collectDeskEmployeeIdsFromCatalogItem(item)).toEqual(['wf-1', 'wf-2'])
    })

    it('workflow_employees 为空数组时回退到 employee.id', () => {
      const item: MarketInstallCatalogItem = {
        id: 'pkg1',
        workflow_employees: [],
        employee: { id: 'emp-1', label: 'EMP1' },
      }
      expect(collectDeskEmployeeIdsFromCatalogItem(item)).toEqual(['emp-1'])
    })

    it('workflow_employees 含非工作流工位员工时被过滤', () => {
      mockIsNonWorkflowDeskEmployeeId.mockImplementation((id: string) =>
        id === 'host_foundation' || id === 'placeholder',
      )
      const item: MarketInstallCatalogItem = {
        id: 'pkg1',
        workflow_employees: [
          { id: 'wf-1', label: 'WF1' },
          { id: 'host_foundation', label: 'Host' },
          { id: 'placeholder', label: 'PH' },
          { id: 'wf-2', label: 'WF2' },
        ],
      }
      expect(collectDeskEmployeeIdsFromCatalogItem(item)).toEqual(['wf-1', 'wf-2'])
    })

    it('workflow_employees 全部被过滤时回退到 employee.id', () => {
      mockIsNonWorkflowDeskEmployeeId.mockImplementation((id: string) =>
        id === 'host_foundation',
      )
      const item: MarketInstallCatalogItem = {
        id: 'pkg1',
        workflow_employees: [{ id: 'host_foundation', label: 'Host' }],
        employee: { id: 'emp-1', label: 'EMP1' },
      }
      expect(collectDeskEmployeeIdsFromCatalogItem(item)).toEqual(['emp-1'])
    })

    it('employee.id 为非工作流工位员工时返回空数组', () => {
      mockIsNonWorkflowDeskEmployeeId.mockImplementation((id: string) => id === 'host_foundation')
      const item: MarketInstallCatalogItem = {
        id: 'pkg1',
        employee: { id: 'host_foundation', label: 'Host' },
      }
      expect(collectDeskEmployeeIdsFromCatalogItem(item)).toEqual([])
    })

    it('workflow_employees 中 id 为空字符串时被跳过', () => {
      const item: MarketInstallCatalogItem = {
        id: 'pkg1',
        workflow_employees: [
          { id: '', label: 'Empty' },
          { id: '  ', label: 'Whitespace' },
          { id: 'wf-1', label: 'WF1' },
        ],
      }
      expect(collectDeskEmployeeIdsFromCatalogItem(item)).toEqual(['wf-1'])
    })

    it('employee.id 为空字符串时回退到空数组', () => {
      const item: MarketInstallCatalogItem = {
        id: 'pkg1',
        employee: { id: '', label: 'Empty' },
      }
      expect(collectDeskEmployeeIdsFromCatalogItem(item)).toEqual([])
    })

    it('employee.id 为空白字符串时回退到空数组', () => {
      const item: MarketInstallCatalogItem = {
        id: 'pkg1',
        employee: { id: '   ', label: 'Whitespace' },
      }
      expect(collectDeskEmployeeIdsFromCatalogItem(item)).toEqual([])
    })

    it('workflow_employees 元素 id 为 null/undefined 时被跳过', () => {
      const item: MarketInstallCatalogItem = {
        id: 'pkg1',
        workflow_employees: [
          { id: undefined as unknown as string, label: 'Undef' },
          { id: null as unknown as string, label: 'Null' },
          { id: 'wf-1', label: 'WF1' },
        ],
      }
      expect(collectDeskEmployeeIdsFromCatalogItem(item)).toEqual(['wf-1'])
    })

    it('employee 字段为 undefined 时回退到空数组', () => {
      const item: MarketInstallCatalogItem = {
        id: 'pkg1',
        employee: undefined,
      }
      expect(collectDeskEmployeeIdsFromCatalogItem(item)).toEqual([])
    })
  })

  // ═══════════════════════════════════════════════════════════
  // 2. autoOnboardInstalledMarketItem
  // ═══════════════════════════════════════════════════════════
  describe('autoOnboardInstalledMarketItem', () => {
    it('employee_pack 制品成功 reload 并返回结果', async () => {
      const item: MarketInstallCatalogItem = {
        id: 'pkg1',
        pkg_id: 'pkg1',
        artifact: 'employee_pack',
        workflow_employees: [{ id: 'wf-1', label: 'WF1' }],
      }
      mockWfStoreEnableEmployees.mockReturnValue(['wf-1'])

      const result = await autoOnboardInstalledMarketItem(item)

      expect(mockReloadEmployeePacks).toHaveBeenCalled()
      expect(result.plannerRefreshed).toBe(true)
      expect(result.onboardedIds).toEqual(['wf-1'])
      expect(result.enterpriseStackLabel).toBe('考勤')
      expect(result.hostModId).toBe('attendance-industry')
    })

    it('非 employee_pack 制品不触发 reload', async () => {
      const item: MarketInstallCatalogItem = {
        id: 'pkg1',
        pkg_id: 'pkg1',
        artifact: 'mod_pack',
        workflow_employees: [{ id: 'wf-1', label: 'WF1' }],
      }

      const result = await autoOnboardInstalledMarketItem(item)

      expect(mockReloadEmployeePacks).not.toHaveBeenCalled()
      expect(result.plannerRefreshed).toBe(false)
    })

    it('artifact 字段缺失时不触发 reload', async () => {
      const item: MarketInstallCatalogItem = {
        id: 'pkg1',
        pkg_id: 'pkg1',
        workflow_employees: [{ id: 'wf-1', label: 'WF1' }],
      }

      const result = await autoOnboardInstalledMarketItem(item)

      expect(mockReloadEmployeePacks).not.toHaveBeenCalled()
      expect(result.plannerRefreshed).toBe(false)
    })

    it('artifact 为大写 EMPLOYEE_PACK 仍识别为 employee_pack', async () => {
      const item: MarketInstallCatalogItem = {
        id: 'pkg1',
        pkg_id: 'pkg1',
        artifact: 'EMPLOYEE_PACK',
        workflow_employees: [{ id: 'wf-1', label: 'WF1' }],
      }

      await autoOnboardInstalledMarketItem(item)

      expect(mockReloadEmployeePacks).toHaveBeenCalled()
    })

    it('artifact 含空白仍识别为 employee_pack', async () => {
      const item: MarketInstallCatalogItem = {
        id: 'pkg1',
        pkg_id: 'pkg1',
        artifact: '  Employee_Pack  ',
        workflow_employees: [{ id: 'wf-1', label: 'WF1' }],
      }

      await autoOnboardInstalledMarketItem(item)

      expect(mockReloadEmployeePacks).toHaveBeenCalled()
    })

    it('reloadEmployeePacks 失败时 plannerRefreshed=false 不抛错', async () => {
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
      mockReloadEmployeePacks.mockRejectedValue(new Error('network error'))
      const item: MarketInstallCatalogItem = {
        id: 'pkg1',
        pkg_id: 'pkg1',
        artifact: 'employee_pack',
        workflow_employees: [{ id: 'wf-1', label: 'WF1' }],
      }

      const result = await autoOnboardInstalledMarketItem(item)

      expect(result.plannerRefreshed).toBe(false)
      expect(warnSpy).toHaveBeenCalledWith(
        '[workflowEmployeeOnboard] reloadEmployeePacks failed:',
        expect.any(Error),
      )
      warnSpy.mockRestore()
    })

    it('无 ids 时不调用 assignHostMod 且 onboardedIds 为空', async () => {
      const item: MarketInstallCatalogItem = {
        id: 'pkg1',
        pkg_id: 'pkg1',
        artifact: 'mod_pack',
        // 无 workflow_employees 和 employee
      }

      const result = await autoOnboardInstalledMarketItem(item)

      expect(mockWfStoreAssignHostMod).not.toHaveBeenCalled()
      expect(result.onboardedIds).toEqual([])
    })

    it('有 ids 时调用 assignHostMod 和 enableEmployees', async () => {
      const item: MarketInstallCatalogItem = {
        id: 'pkg1',
        pkg_id: 'pkg1',
        artifact: 'mod_pack',
        workflow_employees: [
          { id: 'wf-1', label: 'WF1' },
          { id: 'wf-2', label: 'WF2' },
        ],
      }
      mockWfStoreEnableEmployees.mockReturnValue(['wf-1', 'wf-2'])

      const result = await autoOnboardInstalledMarketItem(item)

      expect(mockWfStoreAssignHostMod).toHaveBeenCalledWith(
        ['wf-1', 'wf-2'],
        'attendance-industry',
      )
      expect(mockWfStoreEnableEmployees).toHaveBeenCalledWith(['wf-1', 'wf-2'], {
        onlyNew: false,
      })
      expect(result.onboardedIds).toEqual(['wf-1', 'wf-2'])
    })

    it('通过 mod manifest 收集额外员工 id 并去重', async () => {
      const modWithEmployees = {
        id: 'pkg1',
        pkg_id: 'pkg1',
        workflow_employees: [{ id: 'wf-3', label: 'WF3' }],
      }
      mockModsStoreModsForUi.mockReturnValue([modWithEmployees])
      const item: MarketInstallCatalogItem = {
        id: 'pkg1',
        pkg_id: 'pkg1',
        artifact: 'mod_pack',
        workflow_employees: [{ id: 'wf-1', label: 'WF1' }],
      }
      mockWfStoreEnableEmployees.mockReturnValue(['wf-1', 'wf-3'])

      const result = await autoOnboardInstalledMarketItem(item)

      // wf-1 来自 catalogItem，wf-3 来自 mod，去重后传入 enableEmployees
      expect(mockWfStoreAssignHostMod).toHaveBeenCalledWith(
        expect.arrayContaining(['wf-1', 'wf-3']),
        'attendance-industry',
      )
      expect(result.onboardedIds).toEqual(['wf-1', 'wf-3'])
    })

    it('catalogItem 与 mod 有相同 id 时去重', async () => {
      const modWithEmployees = {
        id: 'pkg1',
        pkg_id: 'pkg1',
        workflow_employees: [{ id: 'wf-1', label: 'WF1' }],
      }
      mockModsStoreModsForUi.mockReturnValue([modWithEmployees])
      const item: MarketInstallCatalogItem = {
        id: 'pkg1',
        pkg_id: 'pkg1',
        artifact: 'mod_pack',
        workflow_employees: [{ id: 'wf-1', label: 'WF1' }],
      }
      mockWfStoreEnableEmployees.mockReturnValue(['wf-1'])

      const result = await autoOnboardInstalledMarketItem(item)

      // 去重后只有一个 wf-1
      expect(mockWfStoreAssignHostMod).toHaveBeenCalledWith(['wf-1'], 'attendance-industry')
      expect(result.onboardedIds).toEqual(['wf-1'])
    })

    it('resolveInstalledMod 通过 id 匹配 mod', async () => {
      const modWithEmployees = {
        id: 'pkg1',
        workflow_employees: [{ id: 'wf-from-mod', label: 'Mod' }],
      }
      mockModsStoreModsForUi.mockReturnValue([modWithEmployees])
      const item: MarketInstallCatalogItem = {
        id: 'pkg1',
        // 无 pkg_id，使用 id
        artifact: 'mod_pack',
      }
      mockWfStoreEnableEmployees.mockReturnValue(['wf-from-mod'])

      const result = await autoOnboardInstalledMarketItem(item)

      expect(result.onboardedIds).toEqual(['wf-from-mod'])
    })

    it('resolveInstalledMod 通过 pkg_id 匹配 mod', async () => {
      const modWithEmployees = {
        id: 'different-id',
        pkg_id: 'pkg-123',
        workflow_employees: [{ id: 'wf-from-mod', label: 'Mod' }],
      }
      mockModsStoreModsForUi.mockReturnValue([modWithEmployees])
      const item: MarketInstallCatalogItem = {
        id: 'pkg1',
        pkg_id: 'pkg-123',
        artifact: 'mod_pack',
      }
      mockWfStoreEnableEmployees.mockReturnValue(['wf-from-mod'])

      const result = await autoOnboardInstalledMarketItem(item)

      expect(result.onboardedIds).toEqual(['wf-from-mod'])
    })

    it('item 无 id 和 pkg_id 时 resolveInstalledMod 返回 undefined', async () => {
      const item: MarketInstallCatalogItem = {
        artifact: 'mod_pack',
        workflow_employees: [{ id: 'wf-1', label: 'WF1' }],
      }
      mockWfStoreEnableEmployees.mockReturnValue(['wf-1'])

      const result = await autoOnboardInstalledMarketItem(item)

      // 仅 catalogItem 的员工被收集
      expect(result.onboardedIds).toEqual(['wf-1'])
    })

    it('调用 modsStore.refresh 和 wfStore.refreshRegistry', async () => {
      const item: MarketInstallCatalogItem = {
        id: 'pkg1',
        pkg_id: 'pkg1',
        artifact: 'mod_pack',
        workflow_employees: [{ id: 'wf-1', label: 'WF1' }],
      }

      await autoOnboardInstalledMarketItem(item)

      expect(mockModsStoreRefresh).toHaveBeenCalled()
      expect(mockWfStoreRefreshRegistry).toHaveBeenCalled()
    })

    it('两次调用 resolveEnterpriseModStack（初始 + refresh 后）', async () => {
      const item: MarketInstallCatalogItem = {
        id: 'pkg1',
        pkg_id: 'pkg1',
        artifact: 'mod_pack',
        workflow_employees: [{ id: 'wf-1', label: 'WF1' }],
      }

      await autoOnboardInstalledMarketItem(item)

      expect(mockResolveEnterpriseModStack).toHaveBeenCalledTimes(2)
    })

    it('返回 enterpriseStackLabel 来自 stack.stackLabel', async () => {
      mockResolveEnterpriseModStack.mockResolvedValue({
        ...baseStack,
        stackLabel: '涂装 + 定制A',
      })
      const item: MarketInstallCatalogItem = {
        id: 'pkg1',
        pkg_id: 'pkg1',
        artifact: 'mod_pack',
        workflow_employees: [{ id: 'wf-1', label: 'WF1' }],
      }

      const result = await autoOnboardInstalledMarketItem(item)

      expect(result.enterpriseStackLabel).toBe('涂装 + 定制A')
    })
  })

  // ═══════════════════════════════════════════════════════════
  // 3. autoOnboardWorkflowEmployeesForMod（deprecated 代理）
  // ═══════════════════════════════════════════════════════════
  describe('autoOnboardWorkflowEmployeesForMod', () => {
    it('代理调用 autoOnboardInstalledMarketItem 并返回 onboardedIds', async () => {
      const modWithEmployees = {
        id: 'mod-1',
        pkg_id: 'mod-1',
        workflow_employees: [
          { id: 'wf-1', label: 'WF1' },
          { id: 'wf-2', label: 'WF2' },
        ],
      }
      mockModsStoreModsForUi.mockReturnValue([modWithEmployees])
      mockWfStoreEnableEmployees.mockReturnValue(['wf-1', 'wf-2'])

      const result = await autoOnboardWorkflowEmployeesForMod('mod-1')

      expect(result).toEqual(['wf-1', 'wf-2'])
      // 应以 { id: modId, pkg_id: modId } 调用 autoOnboardInstalledMarketItem
      expect(mockModsStoreRefresh).toHaveBeenCalled()
    })

    it('modId 为空字符串时仍正常执行', async () => {
      mockWfStoreEnableEmployees.mockReturnValue([])

      const result = await autoOnboardWorkflowEmployeesForMod('')

      expect(result).toEqual([])
    })
  })

  // ═══════════════════════════════════════════════════════════
  // 4. autoOnboardWorkflowEmployeesFromMods
  // ═══════════════════════════════════════════════════════════
  describe('autoOnboardWorkflowEmployeesFromMods', () => {
    it('mods 为 undefined 时返回空数组', async () => {
      const result = await autoOnboardWorkflowEmployeesFromMods(undefined)
      expect(result).toEqual([])
    })

    it('mods 为空数组时返回空数组', async () => {
      const result = await autoOnboardWorkflowEmployeesFromMods([])
      expect(result).toEqual([])
    })

    it('mods 无 workflow_employees 时返回空数组', async () => {
      mockFilterWorkflowRegistrySourceMods.mockImplementation((mods: unknown[]) => mods)
      const result = await autoOnboardWorkflowEmployeesFromMods([
        { id: 'mod-1', name: 'Mod1' },
        { id: 'mod-2', name: 'Mod2', workflow_employees: [] },
      ])
      expect(result).toEqual([])
    })

    it('mods 含 workflow_employees 时上岗员工', async () => {
      mockFilterWorkflowRegistrySourceMods.mockImplementation((mods: unknown[]) => mods)
      mockWfStoreEnableEmployees.mockReturnValue(['wf-1', 'wf-2'])

      const result = await autoOnboardWorkflowEmployeesFromMods([
        {
          id: 'mod-1',
          name: 'Mod1',
          workflow_employees: [
            { id: 'wf-1', label: 'WF1' },
            { id: 'wf-2', label: 'WF2' },
          ],
        },
      ])

      expect(result).toEqual(['wf-1', 'wf-2'])
      expect(mockWfStoreEnableEmployees).toHaveBeenCalledWith(['wf-1', 'wf-2'], {
        onlyNew: false,
      })
    })

    it('多个 mod 的员工 id 被合并', async () => {
      mockFilterWorkflowRegistrySourceMods.mockImplementation((mods: unknown[]) => mods)
      mockWfStoreEnableEmployees.mockReturnValue(['wf-1', 'wf-2', 'wf-3'])

      const result = await autoOnboardWorkflowEmployeesFromMods([
        {
          id: 'mod-1',
          name: 'Mod1',
          workflow_employees: [{ id: 'wf-1', label: 'WF1' }],
        },
        {
          id: 'mod-2',
          name: 'Mod2',
          workflow_employees: [
            { id: 'wf-2', label: 'WF2' },
            { id: 'wf-3', label: 'WF3' },
          ],
        },
      ])

      expect(result).toEqual(['wf-1', 'wf-2', 'wf-3'])
    })

    it('非工作流工位员工 id 被过滤', async () => {
      mockFilterWorkflowRegistrySourceMods.mockImplementation((mods: unknown[]) => mods)
      mockIsNonWorkflowDeskEmployeeId.mockImplementation((id: string) => id === 'host_foundation')
      mockWfStoreEnableEmployees.mockReturnValue(['wf-1'])

      const result = await autoOnboardWorkflowEmployeesFromMods([
        {
          id: 'mod-1',
          name: 'Mod1',
          workflow_employees: [
            { id: 'wf-1', label: 'WF1' },
            { id: 'host_foundation', label: 'Host' },
            { id: '', label: 'Empty' },
          ],
        },
      ])

      expect(result).toEqual(['wf-1'])
    })

    it('filterWorkflowRegistrySourceMods 过滤后无源 mod 时返回空数组', async () => {
      mockFilterWorkflowRegistrySourceMods.mockReturnValue([])

      const result = await autoOnboardWorkflowEmployeesFromMods([
        {
          id: 'mod-1',
          name: 'Mod1',
          workflow_employees: [{ id: 'wf-1', label: 'WF1' }],
        },
      ])

      expect(result).toEqual([])
      expect(mockWfStoreEnableEmployees).not.toHaveBeenCalled()
    })

    it('调用 modsStore.refresh 和 wfStore.refreshRegistry', async () => {
      mockFilterWorkflowRegistrySourceMods.mockImplementation((mods: unknown[]) => mods)
      mockWfStoreEnableEmployees.mockReturnValue([])

      await autoOnboardWorkflowEmployeesFromMods([
        { id: 'mod-1', name: 'Mod1', workflow_employees: [{ id: 'wf-1', label: 'WF1' }] },
      ])

      expect(mockModsStoreRefresh).toHaveBeenCalled()
      expect(mockWfStoreRefreshRegistry).toHaveBeenCalled()
    })

    it('mod 为 undefined 元素时被跳过', async () => {
      mockFilterWorkflowRegistrySourceMods.mockImplementation((mods: unknown[]) => mods)
      mockWfStoreEnableEmployees.mockReturnValue(['wf-1'])

      const result = await autoOnboardWorkflowEmployeesFromMods([
        undefined,
        { id: 'mod-1', name: 'Mod1', workflow_employees: [{ id: 'wf-1', label: 'WF1' }] },
      ] as unknown as Parameters<typeof autoOnboardWorkflowEmployeesFromMods>[0])

      expect(result).toEqual(['wf-1'])
    })

    it('mod 的 workflow_employees 为 undefined 时被跳过', async () => {
      mockFilterWorkflowRegistrySourceMods.mockImplementation((mods: unknown[]) => mods)
      mockWfStoreEnableEmployees.mockReturnValue(['wf-1'])

      const result = await autoOnboardWorkflowEmployeesFromMods([
        { id: 'mod-1', name: 'Mod1' },
        { id: 'mod-2', name: 'Mod2', workflow_employees: [{ id: 'wf-1', label: 'WF1' }] },
      ])

      expect(result).toEqual(['wf-1'])
    })
  })
})
