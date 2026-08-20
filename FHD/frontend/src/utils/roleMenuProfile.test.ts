import { describe, expect, it } from 'vitest'
import { buildRoleMenuProfile, canShowCoreMenuKey } from '@/utils/roleMenuProfile'

describe('roleMenuProfile', () => {
  it('keeps enterprise users on the generic host menu without an industry mod', () => {
    const profile = buildRoleMenuProfile({ accountKind: 'enterprise', marketIsEnterprise: true })

    expect(profile.role).toBe('enterprise-user')
    expect(canShowCoreMenuKey(profile, 'chat')).toBe(true)
    expect(canShowCoreMenuKey(profile, 'persy-knowledge')).toBe(true)
    expect(canShowCoreMenuKey(profile, 'mod-store')).toBe(true)
    expect(canShowCoreMenuKey(profile, 'employee-workflow')).toBe(true)
    expect(canShowCoreMenuKey(profile, 'workflow-employee-space')).toBe(true)
    expect(canShowCoreMenuKey(profile, 'other-tools')).toBe(false)
    // 2026-08 菜单修复：企业用户即使无行业 Mod，也应能看到「智能体任务编排」和「数据对接中心」
    // 「流程可视化」非企业端功能，企业用户侧边栏隐藏（管理端运维壳保留）
    expect(canShowCoreMenuKey(profile, 'workflow-visualization')).toBe(false)
    expect(canShowCoreMenuKey(profile, 'business-docking')).toBe(true)
    expect(canShowCoreMenuKey(profile, 'products')).toBe(false)
    expect(canShowCoreMenuKey(profile, 'orders')).toBe(false)
  })

  it('allows industry business slots only when an industry mod is active', () => {
    const profile = buildRoleMenuProfile({ accountKind: 'enterprise', marketIsEnterprise: true }, true)

    expect(canShowCoreMenuKey(profile, 'products')).toBe(true)
    expect(canShowCoreMenuKey(profile, 'orders')).toBe(true)
  })

  it('does not restrict local admin menus', () => {
    const profile = buildRoleMenuProfile({ accountKind: 'admin', marketIsAdmin: true })

    expect(profile.canSeeAdminMenus).toBe(true)
    expect(canShowCoreMenuKey(profile, 'products')).toBe(true)
    expect(canShowCoreMenuKey(profile, 'orders')).toBe(true)
  })
})
