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

  it('savePendingImport swallows storage write errors', () => {
    const originalSetItem = Storage.prototype.setItem
    Storage.prototype.setItem = () => {
      throw new Error('denied')
    }
    try {
      expect(() => savePendingImport(sampleImport('p-write-fail'))).not.toThrow()
    } finally {
      Storage.prototype.setItem = originalSetItem
    }
  })

  it('getPendingImport returns null when sessionStorage read fails', () => {
    const originalGetItem = Storage.prototype.getItem
    Storage.prototype.getItem = () => {
      throw new Error('denied')
    }
    try {
      expect(getPendingImport('p-read-fail')).toBeNull()
    } finally {
      Storage.prototype.getItem = originalGetItem
    }
  })

  it('removePendingImport swallows storage removal errors', () => {
    const originalRemoveItem = Storage.prototype.removeItem
    Storage.prototype.removeItem = () => {
      throw new Error('denied')
    }
    try {
      expect(() => removePendingImport('p-remove-fail')).not.toThrow()
    } finally {
      Storage.prototype.removeItem = originalRemoveItem
    }
  })

  it('cleanupExpiredImports ignores corrupt entries', () => {
    localStorage.setItem('xcagi_excel_pending_import_corrupt', '{oops')
    localStorage.setItem('xcagi_excel_pending_import_ok', JSON.stringify(sampleImport('ok')))
    expect(() => cleanupExpiredImports()).not.toThrow()
    expect(getPendingImport('ok')).not.toBeNull()
  })

  it('getAllPendingImports ignores corrupt entries', () => {
    localStorage.setItem('xcagi_excel_pending_import_corrupt', '{oops')
    const all = getAllPendingImports()
    expect(all.every((i) => i.pending_id !== 'corrupt')).toBe(true)
  })

  it('cleanupExpiredImports swallows outer storage failures', () => {
    const originalLength = Object.getOwnPropertyDescriptor(Storage.prototype, 'length')
    Object.defineProperty(Storage.prototype, 'length', {
      configurable: true,
      get: () => {
        throw new Error('no storage')
      },
    })
    try {
      expect(() => cleanupExpiredImports()).not.toThrow()
      expect(getAllPendingImports()).toEqual([])
    } finally {
      if (originalLength) Object.defineProperty(Storage.prototype, 'length', originalLength)
    }
  })
})
