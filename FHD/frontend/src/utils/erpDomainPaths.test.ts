import { describe, expect, it, afterEach, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useModsStore } from '@/stores/mods'
import { erpDomainModStatusPath, resolveErpApiPathWhenReady, resolveErpApiBase, resolveErpApiPath } from './erpDomainPaths'
import { scopedActiveExtensionModStorageKey, writeActiveExtensionModIdToStorage } from '@/utils/xcagiStorageKeys'
import { setTenantStorageScopeCache } from '@/utils/tenantStorageScope'

const LS = 'xcagi_erp_domain_mod_facade_enabled'
const TEST_SCOPE = 'tenant:1'
const ACTIVE_LS = () => scopedActiveExtensionModStorageKey(TEST_SCOPE)

describe('erpDomainPaths', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.removeItem(LS)
    localStorage.removeItem(ACTIVE_LS())
  })

  beforeEach(() => {
    setActivePinia(createPinia())
    setTenantStorageScopeCache(TEST_SCOPE)
  })
  it.each(['/api/customers/list?page=1', '/api/products/list', '/api/shipment/shipment-records/units'])('waits for cold-start Mod routing before %s', async (path) => {
    const store = useModsStore()
    let release!: () => void
    const pending = new Promise<void>(resolve => { release = resolve })
    vi.spyOn(store, 'fetchMods').mockImplementation(async () => { await pending; store.mods = [{ id: 'xcagi-erp-domain-bridge' }] as typeof store.mods; return { ok: true } })
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ success: true, data: [{ id: 7 }] }), { headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetch)
    const { api } = await import('@/api/core'), result = api.get(path)
    expect(store.fetchMods).toHaveBeenCalledOnce()
    expect(fetch).not.toHaveBeenCalled()
    release()
    expect(await result).toEqual({ success: true, data: [{ id: 7 }] })
    expect(fetch.mock.calls[0][0]).toBe(`/api/mod/xcagi-erp-domain-bridge${path.slice(4)}`)
  })

  it('defaults to host /api when facade off', () => {
    expect(resolveErpApiBase()).toBe('/api')
    expect(resolveErpApiPath('/api/orders')).toBe('/api/orders')
    expect(resolveErpApiPath('/api/materials')).toBe('/api/materials')
  })

  it.each(['/api/products/list', '/api/shipment/shipment-records/units', '/api/orders?limit=200', '/api/purchase_units', '/api/orders/next_number?suffix=A'])('maps enabled facade %s', (path) => {
    localStorage.setItem(LS, '1')
    expect(resolveErpApiBase()).toBe('/api/mod/xcagi-erp-domain-bridge')
    expect(resolveErpApiPath(path)).toBe(`/api/mod/xcagi-erp-domain-bridge${path.slice(4)}`)
  })
  it.each(['/api/materials', '/api/print/label', '/api/approval/requests'])('preserves host-only %s without waiting for Mods', async (path) => {
    localStorage.setItem(LS, '1')
    const fetch = vi.spyOn(useModsStore(), 'fetchMods')
    expect(resolveErpApiPath(path)).toBe(path)
    expect(await resolveErpApiPathWhenReady(path)).toBe(path)
    expect(fetch).not.toHaveBeenCalled()
  })

  it('exposes mod status probe path', () => {
    expect(erpDomainModStatusPath()).toBe('/api/mod/xcagi-erp-domain-bridge/status')
  })

  it('prefers active protected client mod for products/customers/units; orders via erp bridge', () => {
    localStorage.setItem(LS, '1')
    writeActiveExtensionModIdToStorage('taiyangniao-pro', TEST_SCOPE)
    const ids = ['taiyangniao-pro', 'xcagi-erp-domain-bridge']
    expect(resolveErpApiBase(ids)).toBe('/api/mod/taiyangniao-pro')
    expect(resolveErpApiPath('/api/products/list', ids)).toBe('/api/mod/taiyangniao-pro/products/list')
    expect(resolveErpApiPath('/api/orders?limit=200', ids)).toBe('/api/mod/xcagi-erp-domain-bridge/orders?limit=200')
    expect(resolveErpApiPath('/api/shipment/shipment-records/units', ids)).toBe('/api/mod/taiyangniao-pro/shipment/shipment-records/units')
    expect(resolveErpApiPath('/api/purchase_units', ids)).toBe('/api/mod/taiyangniao-pro/purchase_units')
    expect(resolveErpApiPath('/api/shipment/shipment-records/records', ids)).toBe(
      '/api/mod/xcagi-erp-domain-bridge/shipment/shipment-records/records',
    )
  })

  it('falls back to erp bridge when client mod not in installed list', () => {
    writeActiveExtensionModIdToStorage('taiyangniao-pro', TEST_SCOPE)
    const ids = ['xcagi-erp-domain-bridge']
    expect(resolveErpApiPath('/api/customers/list', ids)).toBe('/api/mod/xcagi-erp-domain-bridge/customers/list')
  })

  it.each(['attendance-industry', ''])('routes industry shell %s via bridge', (active) => {
    writeActiveExtensionModIdToStorage(active, TEST_SCOPE)
    localStorage.removeItem(LS)
    const ids = ['attendance-industry', 'xcagi-erp-domain-bridge']
    expect(resolveErpApiBase(ids)).toBe('/api/mod/xcagi-erp-domain-bridge')
    for (const path of ['/api/customers/list', '/api/products/list', '/api/purchase_units', '/api/shipment/shipment-records/units']) expect(resolveErpApiPath(path, ids)).toBe(`/api/mod/xcagi-erp-domain-bridge${path.slice(4)}`)
  })
})
