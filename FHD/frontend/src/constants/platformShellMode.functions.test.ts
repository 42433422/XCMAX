import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const {
  mockReadBuildEdition,
  mockShouldAutoEnableEditionPlatformShell,
  mockShouldAutoEnableMinimalPlatformShell,
  mockShouldAutoEnablePlatformShell,
  mockHasInstalledAccountCustomMod,
  mockRemoveTenantScopedStorageItem,
} = vi.hoisted(() => ({
  mockReadBuildEdition: vi.fn(() => 'full'),
  mockShouldAutoEnableEditionPlatformShell: vi.fn(() => false),
  mockShouldAutoEnableMinimalPlatformShell: vi.fn(() => false),
  mockShouldAutoEnablePlatformShell: vi.fn(() => false),
  mockHasInstalledAccountCustomMod: vi.fn(() => false),
  mockRemoveTenantScopedStorageItem: vi.fn(),
}))

vi.mock('@/constants/genericModPack', () => ({
  readBuildEdition: mockReadBuildEdition,
  shouldAutoEnableEditionPlatformShell: mockShouldAutoEnableEditionPlatformShell,
  shouldAutoEnableMinimalPlatformShell: mockShouldAutoEnableMinimalPlatformShell,
  shouldAutoEnablePlatformShell: mockShouldAutoEnablePlatformShell,
  hasInstalledAccountCustomMod: mockHasInstalledAccountCustomMod,
}))

vi.mock('@/utils/tenantStorageScope', () => ({
  removeTenantScopedStorageItem: mockRemoveTenantScopedStorageItem,
}))

vi.mock('@/utils/xcagiStorageKeys', () => ({
  XCAGI_ACTIVE_EXTENSION_MOD_ID_KEY: 'xcagi_active_extension_mod_id',
}))

import {
  LS_PLATFORM_SHELL_MODE,
  LS_PLATFORM_SHELL_AUTO_GENERIC,
  LS_PLATFORM_SHELL_AUTO_MINIMAL,
  SHELL_CORE_MENU_KEYS,
  SHELL_CORE_ROUTE_NAMES,
  INDUSTRY_DELIVERY_ERP_MENU_KEYS,
  INDUSTRY_DELIVERY_ROUTE_NAMES,
  shouldExposeIndustrySidebar,
  resolvePlatformShellMenuKeys,
  isIndustryDeliveryRouteName,
  readPlatformShellModeFromStorage,
  isMinimalEditionBuild,
  isGenericEditionBuild,
  isShellEditionBuild,
  bootstrapMinimalEditionDefaults,
  bootstrapGenericEditionDefaults,
  bootstrapEditionDefaults,
  isEnterpriseProductSkuBuild,
  bootstrapEnterpriseShellDefaults,
  bootstrapAdminConsoleShellDefaults,
  isPlatformShellModeEnabled,
  applyMinimalPackPlatformShell,
  applyGenericPackPlatformShell,
  applyEditionPackPlatformShell,
  setPlatformShellModeEnabled,
  isHostBusinessMenuKey,
} from './platformShellMode'

