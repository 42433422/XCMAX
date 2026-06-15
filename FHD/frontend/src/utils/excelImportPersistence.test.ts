import { describe, it, expect, beforeEach } from 'vitest'
import {
  savePendingImport,
  getPendingImport,
  removePendingImport,
  cleanupExpiredImports,
  getAllPendingImports,
  type PendingExcelImport,
} from './excelImportPersistence'

function sampleImport(id: string, createdAt?: number): PendingExcelImport {
  return {
    pending_id: id,
    records: [{ sku: 'A1' }],
    excel_analysis: {
      file_name: 'test.xlsx',
      file_path: '/tmp/test.xlsx',
      sheet_name: 'Sheet1',
      fields: [],
      summary: 'summary',
    },
    created_at: createdAt ?? Date.now(),
    session_id: 'sess-1',
  }
}

describe('excelImportPersistence', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
  })

  it('saves and reads from sessionStorage', () => {
    const data = sampleImport('p1')
    savePendingImport(data)
    const loaded = getPendingImport('p1')
    expect(loaded?.pending_id).toBe('p1')
    expect(loaded?.records).toHaveLength(1)
  })

  it('falls back to localStorage when session missing', () => {
    const data = sampleImport('p2')
    const key = 'xcagi_excel_pending_import_p2'
    localStorage.setItem(key, JSON.stringify(data))
    const loaded = getPendingImport('p2')
    expect(loaded?.pending_id).toBe('p2')
    expect(sessionStorage.getItem(key)).toBeTruthy()
  })

  it('returns null for unknown id', () => {
    expect(getPendingImport('missing')).toBeNull()
  })

  it('removes pending import from both storages', () => {
    savePendingImport(sampleImport('p3'))
    removePendingImport('p3')
    expect(getPendingImport('p3')).toBeNull()
  })

  it('cleans expired imports older than 24h', () => {
    const old = sampleImport('old', Date.now() - 25 * 60 * 60 * 1000)
    const fresh = sampleImport('fresh')
    savePendingImport(old)
    savePendingImport(fresh)
    cleanupExpiredImports()
    expect(getPendingImport('old')).toBeNull()
    expect(getPendingImport('fresh')).not.toBeNull()
  })

  it('getAllPendingImports sorts by created_at desc', () => {
    savePendingImport(sampleImport('a', 1000))
    savePendingImport(sampleImport('b', 2000))
    const all = getAllPendingImports()
    expect(all.length).toBeGreaterThanOrEqual(2)
    expect(all[0].created_at).toBeGreaterThanOrEqual(all[1].created_at)
  })
})
