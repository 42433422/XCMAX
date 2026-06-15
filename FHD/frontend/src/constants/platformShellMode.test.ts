import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  bootstrapEditionDefaults,
  bootstrapGenericEditionDefaults,
  bootstrapMinimalEditionDefaults,
  isGenericEditionBuild,
  isHostBusinessMenuKey,
  isMinimalEditionBuild,
  isPlatformShellModeEnabled,
  LS_PLATFORM_SHELL_MODE,
  SHELL_CORE_MENU_KEYS,
} from './platformShellMode'

describe('platformShellMode', () => {
  it('shell core includes chat, ai-ecosystem and employee workflow group', () => {
    expect(SHELL_CORE_MENU_KEYS.has('chat')).toBe(true)
    expect(SHELL_CORE_MENU_KEYS.has('ai-ecosystem')).toBe(true)
    expect(SHELL_CORE_MENU_KEYS.has('employee-workflow')).toBe(true)
    expect(SHELL_CORE_MENU_KEYS.has('workflow-employee-space')).toBe(true)
    expect(SHELL_CORE_MENU_KEYS.has('other-tools')).toBe(false)
    expect(SHELL_CORE_MENU_KEYS.has('workflow-visualization')).toBe(false)
  })

  it('host business keys are not shell core', () => {
    expect(isHostBusinessMenuKey('products')).toBe(true)
    expect(isHostBusinessMenuKey('shipment-records')).toBe(true)
    expect(SHELL_CORE_MENU_KEYS.has('products')).toBe(false)
  })

  describe('generic edition (milestone I)', () => {
    afterEach(() => {
      vi.unstubAllEnvs()
      localStorage.clear()
    })

    it('isGenericEditionBuild reads VITE_XCAGI_DEFAULT_PLATFORM_SHELL', () => {
      vi.stubEnv('VITE_XCAGI_EDITION', 'generic')
      vi.stubEnv('VITE_XCAGI_DEFAULT_PLATFORM_SHELL', '1')
      expect(isGenericEditionBuild()).toBe(true)
    })

    it('bootstrap sets shell mode in localStorage', () => {
      vi.stubEnv('VITE_XCAGI_EDITION', 'generic')
      vi.stubEnv('VITE_XCAGI_DEFAULT_PLATFORM_SHELL', '1')
      vi.stubEnv('VITE_XCAGI_PRODUCT_SKU', '')
      bootstrapGenericEditionDefaults()
      expect(localStorage.getItem(LS_PLATFORM_SHELL_MODE)).toBe('1')
      expect(isPlatformShellModeEnabled()).toBe(true)
    })

    it('bootstrap respects user opt-out', () => {
      vi.stubEnv('VITE_XCAGI_DEFAULT_PLATFORM_SHELL', '1')
      localStorage.setItem(LS_PLATFORM_SHELL_MODE, '0')
      bootstrapEditionDefaults()
      expect(localStorage.getItem(LS_PLATFORM_SHELL_MODE)).toBe('0')
      expect(isPlatformShellModeEnabled()).toBe(false)
    })
  })

  describe('minimal edition (milestone Q)', () => {
    afterEach(() => {
      vi.unstubAllEnvs()
      localStorage.clear()
    })

    it('isMinimalEditionBuild reads VITE_XCAGI_EDITION', () => {
      vi.stubEnv('VITE_XCAGI_EDITION', 'minimal')
      vi.stubEnv('VITE_XCAGI_DEFAULT_PLATFORM_SHELL', '1')
      vi.stubEnv('VITE_XCAGI_PRODUCT_SKU', '')
      expect(isMinimalEditionBuild()).toBe(true)
      expect(isPlatformShellModeEnabled()).toBe(true)
    })

  it('bootstrapMinimal sets shell mode', () => {
    vi.stubEnv('VITE_XCAGI_EDITION', 'minimal')
    vi.stubEnv('VITE_XCAGI_DEFAULT_PLATFORM_SHELL', '1')
    bootstrapMinimalEditionDefaults()
    expect(localStorage.getItem(LS_PLATFORM_SHELL_MODE)).toBe('1')
    })
  })

  it('expands ERP menu keys when account custom mod is installed', async () => {
    const { resolvePlatformShellMenuKeys, INDUSTRY_DELIVERY_ERP_MENU_KEYS } = await import(
      './platformShellMode'
    )
    const bare = resolvePlatformShellMenuKeys([])
    expect(bare.has('products')).toBe(false)
    const withCustom = resolvePlatformShellMenuKeys(['taiyangniao-pro', 'attendance-industry'])
    expect(withCustom.has('products')).toBe(true)
    expect(withCustom.has('customers')).toBe(true)
    for (const k of INDUSTRY_DELIVERY_ERP_MENU_KEYS) {
      expect(withCustom.has(k)).toBe(true)
    }
  })

  it('expands ERP menu keys once onboarding step 3 (host pack) is acknowledged', async () => {
    const { resolvePlatformShellMenuKeys, shouldExposeIndustrySidebar } = await import(
      './platformShellMode'
    )
    // 未走引导、未装定制：保持壳 4 项
    expect(shouldExposeIndustrySidebar(['attendance-industry'], false)).toBe(false)
    expect(resolvePlatformShellMenuKeys(['attendance-industry'], false).has('products')).toBe(false)
    // 第三步「补基础线」确认后：即便没有定制 Mod，主导航也长出行业业务项
    expect(shouldExposeIndustrySidebar(['attendance-industry'], true)).toBe(true)
    expect(resolvePlatformShellMenuKeys(['attendance-industry'], true).has('products')).toBe(true)
  })

  it('isIndustryDeliveryRouteName honours host pack acknowledgement', async () => {
    const { isIndustryDeliveryRouteName } = await import('./platformShellMode')
    expect(isIndustryDeliveryRouteName('products', [], false)).toBe(false)
    expect(isIndustryDeliveryRouteName('products', [], true)).toBe(true)
    expect(isIndustryDeliveryRouteName('products', ['taiyangniao-pro'], false)).toBe(true)
    // 非交付路由始终不放行
    expect(isIndustryDeliveryRouteName('not-a-route', [], true)).toBe(false)
  })
})