describe('platformShellMode constants', () => {
  it('exposes LS_PLATFORM_SHELL_MODE key', () => {
    expect(LS_PLATFORM_SHELL_MODE).toBe('xcagi_platform_shell_mode')
  })

  it('exposes LS_PLATFORM_SHELL_AUTO_GENERIC key', () => {
    expect(LS_PLATFORM_SHELL_AUTO_GENERIC).toBe('xcagi_platform_shell_auto_generic')
  })

  it('exposes LS_PLATFORM_SHELL_AUTO_MINIMAL key', () => {
    expect(LS_PLATFORM_SHELL_AUTO_MINIMAL).toBe('xcagi_platform_shell_auto_minimal')
  })

  it('SHELL_CORE_MENU_KEYS contains expected core keys', () => {
    expect(SHELL_CORE_MENU_KEYS.has('chat')).toBe(true)
    expect(SHELL_CORE_MENU_KEYS.has('persy-knowledge')).toBe(true)
    expect(SHELL_CORE_MENU_KEYS.has('business-docking')).toBe(true)
    expect(SHELL_CORE_MENU_KEYS.has('settings')).toBe(true)
    expect(SHELL_CORE_MENU_KEYS.has('mod-store')).toBe(true)
    expect(SHELL_CORE_MENU_KEYS.has('login')).toBe(true)
  })

  it('SHELL_CORE_ROUTE_NAMES is a superset of SHELL_CORE_MENU_KEYS', () => {
    for (const k of SHELL_CORE_MENU_KEYS) {
      expect(SHELL_CORE_ROUTE_NAMES.has(k)).toBe(true)
    }
  })

  it('SHELL_CORE_ROUTE_NAMES contains additional route names', () => {
    expect(SHELL_CORE_ROUTE_NAMES.has('product-onboarding')).toBe(true)
    expect(SHELL_CORE_ROUTE_NAMES.has('mod-landing')).toBe(true)
    expect(SHELL_CORE_ROUTE_NAMES.has('login-help')).toBe(true)
    expect(SHELL_CORE_ROUTE_NAMES.has('login-register')).toBe(true)
  })

  it('INDUSTRY_DELIVERY_ERP_MENU_KEYS contains products and customers', () => {
    expect(INDUSTRY_DELIVERY_ERP_MENU_KEYS).toContain('products')
    expect(INDUSTRY_DELIVERY_ERP_MENU_KEYS).toContain('customers')
    expect(INDUSTRY_DELIVERY_ERP_MENU_KEYS).toContain('orders')
  })

  it('INDUSTRY_DELIVERY_ROUTE_NAMES is a superset of INDUSTRY_DELIVERY_ERP_MENU_KEYS', () => {
    for (const k of INDUSTRY_DELIVERY_ERP_MENU_KEYS) {
      expect(INDUSTRY_DELIVERY_ROUTE_NAMES.has(k)).toBe(true)
    }
  })

  it('INDUSTRY_DELIVERY_ROUTE_NAMES contains extra routes like inventory', () => {
    expect(SHELL_CORE_ROUTE_NAMES.has('business-docking')).toBe(true)
    expect(INDUSTRY_DELIVERY_ROUTE_NAMES.has('inventory')).toBe(true)
    expect(INDUSTRY_DELIVERY_ROUTE_NAMES.has('kitten-finance')).toBe(true)
    expect(INDUSTRY_DELIVERY_ROUTE_NAMES.has('workflow-visualization')).toBe(true)
  })
})

describe('shouldExposeIndustrySidebar', () => {
  afterEach(() => {
    mockHasInstalledAccountCustomMod.mockReset()
  })

  it('returns true when hostPackAcknowledged is true (short-circuit)', () => {
    mockHasInstalledAccountCustomMod.mockReturnValue(false)
    expect(shouldExposeIndustrySidebar([], true)).toBe(true)
    expect(mockHasInstalledAccountCustomMod).not.toHaveBeenCalled()
  })

  it('returns true when hostPackAcknowledged is true even with empty mods', () => {
    expect(shouldExposeIndustrySidebar([], true)).toBe(true)
  })

  it('returns false when no acknowledgement and no custom mod installed', () => {
    mockHasInstalledAccountCustomMod.mockReturnValue(false)
    expect(shouldExposeIndustrySidebar(['other-mod'], false)).toBe(false)
  })

  it('returns true when no acknowledgement but custom mod installed', () => {
    mockHasInstalledAccountCustomMod.mockReturnValue(true)
    expect(shouldExposeIndustrySidebar(['sz-qsm-pro'], false)).toBe(true)
  })

  it('returns true when the accessories packaging industry profile is installed', () => {
    mockHasInstalledAccountCustomMod.mockReturnValue(false)
    expect(shouldExposeIndustrySidebar(['accessories-packaging-industry'], false)).toBe(true)
  })

  it('defaults hostPackAcknowledged to false', () => {
    mockHasInstalledAccountCustomMod.mockReturnValue(false)
    expect(shouldExposeIndustrySidebar([])).toBe(false)
  })
})

