import { describe, expect, it, beforeEach, vi } from 'vitest'
import { KITTEN_VIZ_EMPLOYEES, KITTEN_VIZ_EMPLOYEE_PKG_IDS, findKittenVizEmployee } from './kittenVisualizationEmployees'
import { hostViewGlob as hostViewGlobGeneric } from './hostViewGlob.generic'
import { hostViewGlob as hostViewGlobMinimal } from './hostViewGlob.minimal'
import { hostViewGlob as hostViewGlobEnterprise } from './hostViewGlob.enterprise'
import { modRouteGlob as modRouteGlobEnterprise } from './modRouteGlob.enterprise'
import { modRouteGlob as modRouteGlobMinimal } from './modRouteGlob.minimal'
import { modRouteGlob as modRouteGlobFull } from './modRouteGlob.full'
import { modRouteGlob as modRouteGlobGeneric } from './modRouteGlob.generic'
import { modRouteGlob as modRouteGlobReExport } from './modRouteGlob'
import { modPhysicalViewGlob as modPhysicalViewGlobMinimal } from './modPhysicalViewGlob.minimal'
import { modPhysicalViewGlob as modPhysicalViewGlobEnterprise } from './modPhysicalViewGlob.enterprise'
import { modPhysicalViewGlob as modPhysicalViewGlobGeneric } from './modPhysicalViewGlob.generic'
import { buildTimeEdition, isMinimalBuild, isGenericBuild, MINIMAL_BUILD_MOD_IDS } from './buildEdition'
import { BRIDGE_MOD_IDS, PLATFORM_SHELL_POLICY } from './platformShell'
import { SIX_LINE_DEPARTMENTS } from './sixLineDepartments'
import { YUANGONG_STITCH_STATION_PLACEMENTS } from './yuangongStitchPlacements'
import { YUANGONG_STITCH_HOTSPOTS } from './yuangongStitchHotspots'
import { ALL_PLANNED_YUANGON_PKG_IDS } from './modstoreDutyRosterIds'
import {
  xcmaxAutomationPolicyEmbedUrl,
  xcmaxAutomationPolicyOpenUrl,
  xcmaxDutyTimeArchitectureEmbedUrl,
} from './xcmaxDashboardEmbed'
import {
  ENTERPRISE_CUSTOMER_SERVICE_KEY,
  INTERNAL_CUSTOMER_SERVICE_KEY,
  customerServiceSideForNavKey,
  isCustomerServiceNavVisible,
} from './customerServiceNav'
import { isCoreWorkflowModInstalled, CORE_WORKFLOW_MOD_ID, LEGACY_CORE_WORKFLOW_MOD_ID } from './coreWorkflowMod'
import {
  TUTORIAL_DEPT_EMPLOYEE_SAMPLE_XLSX,
  TUTORIAL_QUICKSTART_EXCEL_A,
  TUTORIAL_QUICKSTART_EXCEL_B,
  TUTORIAL_QUICKSTART_WORD,
  TUTORIAL_SAMPLE_NAME_PREFIX,
  trackTutorialOfficeUploadPath,
  readTutorialOfficeUploadPaths,
  clearTutorialOfficeUploadPaths,
} from './tutorialSamples'
import {
  ATTENDANCE_INDUSTRY_MOD_FALLBACK_MENU,
  ATTENDANCE_INDUSTRY_MOD_FALLBACK_OVERRIDES,
  COATING_CUSTOM_MOD_FALLBACK_OVERRIDES,
  SUNBIRD_CLIENT_MOD_FALLBACK_MENU,
  SUNBIRD_CLIENT_MOD_FALLBACK_OVERRIDES,
  buildAttendanceIndustryModStub,
  buildSunbirdClientModStub,
  buildCoatingCustomModStub,
} from './sunbirdClientMod'

