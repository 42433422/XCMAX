import { describe, it, expect } from 'vitest'
import {
  isHostBridgeModId,
  isWorkflowEmployeeModId,
  isAuxEmployeePackModId,
  isEmployeePackListingModId,
  isSelectableExtensionModId,
  isHostFoundationEmployeePackId,
  catalogStoreCollection,
  hasInstalledClientPrimaryErpMod,
  hasInstalledSelectableExtensionMod,
  hasInstalledAccountCustomMod,
  normalizeModSidebarNavKey,
  expectedHostBridgeModIds,
  HOST_FOUNDATION_EMPLOYEE_PACK_ID,
  STORE_COLLECTION_HOST_FOUNDATION,
  STORE_COLLECTION_WORKFLOW_EMPLOYEE,
  STORE_COLLECTION_INDUSTRY_MOD,
} from './genericModPack'

describe('genericModPack predicate branches', () => {
  it('isHostBridgeModId matches known set and -bridge suffix', () => {
    expect(isHostBridgeModId('')).toBe(false)
    expect(isHostBridgeModId('xcagi-erp-domain-bridge')).toBe(true)
    expect(isHostBridgeModId('xcagi-anything-bridge')).toBe(true)
    expect(isHostBridgeModId('taiyangniao-pro')).toBe(false)
  })

  it('isWorkflowEmployeeModId matches prefix', () => {
    expect(isWorkflowEmployeeModId('xcagi-workflow-employee-sales')).toBe(true)
    expect(isWorkflowEmployeeModId('random-mod')).toBe(false)
  })

  it('isAuxEmployeePackModId checks listing', () => {
    expect(isAuxEmployeePackModId('wechat-contacts-ai-employee')).toBe(true)
    expect(isAuxEmployeePackModId('nope')).toBe(false)
  })

  it('isEmployeePackListingModId covers all branches', () => {
    expect(isEmployeePackListingModId('')).toBe(false)
    expect(isEmployeePackListingModId(HOST_FOUNDATION_EMPLOYEE_PACK_ID)).toBe(true)
    expect(isEmployeePackListingModId('lan-gate-ai-employee')).toBe(true)
    expect(isEmployeePackListingModId('foo-generate-employee')).toBe(true)
    expect(isEmployeePackListingModId('csv-reader-employee')).toBe(true)
    expect(isEmployeePackListingModId('plain-industry-mod')).toBe(false)
  })

  it('isSelectableExtensionModId excludes bridges, workflow, packs', () => {
    expect(isSelectableExtensionModId('')).toBe(false)
    expect(isSelectableExtensionModId('xcagi-erp-domain-bridge')).toBe(false)
    expect(isSelectableExtensionModId('xcagi-workflow-employee-x')).toBe(false)
    expect(isSelectableExtensionModId('csv-reader-employee')).toBe(false)
    expect(isSelectableExtensionModId('attendance-industry')).toBe(true)
  })

  it('isHostFoundationEmployeePackId', () => {
    expect(isHostFoundationEmployeePackId(HOST_FOUNDATION_EMPLOYEE_PACK_ID)).toBe(true)
    expect(isHostFoundationEmployeePackId('x')).toBe(false)
  })

  it('catalogStoreCollection prefers explicit store_collection', () => {
    expect(catalogStoreCollection({ store_collection: 'custom' })).toBe('custom')
  })

  it('catalogStoreCollection maps employee_pack artifact', () => {
    expect(catalogStoreCollection({ artifact: 'employee_pack', config: { host_foundation_pack: true } })).toBe(
      STORE_COLLECTION_HOST_FOUNDATION,
    )
    expect(catalogStoreCollection({ artifact: 'employee_pack' })).toBe(STORE_COLLECTION_WORKFLOW_EMPLOYEE)
  })

  it('catalogStoreCollection maps by id', () => {
    expect(catalogStoreCollection({ id: HOST_FOUNDATION_EMPLOYEE_PACK_ID })).toBe(STORE_COLLECTION_HOST_FOUNDATION)
    expect(catalogStoreCollection({ id: 'xcagi-workflow-employee-x' })).toBe(STORE_COLLECTION_WORKFLOW_EMPLOYEE)
    expect(catalogStoreCollection({ id: 'xcagi-erp-domain-bridge' })).toBe('')
    expect(catalogStoreCollection({ id: 'plain-industry' })).toBe(STORE_COLLECTION_INDUSTRY_MOD)
  })

  it('hasInstalledClientPrimaryErpMod and selectable/account checks', () => {
    expect(hasInstalledClientPrimaryErpMod(['attendance-industry'])).toBe(true)
    expect(hasInstalledClientPrimaryErpMod(['nothing'])).toBe(false)
    expect(hasInstalledSelectableExtensionMod(['attendance-industry'])).toBe(true)
    expect(hasInstalledSelectableExtensionMod(['xcagi-erp-domain-bridge'])).toBe(false)
    expect(hasInstalledAccountCustomMod(['taiyangniao-pro'])).toBe(true)
    expect(hasInstalledAccountCustomMod(['x'])).toBe(false)
  })

  it('normalizeModSidebarNavKey strips double prefix', () => {
    expect(normalizeModSidebarNavKey('mod-mod-foo')).toBe('mod-foo')
    expect(normalizeModSidebarNavKey('mod-foo')).toBe('mod-foo')
    expect(normalizeModSidebarNavKey('')).toBe('')
  })

  it('expectedHostBridgeModIds returns array', () => {
    expect(Array.isArray(expectedHostBridgeModIds())).toBe(true)
  })
})