describe('resolvePlatformShellMenuKeys', () => {
  afterEach(() => {
    mockHasInstalledAccountCustomMod.mockReset()
  })

  it('returns only core keys when industry sidebar not exposed', () => {
    mockHasInstalledAccountCustomMod.mockReturnValue(false)
    const keys = resolvePlatformShellMenuKeys([], false)
    expect(keys.size).toBe(SHELL_CORE_MENU_KEYS.size)
    for (const k of SHELL_CORE_MENU_KEYS) {
      expect(keys.has(k)).toBe(true)
    }
  })

  it('returns core + industry keys when hostPackAcknowledged', () => {
    mockHasInstalledAccountCustomMod.mockReturnValue(false)
    const keys = resolvePlatformShellMenuKeys([], true)
    expect(keys.size).toBeGreaterThan(SHELL_CORE_MENU_KEYS.size)
    expect(keys.has('products')).toBe(true)
    expect(keys.has('customers')).toBe(true)
  })

  it('returns core + industry keys when custom mod installed', () => {
    mockHasInstalledAccountCustomMod.mockReturnValue(true)
    const keys = resolvePlatformShellMenuKeys(['sz-qsm-pro'], false)
    expect(keys.has('products')).toBe(true)
  })

  it('returns a new Set (does not mutate SHELL_CORE_MENU_KEYS)', () => {
    mockHasInstalledAccountCustomMod.mockReturnValue(false)
    const beforeSize = SHELL_CORE_MENU_KEYS.size
    resolvePlatformShellMenuKeys(['taiyangniao-pro'], true)
    expect(SHELL_CORE_MENU_KEYS.size).toBe(beforeSize)
    expect(SHELL_CORE_MENU_KEYS.has('products')).toBe(false)
  })
})

describe('isIndustryDeliveryRouteName', () => {
  afterEach(() => {
    mockHasInstalledAccountCustomMod.mockReset()
  })

  it('returns false for empty route name', () => {
    expect(isIndustryDeliveryRouteName('', [], true)).toBe(false)
  })

  it('returns false for whitespace-only route name', () => {
    expect(isIndustryDeliveryRouteName('   ', [], true)).toBe(false)
  })

  it('returns false when route name is not in INDUSTRY_DELIVERY_ROUTE_NAMES', () => {
    expect(isIndustryDeliveryRouteName('unknown-route', [], true)).toBe(false)
  })

  it('returns false when route is industry but industry sidebar not exposed', () => {
    mockHasInstalledAccountCustomMod.mockReturnValue(false)
    expect(isIndustryDeliveryRouteName('products', [], false)).toBe(false)
  })

  it('returns true when route is industry and industry sidebar exposed via acknowledgement', () => {
    mockHasInstalledAccountCustomMod.mockReturnValue(false)
    expect(isIndustryDeliveryRouteName('products', [], true)).toBe(true)
  })

  it('returns true when route is industry and custom mod installed', () => {
    mockHasInstalledAccountCustomMod.mockReturnValue(true)
    expect(isIndustryDeliveryRouteName('inventory', ['sz-qsm-pro'], false)).toBe(true)
  })

  it('returns true when route is industry and accessories packaging profile is installed', () => {
    mockHasInstalledAccountCustomMod.mockReturnValue(false)
    expect(isIndustryDeliveryRouteName('inventory', ['accessories-packaging-industry'], false)).toBe(true)
  })

  it('trims route name before checking', () => {
    mockHasInstalledAccountCustomMod.mockReturnValue(false)
    expect(isIndustryDeliveryRouteName('  products  ', [], true)).toBe(true)
  })
})

describe('readPlatformShellModeFromStorage', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('returns false when key not set', () => {
    expect(readPlatformShellModeFromStorage()).toBe(false)
  })

  it('returns true when key is "1"', () => {
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '1')
    expect(readPlatformShellModeFromStorage()).toBe(true)
  })

  it('returns false when key is "0"', () => {
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '0')
    expect(readPlatformShellModeFromStorage()).toBe(false)
  })

  it('returns false when key is any other value', () => {
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, 'yes')
    expect(readPlatformShellModeFromStorage()).toBe(false)
  })
})

