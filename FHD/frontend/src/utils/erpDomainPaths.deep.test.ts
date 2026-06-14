import { describe, it, expect, vi, beforeEach } from 'vitest'

const facadeEnabled = { value: false }
const activeMod = { value: '' }
const protectedIds = new Set<string>()

vi.mock('@/constants/erpDomainMod', () => ({
  ERP_DOMAIN_BRIDGE_MOD_ID: 'xcagi-erp-domain-bridge',
  LEGACY_CLIENT_ERP_MOD_ID: 'legacy-erp',
  readErpDomainModFacadeEnabled: () => facadeEnabled.value,
}))
vi.mock('@/constants/genericModPack', () => ({
  CLIENT_PRIMARY_ERP_MOD_ID: 'client-primary-erp',
}))
vi.mock('@/constants/protectedMods', () => ({
  isProtectedClientModId: (id: string) => protectedIds.has(id),
  clientModProvidesErpApi: (id: string) => protectedIds.has(id),
}))
vi.mock('@/stores/hostConfig', () => ({
  clientModPolicies: { value: { client_primary_erp_mod_id: 'client-primary-erp' } },
}))
vi.mock('@/stores/mods', () => ({
  useModsStore: () => ({ mods: [] }),
}))
vi.mock('@/utils/xcagiStorageKeys', () => ({
  readActiveExtensionModIdFromStorage: () => activeMod.value,
}))

import {
  resolveErpApiBase,
  resolveErpApiPath,
  useErpDomainModFacade,
  erpDomainModStatusPath,
  readActiveExtensionModId,
} from './erpDomainPaths'

describe('erpDomainPaths deep branches', () => {
  beforeEach(() => {
    facadeEnabled.value = false
    activeMod.value = ''
    protectedIds.clear()
  })

  it('resolveErpApiBase returns /api by default', () => {
    expect(resolveErpApiBase([])).toBe('/api')
  })

  it('resolveErpApiBase returns facade when enabled', () => {
    facadeEnabled.value = true
    expect(resolveErpApiBase([])).toBe('/api/mod/xcagi-erp-domain-bridge')
  })

  it('resolveErpApiBase returns legacy mod base when installed', () => {
    expect(resolveErpApiBase(['legacy-erp'])).toBe('/api/mod/legacy-erp')
  })

  it('resolveErpApiBase routes active protected client mod to its base', () => {
    activeMod.value = 'taiyangniao-pro'
    protectedIds.add('taiyangniao-pro')
    expect(resolveErpApiBase(['taiyangniao-pro'])).toBe('/api/mod/taiyangniao-pro')
  })

  it('resolveErpApiBase falls back to bridge when client mod not installed', () => {
    activeMod.value = 'taiyangniao-pro'
    protectedIds.add('taiyangniao-pro')
    expect(resolveErpApiBase(['xcagi-erp-domain-bridge'])).toBe('/api/mod/xcagi-erp-domain-bridge')
  })

  it('resolveErpApiPath keeps host-only api unchanged', () => {
    expect(resolveErpApiPath('/api/materials/list')).toBe('/api/materials/list')
    expect(resolveErpApiPath('/api/auth/login')).toBe('/api/auth/login')
  })

  it('resolveErpApiPath keeps non-api path unchanged', () => {
    expect(resolveErpApiPath('/static/x.png')).toBe('/static/x.png')
  })

  it('resolveErpApiPath maps products to facade when enabled', () => {
    facadeEnabled.value = true
    expect(resolveErpApiPath('/api/products/list')).toBe('/api/mod/xcagi-erp-domain-bridge/products/list')
  })

  it('resolveErpApiPath preserves query suffix', () => {
    facadeEnabled.value = true
    expect(resolveErpApiPath('/api/orders?page=1')).toBe('/api/mod/xcagi-erp-domain-bridge/orders?page=1')
  })

  it('resolveErpApiPath wechat_contacts compat routes to facade', () => {
    expect(resolveErpApiPath('/api/wechat_contacts/list', ['xcagi-erp-domain-bridge'])).toContain(
      '/api/mod/xcagi-erp-domain-bridge',
    )
  })

  it('resolveErpApiPath orders go to bridge when client active', () => {
    activeMod.value = 'taiyangniao-pro'
    protectedIds.add('taiyangniao-pro')
    const out = resolveErpApiPath('/api/orders', ['taiyangniao-pro', 'xcagi-erp-domain-bridge'])
    expect(out).toBe('/api/mod/xcagi-erp-domain-bridge/orders')
  })

  it('useErpDomainModFacade reflects flag', () => {
    expect(useErpDomainModFacade()).toBe(false)
    facadeEnabled.value = true
    expect(useErpDomainModFacade()).toBe(true)
  })

  it('erpDomainModStatusPath returns status endpoint', () => {
    expect(erpDomainModStatusPath()).toBe('/api/mod/xcagi-erp-domain-bridge/status')
  })

  it('readActiveExtensionModId reads from storage', () => {
    activeMod.value = 'm-active'
    expect(readActiveExtensionModId()).toBe('m-active')
  })
})
