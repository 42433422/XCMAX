import { describe, expect, it } from 'vitest'
import {
  AUX_EMPLOYEE_PACK_MOD_IDS,
  GENERIC_HOST_MOD_IDS,
  HOST_FOUNDATION_EMPLOYEE_PACK_ID,
  STORE_COLLECTION_INDUSTRY_MOD,
} from '@/constants/genericModPack'
import { OFFICE_AUX_PACK_1_PKG_IDS, OFFICE_EMPLOYEE_PKG_IDS } from '@/constants/officeEmployeePack'
import { WORKFLOW_EMPLOYEE_MOD_IDS } from '@/constants/workflowEmployeeMods'
import { marketItemType, type StoreModRow } from './useModStoreState'

function row(id: string, fields: Partial<StoreModRow> & { store_collection?: string } = {}): StoreModRow {
  return {
    id,
    name: id,
    version: '1.0.0',
    author: 'test',
    description: '',
    is_installed: true,
    source: 'local',
    ...fields,
  }
}

describe('marketItemType with the existing catalog taxonomy', () => {
  it.each(['mod', 'bundle'])('lists remote %s packages as modules', (artifact) => {
    expect(marketItemType(row('industry-extension', { artifact, source: 'remote', is_installed: false }))).toBe('module')
  })

  it('keeps employee packs in employees despite a stale industry collection', () => {
    expect(marketItemType(row('custom-employee', {
      artifact: 'employee_pack',
      store_collection: STORE_COLLECTION_INDUSTRY_MOD,
    }))).toBe('employee')
  })

  it.each([
    HOST_FOUNDATION_EMPLOYEE_PACK_ID,
    OFFICE_EMPLOYEE_PKG_IDS[0],
    OFFICE_AUX_PACK_1_PKG_IDS[0],
    WORKFLOW_EMPLOYEE_MOD_IDS[0],
    AUX_EMPLOYEE_PACK_MOD_IDS[0],
  ])('retains installed employee %s when local artifact metadata is absent', (id) => {
    expect(marketItemType(row(id))).toBe('employee')
  })

  it('retains an ordinary installed local module without artifact metadata', () => {
    expect(marketItemType(row('custom-local-extension'))).toBe('module')
  })

  it.each(['workflow_template', 'surface'])('excludes %s assets from package categories', (artifact) => {
    expect(marketItemType(row(`${artifact}-listing`, { artifact }))).toBeNull()
  })

  it('keeps host infrastructure bridges out of the market categories', () => {
    expect(marketItemType(row(GENERIC_HOST_MOD_IDS[0]))).toBeNull()
  })
})