describe('isMinimalEditionBuild', () => {
  afterEach(() => {
    mockReadBuildEdition.mockReset()
  })

  it('returns true when edition is minimal', () => {
    mockReadBuildEdition.mockReturnValue('minimal')
    expect(isMinimalEditionBuild()).toBe(true)
  })

  it('returns false when edition is generic', () => {
    mockReadBuildEdition.mockReturnValue('generic')
    expect(isMinimalEditionBuild()).toBe(false)
  })

  it('returns false when edition is full', () => {
    mockReadBuildEdition.mockReturnValue('full')
    expect(isMinimalEditionBuild()).toBe(false)
  })
})

describe('isGenericEditionBuild', () => {
  afterEach(() => {
    mockReadBuildEdition.mockReset()
  })

  it('returns true when edition is generic', () => {
    mockReadBuildEdition.mockReturnValue('generic')
    expect(isGenericEditionBuild()).toBe(true)
  })

  it('returns false when edition is minimal', () => {
    mockReadBuildEdition.mockReturnValue('minimal')
    expect(isGenericEditionBuild()).toBe(false)
  })

  it('returns false when edition is full and env not set', () => {
    mockReadBuildEdition.mockReturnValue('full')
    expect(isGenericEditionBuild()).toBe(false)
  })
})

describe('isShellEditionBuild', () => {
  afterEach(() => {
    mockReadBuildEdition.mockReset()
  })

  it('returns false when edition is minimal', () => {
    mockReadBuildEdition.mockReturnValue('minimal')
    expect(isShellEditionBuild()).toBe(false)
  })

  it('returns false when edition is generic', () => {
    mockReadBuildEdition.mockReturnValue('generic')
    expect(isShellEditionBuild()).toBe(false)
  })

  it('returns false when edition is full', () => {
    mockReadBuildEdition.mockReturnValue('full')
    expect(isShellEditionBuild()).toBe(false)
  })
})

describe('bootstrapMinimalEditionDefaults', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  afterEach(() => {
    mockReadBuildEdition.mockReset()
  })

  it('clears shell mode when edition is full', () => {
    mockReadBuildEdition.mockReturnValue('full')
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '1')
    bootstrapMinimalEditionDefaults()
    expect(localStorage.getItem(LS_PLATFORM_SHELL_MODE)).toBe('0')
  })

  it('clears shell mode when edition is minimal', () => {
    mockReadBuildEdition.mockReturnValue('minimal')
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '1')
    localStorage.setItem(LS_PLATFORM_SHELL_AUTO_MINIMAL, 'minimal_edition_build')
    bootstrapMinimalEditionDefaults()
    expect(localStorage.getItem(LS_PLATFORM_SHELL_MODE)).toBe('0')
    expect(localStorage.getItem(LS_PLATFORM_SHELL_AUTO_MINIMAL)).toBeNull()
  })

  it('keeps shell mode off when it was already 0', () => {
    mockReadBuildEdition.mockReturnValue('minimal')
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '0')
    bootstrapMinimalEditionDefaults()
    expect(localStorage.getItem(LS_PLATFORM_SHELL_MODE)).toBe('0')
    expect(localStorage.getItem(LS_PLATFORM_SHELL_AUTO_MINIMAL)).toBeNull()
  })
})

describe('bootstrapGenericEditionDefaults', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  afterEach(() => {
    mockReadBuildEdition.mockReset()
  })

  it('clears shell mode when edition is full', () => {
    mockReadBuildEdition.mockReturnValue('full')
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '1')
    bootstrapGenericEditionDefaults()
    expect(localStorage.getItem(LS_PLATFORM_SHELL_MODE)).toBe('0')
  })

  it('clears shell mode when edition is minimal', () => {
    mockReadBuildEdition.mockReturnValue('minimal')
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '1')
    bootstrapGenericEditionDefaults()
    expect(localStorage.getItem(LS_PLATFORM_SHELL_MODE)).toBe('0')
  })

  it('clears shell mode when edition is generic', () => {
    mockReadBuildEdition.mockReturnValue('generic')
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '1')
    localStorage.setItem(LS_PLATFORM_SHELL_AUTO_GENERIC, 'generic_edition_build')
    bootstrapGenericEditionDefaults()
    expect(localStorage.getItem(LS_PLATFORM_SHELL_MODE)).toBe('0')
    expect(localStorage.getItem(LS_PLATFORM_SHELL_AUTO_GENERIC)).toBeNull()
  })

  it('keeps shell mode off when it was already 0', () => {
    mockReadBuildEdition.mockReturnValue('generic')
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '0')
    bootstrapGenericEditionDefaults()
    expect(localStorage.getItem(LS_PLATFORM_SHELL_MODE)).toBe('0')
  })
})

