import { describe, expect, it, vi } from 'vitest'
import {
  GENERIC_HOST_MOD_IDS,
  isHostMountedModMenuPath,
  keepHostNavKeyVisibleWhenModSidebarFacetSuppressed,
  MINIMAL_HOST_MOD_IDS,
  shouldAutoEnableMinimalPlatformShell,
  shouldAutoEnablePlatformShell,
  shouldHideAttendanceModSidebarMenu,
} from './genericModPack'

describe('genericModPack', () => {
  it('minimal pack is subset of generic', () => {
    for (const mid of MINIMAL_HOST_MOD_IDS) {
      expect(GENERIC_HOST_MOD_IDS).toContain(mid)
    }
  })

  it('shouldAutoEnableMinimalPlatformShell when minimal mods installed', () => {
    expect(shouldAutoEnableMinimalPlatformShell([...MINIMAL_HOST_MOD_IDS])).toBe(true)
    expect(shouldAutoEnableMinimalPlatformShell(['xcagi-planner-bridge'])).toBe(false)
  })

  it('respects client primary ERP without domain bridge', () => {
    expect(
      shouldAutoEnableMinimalPlatformShell(['attendance-industry', ...MINIMAL_HOST_MOD_IDS]),
    ).toBe(false)
    const partialGeneric = GENERIC_HOST_MOD_IDS.filter((id) => id !== 'xcagi-erp-domain-bridge')
    expect(
      shouldAutoEnablePlatformShell(['attendance-industry', ...partialGeneric]),
    ).toBe(false)
  })

  it('keeps host chat when planner mod facet is suppressed in client ERP', () => {
    const installed = ['attendance-industry', 'xcagi-planner-bridge', ...MINIMAL_HOST_MOD_IDS]
    expect(
      keepHostNavKeyVisibleWhenModSidebarFacetSuppressed(
        'chat',
        installed,
        'attendance-industry',
      ),
    ).toBe(true)
    expect(
      keepHostNavKeyVisibleWhenModSidebarFacetSuppressed(
        'ai-ecosystem',
        installed,
        'attendance-industry',
      ),
    ).toBe(true)
    expect(
      keepHostNavKeyVisibleWhenModSidebarFacetSuppressed('kitten-finance', installed, 'attendance-industry'),
    ).toBe(true)
  })

  it('isHostMountedModMenuPath accepts pro_entry_path and host keys', () => {
    expect(isHostMountedModMenuPath('/wechat-contacts', '/wechat-contacts')).toBe(true)
    expect(isHostMountedModMenuPath('/chat', null)).toBe(true)
    expect(isHostMountedModMenuPath('/mod/foo/bar', '/wechat-contacts')).toBe(false)
  })

  it('hides attendance industry sidebar in enterprise/admin but keeps account custom menus', () => {
    vi.stubEnv('VITE_XCMAX_SUNBIRD_CONSOLE', '')
    vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '')
    vi.stubEnv('VITE_XCAGI_PRODUCT_SKU', 'enterprise')
    expect(shouldHideAttendanceModSidebarMenu('mod-attendance-industry-home')).toBe(true)
    expect(shouldHideAttendanceModSidebarMenu('mod-taiyangniao-pro-home')).toBe(false)
    expect(shouldHideAttendanceModSidebarMenu('mod-qsm-pro-home')).toBe(false)
    vi.stubEnv('VITE_XCAGI_PRODUCT_SKU', '')
    vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '1')
    expect(shouldHideAttendanceModSidebarMenu('attendance-industry-home')).toBe(true)
    vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '')
    vi.stubEnv('VITE_XCMAX_SUNBIRD_CONSOLE', '1')
    expect(shouldHideAttendanceModSidebarMenu('mod-attendance-industry-home')).toBe(false)
  })

  it('readBuildEdition from env', async () => {
    vi.stubEnv('VITE_XCAGI_EDITION', 'minimal')
    const { readBuildEdition } = await import('./genericModPack')
    expect(readBuildEdition()).toBe('minimal')
    vi.unstubAllEnvs()
  })
})
