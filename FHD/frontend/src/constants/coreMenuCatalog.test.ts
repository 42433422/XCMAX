import { describe, expect, it } from 'vitest'
import catalog from '../../../config/core_navigation.json'
import { ADMIN_EMPLOYEE_WORKFLOW_MENU_CHILDREN, CORE_MENU_ITEMS_BASE, INDUSTRY_DELIVERY_CORE_ITEMS, pinMenuKeyFirst, PRIMARY_CHAT_MENU_KEY, sidebarLayoutSeedKeys } from './coreMenuCatalog'
import { MENU_DEFAULT_NAMES } from '../utils/coreNavLabel'
import { MOD_MENU_ID_TO_HOST_NAV_KEY } from './genericModPack'
import { TENANT_SCOPED_BUSINESS_PATHS } from '../utils/roleMenuProfile'

describe('coreMenuCatalog', () => {
  it('shares routes, labels and Mod aliases with the mobile catalog', () => {
    expect(CORE_MENU_ITEMS_BASE).toBe(catalog.core)
    expect(INDUSTRY_DELIVERY_CORE_ITEMS).toBe(catalog.industry)
    expect(MOD_MENU_ID_TO_HOST_NAV_KEY).toBe(catalog.mod_aliases)
    expect(TENANT_SCOPED_BUSINESS_PATHS).toBe(catalog.tenant_paths)
    for (const item of [...catalog.core, ...catalog.industry]) {
      expect(MENU_DEFAULT_NAMES[item.key]).toBe(item.name)
    }
    expect(catalog.core.find(item => item.key === 'employee-workflow')?.path).toBe('/employee-workbench')
    expect(catalog.industry.find(item => item.key === 'template-preview')?.requires_desktop).toBe(false)
  })

  it('keeps the admin workflow subgroup separate from employee navigation', () => {
    expect(ADMIN_EMPLOYEE_WORKFLOW_MENU_CHILDREN.map(item => item.key)).toEqual([])
    expect(CORE_MENU_ITEMS_BASE.flatMap(item => item.children || []).map(item => item.key)).toEqual(['employee-workbench', 'workflow-employee-space', 'workflow-employee-stitch-full'])
  })
  it('exposes business docking as a core menu item', () => {
    expect(CORE_MENU_ITEMS_BASE).toContainEqual(expect.objectContaining({ key: 'business-docking', name: '数据对接中心' }))
  })

  it('pinMenuKeyFirst moves chat to front', () => {
    const rows = [
      { key: 'mod-a', name: 'A' },
      { key: PRIMARY_CHAT_MENU_KEY, name: 'Chat' },
      { key: 'products', name: 'P' },
    ]
    expect(pinMenuKeyFirst(rows).map((r) => r.key)).toEqual([PRIMARY_CHAT_MENU_KEY, 'mod-a', 'products'])
  })

  it('sidebarLayoutSeedKeys starts with chat', () => {
    expect(sidebarLayoutSeedKeys()[0]).toBe(PRIMARY_CHAT_MENU_KEY)
  })
})