describe('bootstrapEditionDefaults', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  afterEach(() => {
    mockReadBuildEdition.mockReset()
  })

  it('clears shell mode for a full edition', () => {
    mockReadBuildEdition.mockReturnValue('full')
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '1')
    bootstrapEditionDefaults()
    expect(localStorage.getItem(LS_PLATFORM_SHELL_MODE)).toBe('0')
  })

  it('clears shell mode when edition is minimal', () => {
    mockReadBuildEdition.mockReturnValue('minimal')
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '1')
    bootstrapEditionDefaults()
    expect(localStorage.getItem(LS_PLATFORM_SHELL_MODE)).toBe('0')
    expect(localStorage.getItem(LS_PLATFORM_SHELL_AUTO_MINIMAL)).toBeNull()
  })

  it('clears shell mode when edition is generic', () => {
    mockReadBuildEdition.mockReturnValue('generic')
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '1')
    bootstrapEditionDefaults()
    expect(localStorage.getItem(LS_PLATFORM_SHELL_MODE)).toBe('0')
    expect(localStorage.getItem(LS_PLATFORM_SHELL_AUTO_GENERIC)).toBeNull()
  })
})

describe('isEnterpriseProductSkuBuild', () => {
  it('returns true when VITE_XCAGI_PRODUCT_SKU is enterprise', () => {
    vi.stubEnv('VITE_XCAGI_PRODUCT_SKU', 'enterprise')
    expect(isEnterpriseProductSkuBuild()).toBe(true)
    vi.unstubAllEnvs()
  })

  it('returns true when VITE_XCAGI_PRODUCT_SKU is ENTERPRISE (case-insensitive)', () => {
    vi.stubEnv('VITE_XCAGI_PRODUCT_SKU', 'ENTERPRISE')
    expect(isEnterpriseProductSkuBuild()).toBe(true)
    vi.unstubAllEnvs()
  })

  it('returns false when VITE_XCAGI_PRODUCT_SKU is personal', () => {
    vi.stubEnv('VITE_XCAGI_PRODUCT_SKU', 'personal')
    expect(isEnterpriseProductSkuBuild()).toBe(false)
    vi.unstubAllEnvs()
  })

  it('returns false when VITE_XCAGI_PRODUCT_SKU is empty', () => {
    vi.stubEnv('VITE_XCAGI_PRODUCT_SKU', '')
    expect(isEnterpriseProductSkuBuild()).toBe(false)
    vi.unstubAllEnvs()
  })

  it('returns false when VITE_XCAGI_PRODUCT_SKU is whitespace', () => {
    vi.stubEnv('VITE_XCAGI_PRODUCT_SKU', '   ')
    expect(isEnterpriseProductSkuBuild()).toBe(false)
    vi.unstubAllEnvs()
  })
})

describe('bootstrapEnterpriseShellDefaults', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  afterEach(() => {
    mockReadBuildEdition.mockReset()
    vi.unstubAllEnvs()
  })

  it('does nothing when SKU is not enterprise', () => {
    vi.stubEnv('VITE_XCAGI_PRODUCT_SKU', 'personal')
    mockReadBuildEdition.mockReturnValue('full')
    bootstrapEnterpriseShellDefaults()
    expect(localStorage.getItem(LS_PLATFORM_SHELL_MODE)).toBeNull()
  })

  it('clears shell mode when SKU is enterprise even if edition env is minimal', () => {
    vi.stubEnv('VITE_XCAGI_PRODUCT_SKU', 'enterprise')
    mockReadBuildEdition.mockReturnValue('minimal')
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '1')
    bootstrapEnterpriseShellDefaults()
    expect(localStorage.getItem(LS_PLATFORM_SHELL_MODE)).toBe('0')
  })

  it('sets shell mode to 0 when SKU is enterprise and edition is full', () => {
    vi.stubEnv('VITE_XCAGI_PRODUCT_SKU', 'enterprise')
    mockReadBuildEdition.mockReturnValue('full')
    bootstrapEnterpriseShellDefaults()
    expect(localStorage.getItem(LS_PLATFORM_SHELL_MODE)).toBe('0')
  })

  it('clears shell mode when SKU is enterprise and edition env is generic', () => {
    vi.stubEnv('VITE_XCAGI_PRODUCT_SKU', 'enterprise')
    mockReadBuildEdition.mockReturnValue('generic')
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '1')
    bootstrapEnterpriseShellDefaults()
    expect(localStorage.getItem(LS_PLATFORM_SHELL_MODE)).toBe('0')
  })
})