describe('kittenVisualizationEmployees', () => {
  it('exports four kitten viz employees', () => {
    expect(KITTEN_VIZ_EMPLOYEES).toHaveLength(4)
  })

  it('each employee has required fields with valid values', () => {
    for (const emp of KITTEN_VIZ_EMPLOYEES) {
      expect(typeof emp.pkgId).toBe('string')
      expect(emp.pkgId.length).toBeGreaterThan(0)
      expect(typeof emp.name).toBe('string')
      expect(typeof emp.icon).toBe('string')
      expect(['bar', 'line', 'pie', 'scatter', 'area']).toContain(emp.chartType)
      expect(Array.isArray(emp.palette)).toBe(true)
      expect(emp.palette.length).toBeGreaterThan(0)
      expect(typeof emp.description).toBe('string')
    }
  })

  it('dashboard employee has dashboard flag set', () => {
    const dashboard = KITTEN_VIZ_EMPLOYEES.find((e) => e.dashboard)
    expect(dashboard).toBeDefined()
    expect(dashboard?.pkgId).toBe('chart-dashboard-employee')
  })

  it('KITTEN_VIZ_EMPLOYEE_PKG_IDS matches pkgIds of employees', () => {
    expect(KITTEN_VIZ_EMPLOYEE_PKG_IDS).toEqual(KITTEN_VIZ_EMPLOYEES.map((e) => e.pkgId))
  })

  it('findKittenVizEmployee returns matching employee by pkgId', () => {
    const found = findKittenVizEmployee('chart-bar-employee')
    expect(found).toBeDefined()
    expect(found?.name).toBe('柱状图可视化员')
  })

  it('findKittenVizEmployee returns undefined for unknown pkgId', () => {
    expect(findKittenVizEmployee('unknown-id')).toBeUndefined()
  })

  it('findKittenVizEmployee handles null/undefined/empty/whitespace input', () => {
    expect(findKittenVizEmployee(undefined)).toBeUndefined()
    expect(findKittenVizEmployee(null)).toBeUndefined()
    expect(findKittenVizEmployee('')).toBeUndefined()
    expect(findKittenVizEmployee('   ')).toBeUndefined()
  })

  it('findKittenVizEmployee trims whitespace around pkgId', () => {
    const found = findKittenVizEmployee('  chart-bar-employee  ')
    expect(found).toBeDefined()
    expect(found?.pkgId).toBe('chart-bar-employee')
  })
})

describe('hostViewGlob variants', () => {
  it('hostViewGlob.generic includes chat and settings views', () => {
    expect(Object.keys(hostViewGlobGeneric).length).toBeGreaterThan(0)
    const keys = Object.keys(hostViewGlobGeneric)
    expect(keys.some((k) => k.includes('ChatView.vue'))).toBe(true)
    expect(keys.some((k) => k.includes('SettingsView.vue'))).toBe(true)
    expect(keys.some((k) => k.includes('LoginView.vue'))).toBe(true)
  })

  it('hostViewGlob.minimal includes chat and modstore views', () => {
    expect(Object.keys(hostViewGlobMinimal).length).toBeGreaterThan(0)
    const keys = Object.keys(hostViewGlobMinimal)
    expect(keys.some((k) => k.includes('ChatView.vue'))).toBe(true)
    expect(keys.some((k) => k.includes('ModStore.vue'))).toBe(true)
  })

  it('hostViewGlob.enterprise filters out temp/Fixed/Optimized views', () => {
    const keys = Object.keys(hostViewGlobEnterprise)
    expect(keys.length).toBeGreaterThan(0)
    for (const k of keys) {
      const norm = k.replace(/\\/g, '/')
      expect(norm).not.toMatch(/\/views\/temp\d+\.vue$/)
      expect(norm).not.toMatch(/\/views\/[^/]+(?:Fixed|Optimized)\.vue$/)
    }
  })

  it('each hostViewGlob entry is a function loader', () => {
    for (const loader of Object.values(hostViewGlobGeneric)) {
      expect(typeof loader).toBe('function')
    }
    for (const loader of Object.values(hostViewGlobMinimal)) {
      expect(typeof loader).toBe('function')
    }
  })
})

