import { describe, expect, it } from 'vitest'
import { ADMIN_OPERATOR_VISIBLE_CORE_KEYS } from '../../../admin-console/src/constants/adminOperatorNav'
import { canShowCoreMenuKey, type RoleMenuProfile } from '@/utils/roleMenuProfile'
import { CORE_MENU_ITEMS_BASE } from './coreMenuCatalog'

describe('real admin console employee sidebar', () => {
  it('preserves workbench, workspace, and graph after the actual admin allowlist filter', () => {
    const adminProfile: RoleMenuProfile = {
      role: 'local-admin',
      canSeeAdminMenus: true,
      canSeeDeveloperMenus: true,
      visibleCoreKeys: new Set(ADMIN_OPERATOR_VISIBLE_CORE_KEYS),
    }
    const parent = CORE_MENU_ITEMS_BASE.find(item => item.key === 'employee-workflow')
    expect(parent).toBeDefined()
    expect(canShowCoreMenuKey(adminProfile, 'employee-workflow')).toBe(true)
    expect(parent?.children?.filter(child => canShowCoreMenuKey(adminProfile, child.key)).map(child => child.key)).toEqual([
      'employee-workbench',
      'workflow-employee-space',
      'workflow-employee-stitch-full',
    ])
    expect(canShowCoreMenuKey(adminProfile, 'orders')).toBe(false)
  })
})