describe('bootstrapAdminConsoleShellDefaults', () => {
  beforeEach(() => {
    localStorage.clear()
    mockRemoveTenantScopedStorageItem.mockClear()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('does nothing when VITE_XCMAX_ADMIN_CONSOLE is not 1', () => {
    vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '')
    bootstrapAdminConsoleShellDefaults()
    expect(localStorage.getItem(LS_PLATFORM_SHELL_MODE)).toBeNull()
    expect(mockRemoveTenantScopedStorageItem).not.toHaveBeenCalled()
  })

  it('disables shell and clears facade flags when VITE_XCMAX_ADMIN_CONSOLE is 1', () => {
    vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '1')
    bootstrapAdminConsoleShellDefaults()
    expect(localStorage.getItem(LS_PLATFORM_SHELL_MODE)).toBe('0')
    expect(localStorage.getItem('xcagi_lan_mod_facade_enabled')).toBe('0')
    expect(localStorage.getItem('xcagi_planner_mod_facade_enabled')).toBe('0')
    expect(localStorage.getItem('xcagi_erp_domain_mod_facade_enabled')).toBe('0')
    expect(localStorage.getItem('xcagi_workflow_viz_mod_pages_enabled')).toBe('0')
    expect(mockRemoveTenantScopedStorageItem).toHaveBeenCalledWith('xcagi_active_extension_mod_id')
  })
})