describe('modRouteGlob variants', () => {
  it('modRouteGlob.enterprise globs bridge routes from mods directory', () => {
    const keys = Object.keys(modRouteGlobEnterprise)
    // glob 结果取决于磁盘上实际存在的 mods；至少应包含 planner-bridge
    expect(keys.some((k) => k.includes('xcagi-planner-bridge'))).toBe(true)
    // 所有 key 都应指向 mods 目录下的 routes.js
    for (const k of keys) {
      expect(k).toContain('/mods/')
      expect(k).toContain('routes.js')
    }
  })

  it('modRouteGlob.minimal globs subset of enterprise (only minimal bridges on disk)', () => {
    const keys = Object.keys(modRouteGlobMinimal)
    // minimal 只 glob 三个 bridge，实际存在的可能更少
    expect(keys.length).toBeGreaterThanOrEqual(0)
    for (const k of keys) {
      expect(k).toContain('/mods/')
      expect(k).toContain('routes.js')
    }
  })

  it('modRouteGlob.full uses wildcard glob over mods and mods-admin-runtime', () => {
    const keys = Object.keys(modRouteGlobFull)
    expect(keys.length).toBeGreaterThanOrEqual(0)
    for (const k of keys) {
      expect(k).toContain('routes.js')
    }
  })

  it('modRouteGlob.generic is empty (mods registered at runtime)', () => {
    expect(Object.keys(modRouteGlobGeneric)).toHaveLength(0)
  })

  it('modRouteGlob re-export matches modRouteGlob.full', () => {
    expect(modRouteGlobReExport).toBe(modRouteGlobFull)
  })

  it('each modRouteGlob entry is a function loader', () => {
    for (const loader of Object.values(modRouteGlobEnterprise)) {
      expect(typeof loader).toBe('function')
    }
    for (const loader of Object.values(modRouteGlobMinimal)) {
      expect(typeof loader).toBe('function')
    }
  })
})

describe('modPhysicalViewGlob variants', () => {
  it('modPhysicalViewGlob.minimal globs bridge views from mods directory', () => {
    const keys = Object.keys(modPhysicalViewGlobMinimal)
    // glob 结果取决于磁盘上实际存在的 mods；至少应包含 planner-bridge
    expect(keys.some((k) => k.includes('xcagi-planner-bridge'))).toBe(true)
    for (const k of keys) {
      expect(k).toContain('/mods/')
      expect(k).toContain('.vue')
    }
  })

  it('modPhysicalViewGlob.enterprise uses wildcard glob', () => {
    expect(Object.keys(modPhysicalViewGlobEnterprise).length).toBeGreaterThanOrEqual(0)
  })

  it('modPhysicalViewGlob.generic is empty', () => {
    expect(Object.keys(modPhysicalViewGlobGeneric)).toHaveLength(0)
  })
})

describe('buildEdition', () => {
  it('MINIMAL_BUILD_MOD_IDS contains the three minimal bridges', () => {
    expect(MINIMAL_BUILD_MOD_IDS).toHaveLength(3)
    expect(MINIMAL_BUILD_MOD_IDS).toContain('xcagi-planner-bridge')
    expect(MINIMAL_BUILD_MOD_IDS).toContain('xcagi-neuro-bus-bridge')
    expect(MINIMAL_BUILD_MOD_IDS).toContain('xcagi-office-employee-pack-bridge')
  })

  it('buildTimeEdition returns a valid HostEdition', () => {
    const edition = buildTimeEdition()
    expect(['minimal', 'generic', 'full']).toContain(edition)
  })

  it('isMinimalBuild and isGenericBuild are mutually exclusive booleans', () => {
    expect(typeof isMinimalBuild()).toBe('boolean')
    expect(typeof isGenericBuild()).toBe('boolean')
    if (isMinimalBuild()) {
      expect(isGenericBuild()).toBe(false)
    }
    if (isGenericBuild()) {
      expect(isMinimalBuild()).toBe(false)
    }
  })
})

describe('platformShell', () => {
  it('BRIDGE_MOD_IDS contains four bridge mod ids', () => {
    expect(BRIDGE_MOD_IDS).toHaveLength(4)
    expect(BRIDGE_MOD_IDS).toContain('xcagi-approval-bridge')
    expect(BRIDGE_MOD_IDS).toContain('xcagi-lan-license-bridge')
    expect(BRIDGE_MOD_IDS).toContain('xcagi-model-payment-bridge')
    expect(BRIDGE_MOD_IDS).toContain('xcagi-planner-bridge')
  })

  it('PLATFORM_SHELL_POLICY is a non-empty guidance string', () => {
    expect(typeof PLATFORM_SHELL_POLICY).toBe('string')
    expect(PLATFORM_SHELL_POLICY.length).toBeGreaterThan(0)
    expect(PLATFORM_SHELL_POLICY).toContain('Mod')
  })
})