describe('isPlatformShellModeEnabled', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  afterEach(() => {
    mockReadBuildEdition.mockReset()
    vi.unstubAllEnvs()
  })

  it('returns false when SKU is enterprise and edition is full', () => {
    vi.stubEnv('VITE_XCAGI_PRODUCT_SKU', 'enterprise')
    mockReadBuildEdition.mockReturnValue('full')
    expect(isPlatformShellModeEnabled()).toBe(false)
  })

  it('returns false when URL has shell param', () => {
    const original = window.location.href
    window.history.replaceState({}, '', '/?shell=1')
    mockReadBuildEdition.mockReturnValue('full')
    vi.stubEnv('VITE_XCAGI_PRODUCT_SKU', '')
    expect(isPlatformShellModeEnabled()).toBe(false)
    window.history.replaceState({}, '', original)
  })

  it('returns false when URL has full param', () => {
    const original = window.location.href
    window.history.replaceState({}, '', '/?full=1')
    mockReadBuildEdition.mockReturnValue('full')
    vi.stubEnv('VITE_XCAGI_PRODUCT_SKU', '')
    expect(isPlatformShellModeEnabled()).toBe(false)
    window.history.replaceState({}, '', original)
  })

  it('returns false when localStorage is "1"', () => {
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '1')
    mockReadBuildEdition.mockReturnValue('full')
    vi.stubEnv('VITE_XCAGI_PRODUCT_SKU', '')
    expect(isPlatformShellModeEnabled()).toBe(false)
  })

  it('returns false when localStorage is "0"', () => {
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '0')
    mockReadBuildEdition.mockReturnValue('full')
    vi.stubEnv('VITE_XCAGI_PRODUCT_SKU', '')
    expect(isPlatformShellModeEnabled()).toBe(false)
  })

  it('returns false when VITE_XCAGI_PLATFORM_SHELL is "1"', () => {
    vi.stubEnv('VITE_XCAGI_PLATFORM_SHELL', '1')
    mockReadBuildEdition.mockReturnValue('full')
    vi.stubEnv('VITE_XCAGI_PRODUCT_SKU', '')
    expect(isPlatformShellModeEnabled()).toBe(false)
  })

  it('returns false when VITE_XCAGI_PLATFORM_SHELL is "true"', () => {
    vi.stubEnv('VITE_XCAGI_PLATFORM_SHELL', 'true')
    mockReadBuildEdition.mockReturnValue('full')
    vi.stubEnv('VITE_XCAGI_PRODUCT_SKU', '')
    expect(isPlatformShellModeEnabled()).toBe(false)
  })

  it('returns false when VITE_XCAGI_PLATFORM_SHELL is "yes"', () => {
    vi.stubEnv('VITE_XCAGI_PLATFORM_SHELL', 'yes')
    mockReadBuildEdition.mockReturnValue('full')
    vi.stubEnv('VITE_XCAGI_PRODUCT_SKU', '')
    expect(isPlatformShellModeEnabled()).toBe(false)
  })

  it('returns false when edition is minimal', () => {
    mockReadBuildEdition.mockReturnValue('minimal')
    vi.stubEnv('VITE_XCAGI_PRODUCT_SKU', '')
    vi.stubEnv('VITE_XCAGI_PLATFORM_SHELL', '')
    expect(isPlatformShellModeEnabled()).toBe(false)
  })

  it('returns false when edition is generic', () => {
    mockReadBuildEdition.mockReturnValue('generic')
    vi.stubEnv('VITE_XCAGI_PRODUCT_SKU', '')
    vi.stubEnv('VITE_XCAGI_PLATFORM_SHELL', '')
    expect(isPlatformShellModeEnabled()).toBe(false)
  })

  it('returns false when full edition, no env, no storage, no URL params', () => {
    mockReadBuildEdition.mockReturnValue('full')
    vi.stubEnv('VITE_XCAGI_PRODUCT_SKU', '')
    vi.stubEnv('VITE_XCAGI_PLATFORM_SHELL', '')
    vi.stubEnv('VITE_XCAGI_DEFAULT_PLATFORM_SHELL', '')
    expect(isPlatformShellModeEnabled()).toBe(false)
  })
})

describe('applyMinimalPackPlatformShell', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  afterEach(() => {
    mockShouldAutoEnableMinimalPlatformShell.mockReset()
  })

  it('clears shell mode when auto-enable is false', () => {
    mockShouldAutoEnableMinimalPlatformShell.mockReturnValue(false)
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '1')
    applyMinimalPackPlatformShell(['other'])
    expect(localStorage.getItem(LS_PLATFORM_SHELL_MODE)).toBe('0')
  })

  it('does not turn shell mode on when auto-enable is true', () => {
    mockShouldAutoEnableMinimalPlatformShell.mockReturnValue(true)
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '1')
    applyMinimalPackPlatformShell(['xcagi-planner-bridge'])
    expect(localStorage.getItem(LS_PLATFORM_SHELL_MODE)).toBe('0')
    expect(localStorage.getItem(LS_PLATFORM_SHELL_AUTO_MINIMAL)).toBeNull()
  })

  it('keeps shell mode off when it was already 0', () => {
    mockShouldAutoEnableMinimalPlatformShell.mockReturnValue(true)
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '0')
    applyMinimalPackPlatformShell(['xcagi-planner-bridge'])
    expect(localStorage.getItem(LS_PLATFORM_SHELL_MODE)).toBe('0')
  })
})

describe('applyGenericPackPlatformShell', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  afterEach(() => {
    mockShouldAutoEnablePlatformShell.mockReset()
  })

  it('clears shell mode when auto-enable is false', () => {
    mockShouldAutoEnablePlatformShell.mockReturnValue(false)
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '1')
    applyGenericPackPlatformShell(['other'])
    expect(localStorage.getItem(LS_PLATFORM_SHELL_MODE)).toBe('0')
  })

  it('does not turn shell mode on when auto-enable is true', () => {
    mockShouldAutoEnablePlatformShell.mockReturnValue(true)
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '1')
    applyGenericPackPlatformShell(['xcagi-planner-bridge'])
    expect(localStorage.getItem(LS_PLATFORM_SHELL_MODE)).toBe('0')
    expect(localStorage.getItem(LS_PLATFORM_SHELL_AUTO_GENERIC)).toBeNull()
  })

  it('keeps shell mode off when it was already 0', () => {
    mockShouldAutoEnablePlatformShell.mockReturnValue(true)
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '0')
    applyGenericPackPlatformShell(['xcagi-planner-bridge'])
    expect(localStorage.getItem(LS_PLATFORM_SHELL_MODE)).toBe('0')
  })
})