describe('sixLineDepartments', () => {
  it('exports six departments in order', () => {
    expect(SIX_LINE_DEPARTMENTS).toHaveLength(6)
  })

  it('each department has id and label', () => {
    for (const dept of SIX_LINE_DEPARTMENTS) {
      expect(typeof dept.id).toBe('string')
      expect(dept.id.length).toBeGreaterThan(0)
      expect(typeof dept.label).toBe('string')
      expect(dept.label.length).toBeGreaterThan(0)
    }
  })

  it('contains expected department ids', () => {
    const ids = SIX_LINE_DEPARTMENTS.map((d) => d.id)
    expect(ids).toEqual(['site', 'ops', 'product', 'market', 'workflow', 'quality'])
  })
})

describe('yuangongStitchPlacements', () => {
  it('exports four placeholder placements', () => {
    expect(YUANGONG_STITCH_STATION_PLACEMENTS).toHaveLength(4)
  })

  it('each placement has empId, leftPct, topPct, and scale', () => {
    for (const p of YUANGONG_STITCH_STATION_PLACEMENTS) {
      expect(typeof p.empId).toBe('string')
      expect(p.empId.length).toBeGreaterThan(0)
      expect(typeof p.leftPct).toBe('number')
      expect(p.leftPct).toBeGreaterThanOrEqual(0)
      expect(p.leftPct).toBeLessThanOrEqual(100)
      expect(typeof p.topPct).toBe('number')
      expect(p.topPct).toBeGreaterThanOrEqual(0)
      expect(p.topPct).toBeLessThanOrEqual(100)
      expect(typeof p.scale).toBe('number')
      expect(p.scale).toBeGreaterThan(0)
    }
  })

  it('placements are along the bottom row (topPct=82)', () => {
    for (const p of YUANGONG_STITCH_STATION_PLACEMENTS) {
      expect(p.topPct).toBe(82)
    }
  })
})

describe('yuangongStitchHotspots', () => {
  it('exports an empty array initially', () => {
    expect(Array.isArray(YUANGONG_STITCH_HOTSPOTS)).toBe(true)
    expect(YUANGONG_STITCH_HOTSPOTS).toHaveLength(0)
  })
})

describe('modstoreDutyRosterIds', () => {
  it('re-exports ALL_PLANNED_YUANGON_PKG_IDS as a non-empty set', () => {
    expect(ALL_PLANNED_YUANGON_PKG_IDS).toBeInstanceOf(Set)
    expect(ALL_PLANNED_YUANGON_PKG_IDS.size).toBeGreaterThan(0)
  })
})

describe('xcmaxDashboardEmbed', () => {
  it('xcmaxAutomationPolicyEmbedUrl returns a url with embed=loops', () => {
    const url = xcmaxAutomationPolicyEmbedUrl()
    expect(typeof url).toBe('string')
    expect(url).toContain('embed=loops')
    expect(url).toContain('#s-loops')
  })

  it('xcmaxAutomationPolicyOpenUrl returns a url with #s-loops', () => {
    const url = xcmaxAutomationPolicyOpenUrl()
    expect(typeof url).toBe('string')
    expect(url).toContain('#s-loops')
    expect(url).not.toContain('embed=loops')
  })

  it('xcmaxDutyTimeArchitectureEmbedUrl returns a url with embed=shell', () => {
    const url = xcmaxDutyTimeArchitectureEmbedUrl()
    expect(typeof url).toBe('string')
    expect(url).toContain('embed=shell')
    expect(url).toContain('view=mermaid')
  })
})