describe('applyEditionPackPlatformShell', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  afterEach(() => {
    mockReadBuildEdition.mockReset()
    mockShouldAutoEnableMinimalPlatformShell.mockReset()
    mockShouldAutoEnablePlatformShell.mockReset()
    vi.unstubAllEnvs()
  })

  it('clears shell mode when SKU is enterprise', () => {
    vi.stubEnv('VITE_XCAGI_PRODUCT_SKU', 'enterprise')
    mockReadBuildEdition.mockReturnValue('full')
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '1')
    applyEditionPackPlatformShell([])
    expect(localStorage.getItem(LS_PLATFORM_SHELL_MODE)).toBe('0')
  })

  it('clears shell mode when edition is minimal', () => {
    mockReadBuildEdition.mockReturnValue('minimal')
    mockShouldAutoEnableMinimalPlatformShell.mockReturnValue(true)
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '1')
    applyEditionPackPlatformShell(['xcagi-planner-bridge'])
    expect(localStorage.getItem(LS_PLATFORM_SHELL_MODE)).toBe('0')
    expect(localStorage.getItem(LS_PLATFORM_SHELL_AUTO_MINIMAL)).toBeNull()
  })

  it('clears shell mode when edition is generic', () => {
    mockReadBuildEdition.mockReturnValue('generic')
    mockShouldAutoEnablePlatformShell.mockReturnValue(true)
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '1')
    applyEditionPackPlatformShell(['xcagi-planner-bridge'])
    expect(localStorage.getItem(LS_PLATFORM_SHELL_MODE)).toBe('0')
    expect(localStorage.getItem(LS_PLATFORM_SHELL_AUTO_GENERIC)).toBeNull()
  })

  it('clears shell mode for a full edition', () => {
    mockReadBuildEdition.mockReturnValue('full')
    mockShouldAutoEnableMinimalPlatformShell.mockReturnValue(false)
    mockShouldAutoEnablePlatformShell.mockReturnValue(false)
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '1')
    applyEditionPackPlatformShell([])
    expect(localStorage.getItem(LS_PLATFORM_SHELL_MODE)).toBe('0')
  })
})

describe('setPlatformShellModeEnabled', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('keeps shell mode off when asked to turn it on', () => {
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '1')
    setPlatformShellModeEnabled(true)
    expect(localStorage.getItem(LS_PLATFORM_SHELL_MODE)).toBe('0')
  })

  it('sets shell mode to "0" when on is false', () => {
    setPlatformShellModeEnabled(false)
    expect(localStorage.getItem(LS_PLATFORM_SHELL_MODE)).toBe('0')
  })

  it('overwrites previous value', () => {
    localStorage.setItem(LS_PLATFORM_SHELL_MODE, '1')
    setPlatformShellModeEnabled(false)
    expect(localStorage.getItem(LS_PLATFORM_SHELL_MODE)).toBe('0')
  })
})

describe('isHostBusinessMenuKey', () => {
  it('returns false for core menu keys', () => {
    expect(isHostBusinessMenuKey('chat')).toBe(false)
    expect(isHostBusinessMenuKey('settings')).toBe(false)
    expect(isHostBusinessMenuKey('mod-store')).toBe(false)
  })

  it('returns true for non-core (business) keys', () => {
    expect(isHostBusinessMenuKey('products')).toBe(true)
    expect(isHostBusinessMenuKey('customers')).toBe(true)
    expect(isHostBusinessMenuKey('unknown-key')).toBe(true)
  })

  it('returns true for empty string (not in core set)', () => {
    expect(isHostBusinessMenuKey('')).toBe(true)
  })
})