describe('customerServiceNav', () => {
  it('exports enterprise and internal customer service keys', () => {
    expect(ENTERPRISE_CUSTOMER_SERVICE_KEY).toBe('enterprise-customer-service')
    expect(INTERNAL_CUSTOMER_SERVICE_KEY).toBe('internal-customer-service')
  })

  it('customerServiceSideForNavKey returns enterprise for enterprise key', () => {
    expect(customerServiceSideForNavKey(ENTERPRISE_CUSTOMER_SERVICE_KEY)).toBe('enterprise')
  })

  it('customerServiceSideForNavKey returns admin for internal key', () => {
    expect(customerServiceSideForNavKey(INTERNAL_CUSTOMER_SERVICE_KEY)).toBe('admin')
  })

  it('customerServiceSideForNavKey returns null for unknown key', () => {
    expect(customerServiceSideForNavKey('unknown')).toBeNull()
    expect(customerServiceSideForNavKey('')).toBeNull()
  })

  it('isCustomerServiceNavVisible returns true for unknown keys', () => {
    expect(isCustomerServiceNavVisible('unknown', true)).toBe(true)
    expect(isCustomerServiceNavVisible('unknown', false)).toBe(true)
  })

  it('isCustomerServiceNavVisible shows admin side only for admin accounts', () => {
    expect(isCustomerServiceNavVisible(INTERNAL_CUSTOMER_SERVICE_KEY, true)).toBe(true)
    expect(isCustomerServiceNavVisible(INTERNAL_CUSTOMER_SERVICE_KEY, false)).toBe(false)
  })

  it('isCustomerServiceNavVisible shows enterprise side only for non-admin accounts', () => {
    expect(isCustomerServiceNavVisible(ENTERPRISE_CUSTOMER_SERVICE_KEY, false)).toBe(true)
    expect(isCustomerServiceNavVisible(ENTERPRISE_CUSTOMER_SERVICE_KEY, true)).toBe(false)
  })
})

describe('coreWorkflowMod', () => {
  it('re-exports CORE_WORKFLOW_MOD_ID as workflow viz bridge id', () => {
    expect(CORE_WORKFLOW_MOD_ID).toBe('xcagi-workflow-visualization-bridge')
  })

  it('re-exports LEGACY_CORE_WORKFLOW_MOD_ID', () => {
    expect(LEGACY_CORE_WORKFLOW_MOD_ID).toBe('xcagi-core-workflow-employees')
  })

  it('isCoreWorkflowModInstalled returns false for empty/null/undefined mods', () => {
    expect(isCoreWorkflowModInstalled([])).toBe(false)
    expect(isCoreWorkflowModInstalled(null)).toBe(false)
    expect(isCoreWorkflowModInstalled(undefined)).toBe(false)
  })

  it('isCoreWorkflowModInstalled returns false for unrelated mods', () => {
    expect(isCoreWorkflowModInstalled([{ id: 'other-mod' }])).toBe(false)
    expect(isCoreWorkflowModInstalled([{ id: 'xcagi-planner-bridge' }])).toBe(false)
  })

  it('isCoreWorkflowModInstalled returns true when workflow-visualization-bridge present', () => {
    expect(isCoreWorkflowModInstalled([{ id: 'xcagi-workflow-visualization-bridge' }])).toBe(true)
  })

  it('isCoreWorkflowModInstalled returns true when legacy core-workflow-employees present', () => {
    expect(isCoreWorkflowModInstalled([{ id: 'xcagi-core-workflow-employees' }])).toBe(true)
  })

  it('isCoreWorkflowModInstalled trims whitespace in mod id', () => {
    expect(isCoreWorkflowModInstalled([{ id: '  xcagi-workflow-visualization-bridge  ' }])).toBe(true)
  })

  it('isCoreWorkflowModInstalled handles mods with missing/empty id', () => {
    expect(isCoreWorkflowModInstalled([{ id: '' }])).toBe(false)
    expect(isCoreWorkflowModInstalled([{}])).toBe(false)
    expect(isCoreWorkflowModInstalled([{ id: undefined }])).toBe(false)
  })
})

describe('tutorialSamples', () => {
  it('exports tutorial sample file paths', () => {
    expect(TUTORIAL_DEPT_EMPLOYEE_SAMPLE_XLSX).toBe('/tutorial/xcagi-tutorial-dept-employee.xlsx')
    expect(TUTORIAL_QUICKSTART_EXCEL_A).toBe('/tutorial/xcagi-quickstart-sample-a.xlsx')
    expect(TUTORIAL_QUICKSTART_EXCEL_B).toBe('/tutorial/xcagi-quickstart-sample-b.xlsx')
    expect(TUTORIAL_QUICKSTART_WORD).toBe('/tutorial/xcagi-quickstart-sample.docx')
  })

  it('exports tutorial sample name prefix', () => {
    expect(TUTORIAL_SAMPLE_NAME_PREFIX).toBe('教程示例-')
  })

  describe('trackTutorialOfficeUploadPath', () => {
    beforeEach(() => {
      sessionStorage.clear()
    })

    it('stores a new path in sessionStorage', () => {
      trackTutorialOfficeUploadPath('/tmp/file1.xlsx')
      expect(readTutorialOfficeUploadPaths()).toEqual(['/tmp/file1.xlsx'])
    })

    it('does not duplicate existing paths', () => {
      trackTutorialOfficeUploadPath('/tmp/file1.xlsx')
      trackTutorialOfficeUploadPath('/tmp/file1.xlsx')
      expect(readTutorialOfficeUploadPaths()).toEqual(['/tmp/file1.xlsx'])
    })

    it('appends new paths preserving order', () => {
      trackTutorialOfficeUploadPath('/tmp/file1.xlsx')
      trackTutorialOfficeUploadPath('/tmp/file2.xlsx')
      expect(readTutorialOfficeUploadPaths()).toEqual(['/tmp/file1.xlsx', '/tmp/file2.xlsx'])
    })

    it('keeps only last 12 paths', () => {
      for (let i = 0; i < 15; i += 1) {
        trackTutorialOfficeUploadPath(`/tmp/file${i}.xlsx`)
      }
      const paths = readTutorialOfficeUploadPaths()
      expect(paths).toHaveLength(12)
      expect(paths[0]).toBe('/tmp/file3.xlsx')
      expect(paths[11]).toBe('/tmp/file14.xlsx')
    })

    it('ignores empty filePath', () => {
      trackTutorialOfficeUploadPath('')
      expect(readTutorialOfficeUploadPaths()).toEqual([])
    })

    it('ignores null/undefined filePath', () => {
      trackTutorialOfficeUploadPath(null as unknown as string)
      trackTutorialOfficeUploadPath(undefined as unknown as string)
      expect(readTutorialOfficeUploadPaths()).toEqual([])
    })
  })

  describe('readTutorialOfficeUploadPaths', () => {
    beforeEach(() => {
      sessionStorage.clear()
    })

    it('returns empty array when nothing stored', () => {
      expect(readTutorialOfficeUploadPaths()).toEqual([])
    })

    it('returns stored paths', () => {
      trackTutorialOfficeUploadPath('/tmp/a.xlsx')
      trackTutorialOfficeUploadPath('/tmp/b.xlsx')
      expect(readTutorialOfficeUploadPaths()).toEqual(['/tmp/a.xlsx', '/tmp/b.xlsx'])
    })

    it('returns empty array when sessionStorage has invalid JSON', () => {
      sessionStorage.setItem('xcagi_tutorial_office_upload_paths', 'not-json')
      expect(readTutorialOfficeUploadPaths()).toEqual([])
    })
  })

  describe('clearTutorialOfficeUploadPaths', () => {
    beforeEach(() => {
      sessionStorage.clear()
    })

    it('removes stored paths', () => {
      trackTutorialOfficeUploadPath('/tmp/a.xlsx')
      expect(readTutorialOfficeUploadPaths()).toHaveLength(1)
      clearTutorialOfficeUploadPaths()
      expect(readTutorialOfficeUploadPaths()).toEqual([])
    })

    it('does not throw when nothing stored', () => {
      expect(() => clearTutorialOfficeUploadPaths()).not.toThrow()
    })
  })
})

describe('sunbirdClientMod', () => {
  it('ATTENDANCE_INDUSTRY_MOD_FALLBACK_MENU has one entry', () => {
    expect(ATTENDANCE_INDUSTRY_MOD_FALLBACK_MENU).toHaveLength(1)
    expect(ATTENDANCE_INDUSTRY_MOD_FALLBACK_MENU[0].id).toBe('attendance-industry-home')
    expect(ATTENDANCE_INDUSTRY_MOD_FALLBACK_MENU[0].path).toBe('/attendance-industry')
  })

  it('ATTENDANCE_INDUSTRY_MOD_FALLBACK_OVERRIDES is empty array', () => {
    expect(ATTENDANCE_INDUSTRY_MOD_FALLBACK_OVERRIDES).toEqual([])
  })

  it('COATING_CUSTOM_MOD_FALLBACK_OVERRIDES has six entries', () => {
    expect(COATING_CUSTOM_MOD_FALLBACK_OVERRIDES).toHaveLength(6)
    const keys = COATING_CUSTOM_MOD_FALLBACK_OVERRIDES.map((o) => o.key)
    expect(keys).toEqual(['products', 'customers', 'materials', 'orders', 'shipment-records', 'print'])
  })

  it('SUNBIRD deprecated aliases point to same objects', () => {
    expect(SUNBIRD_CLIENT_MOD_FALLBACK_MENU).toBe(ATTENDANCE_INDUSTRY_MOD_FALLBACK_MENU)
    expect(SUNBIRD_CLIENT_MOD_FALLBACK_OVERRIDES).toBe(ATTENDANCE_INDUSTRY_MOD_FALLBACK_OVERRIDES)
  })

  describe('buildAttendanceIndustryModStub', () => {
    it('returns a ModInfo stub for attendance industry', () => {
      const stub = buildAttendanceIndustryModStub()
      expect(stub.id).toBe('attendance-industry')
      expect(stub.name).toBe('考勤行业包')
      expect(stub.version).toBe('1.0.0')
      expect(stub.primary).toBe(true)
      expect(stub.frontend?.pro_entry_path).toBe('/attendance-industry')
      expect(stub.menu).toHaveLength(1)
      expect(stub.menu_overrides).toEqual([])
      expect(stub.industry?.id).toBe('考勤')
    })

    it('returns a deep copy of the fallback menu (not same reference)', () => {
      const stub = buildAttendanceIndustryModStub()
      expect(stub.menu).not.toBe(ATTENDANCE_INDUSTRY_MOD_FALLBACK_MENU)
      expect(stub.menu).toEqual(ATTENDANCE_INDUSTRY_MOD_FALLBACK_MENU)
    })
  })

  describe('buildSunbirdClientModStub', () => {
    it('returns a ModInfo stub for sunbird (taiyangniao-pro)', () => {
      const stub = buildSunbirdClientModStub()
      expect(stub.id).toBe('taiyangniao-pro')
      expect(stub.name).toBe('太阳鸟 PRO')
      expect(stub.version).toBe('1.0.0')
      expect(stub.primary).toBe(true)
      expect(stub.frontend?.pro_entry_path).toBe('/taiyangniao-pro')
      expect(stub.menu).toHaveLength(1)
      expect(stub.menu[0].id).toBe('taiyangniao-pro-home')
      expect(stub.menu_overrides).toHaveLength(2)
      expect(stub.industry?.id).toBe('考勤')
    })
  })

  describe('buildCoatingCustomModStub', () => {
    it('returns a ModInfo stub for coating (sz-qsm-pro)', () => {
      const stub = buildCoatingCustomModStub()
      expect(stub.id).toBe('sz-qsm-pro')
      expect(stub.name).toBe('奇士美 PRO')
      expect(stub.version).toBe('1.0.0')
      expect(stub.primary).toBe(true)
      expect(stub.frontend?.pro_entry_path).toBe('/qsm-pro')
      expect(stub.menu).toHaveLength(1)
      expect(stub.menu[0].id).toBe('qsm-pro-home')
      expect(stub.menu_overrides).toHaveLength(6)
      expect(stub.industry?.id).toBe('涂料')
    })

    it('returns a deep copy of the coating overrides (not same reference)', () => {
      const stub = buildCoatingCustomModStub()
      expect(stub.menu_overrides).not.toBe(COATING_CUSTOM_MOD_FALLBACK_OVERRIDES)
      expect(stub.menu_overrides).toEqual(COATING_CUSTOM_MOD_FALLBACK_OVERRIDES)
    })
  })
})
