import { describe, it, expect, beforeEach } from 'vitest'
import {
  readPersistedExcelAnalysisContext,
  persistExcelAnalysisContext,
  resolveExcelFilePathFromAnalysis,
  resolveExcelSheetOptionsFromContext,
  resolveLinkedSheetGridPreview,
  extractLikelyProductQueryKeyword,
  EXCEL_ANALYSIS_STORAGE_PREFIX,
} from './useChatPersistence'

describe('useChatPersistence', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  describe('readPersistedExcelAnalysisContext', () => {
    it('returns null when no data', () => {
      expect(readPersistedExcelAnalysisContext('test')).toBeNull()
    })

    it('returns parsed context from sessionStorage', () => {
      sessionStorage.setItem(
        EXCEL_ANALYSIS_STORAGE_PREFIX + 'test',
        JSON.stringify({ file_path: '/test.xlsx' }),
      )
      const result = readPersistedExcelAnalysisContext('test')
      expect(result).toEqual({ file_path: '/test.xlsx' })
    })

    it('returns null for invalid JSON', () => {
      sessionStorage.setItem(EXCEL_ANALYSIS_STORAGE_PREFIX + 'test', 'not-json')
      expect(readPersistedExcelAnalysisContext('test')).toBeNull()
    })
  })

  describe('persistExcelAnalysisContext', () => {
    it('stores context in sessionStorage', () => {
      persistExcelAnalysisContext('test', { file_path: '/a.xlsx' })
      const raw = sessionStorage.getItem(EXCEL_ANALYSIS_STORAGE_PREFIX + 'test')
      expect(raw).toBeTruthy()
      expect(JSON.parse(raw!)).toEqual({ file_path: '/a.xlsx' })
    })

    it('removes context when null', () => {
      persistExcelAnalysisContext('test', { file_path: '/a.xlsx' })
      persistExcelAnalysisContext('test', null)
      expect(sessionStorage.getItem(EXCEL_ANALYSIS_STORAGE_PREFIX + 'test')).toBeNull()
    })
  })

  describe('resolveExcelFilePathFromAnalysis', () => {
    it('returns file_path from top level', () => {
      expect(resolveExcelFilePathFromAnalysis({ file_path: '/top.xlsx' })).toBe('/top.xlsx')
    })

    it('returns file_path from preview_data', () => {
      expect(resolveExcelFilePathFromAnalysis({ preview_data: { file_path: '/preview.xlsx' } })).toBe('/preview.xlsx')
    })

    it('returns file_path from data', () => {
      expect(resolveExcelFilePathFromAnalysis({ data: { file_path: '/data.xlsx' } })).toBe('/data.xlsx')
    })

    it('returns file_path from document', () => {
      expect(resolveExcelFilePathFromAnalysis({ document: { filepath: '/doc.xlsx' } })).toBe('/doc.xlsx')
    })

    it('returns file_path from meta', () => {
      expect(resolveExcelFilePathFromAnalysis({ meta: { file_path: '/meta.xlsx' } })).toBe('/meta.xlsx')
    })

    it('returns empty string when no file_path found', () => {
      expect(resolveExcelFilePathFromAnalysis({})).toBe('')
    })

    it('returns empty string for null', () => {
      expect(resolveExcelFilePathFromAnalysis(null)).toBe('')
    })
  })

  describe('resolveExcelSheetOptionsFromContext', () => {
    it('returns empty array for null', () => {
      expect(resolveExcelSheetOptionsFromContext(null)).toEqual([])
    })

    it('returns empty array for no preview_data', () => {
      expect(resolveExcelSheetOptionsFromContext({})).toEqual([])
    })

    it('returns sheets from all_sheets', () => {
      const ctx = {
        preview_data: {
          all_sheets: [
            { sheet_name: 'Sheet1', sheet_index: 1 },
            { sheet_name: 'Sheet2', sheet_index: 2 },
          ],
        },
      }
      const result = resolveExcelSheetOptionsFromContext(ctx)
      expect(result).toHaveLength(2)
      expect(result[0].sheet_name).toBe('Sheet1')
    })

    it('skips sheets with empty names', () => {
      const ctx = {
        preview_data: {
          all_sheets: [
            { sheet_name: '', sheet_index: 1 },
            { sheet_name: 'Sheet2', sheet_index: 2 },
          ],
        },
      }
      const result = resolveExcelSheetOptionsFromContext(ctx)
      expect(result).toHaveLength(1)
    })

    it('falls back to sheet_names', () => {
      const ctx = {
        preview_data: {
          sheet_names: ['Sheet1', 'Sheet2'],
        },
      }
      const result = resolveExcelSheetOptionsFromContext(ctx)
      expect(result).toHaveLength(2)
    })
  })

  describe('resolveLinkedSheetGridPreview', () => {
    it('returns null for null context', () => {
      expect(resolveLinkedSheetGridPreview(null, { sheet_name: 'Sheet1', sheet_index: 1 })).toBeNull()
    })

    it('returns null for null linkedSheet', () => {
      expect(resolveLinkedSheetGridPreview({}, null)).toBeNull()
    })

    it('returns null when sheet not found', () => {
      expect(resolveLinkedSheetGridPreview({}, { sheet_name: 'Sheet1', sheet_index: 1 })).toBeNull()
    })

    it('returns preview when sheet found', () => {
      const ctx = {
        preview_data: {
          all_sheets: [
            { sheet_name: 'Sheet1', sheet_index: 1, fields: [{ label: 'Name' }], sample_rows: [{ Name: 'Test' }] },
          ],
        },
      }
      const result = resolveLinkedSheetGridPreview(ctx, { sheet_name: 'Sheet1', sheet_index: 1 })
      expect(result).not.toBeNull()
      expect(result!.sheet_name).toBe('Sheet1')
      expect(result!.field_names).toContain('Name')
    })
  })

  describe('extractLikelyProductQueryKeyword', () => {
    it('returns null for short input', () => {
      expect(extractLikelyProductQueryKeyword('a')).toBeNull()
    })

    it('returns null for long input', () => {
      expect(extractLikelyProductQueryKeyword('x'.repeat(201))).toBeNull()
    })

    it('returns null for question patterns', () => {
      expect(extractLikelyProductQueryKeyword('什么价格')).toBeNull()
      expect(extractLikelyProductQueryKeyword('怎么操作')).toBeNull()
    })

    it('returns null for non-product queries', () => {
      expect(extractLikelyProductQueryKeyword('出货单')).toBeNull()
      expect(extractLikelyProductQueryKeyword('打印标签')).toBeNull()
    })

    it('extracts keyword from 查询 pattern', () => {
      const result = extractLikelyProductQueryKeyword('查询 XCD-100')
      expect(result).toBe('XCD-100')
    })

    it('extracts keyword from 查一下 pattern', () => {
      const result = extractLikelyProductQueryKeyword('查一下 XCD-200 的价格')
      expect(result).toBe('XCD-200')
    })

    it('returns null for 帮我查 pattern (blocked by 帮 prefix)', () => {
      // The function blocks queries starting with 帮
      const result = extractLikelyProductQueryKeyword('帮我查XCD-300的价格')
      expect(result).toBeNull()
    })

    it('returns null for non-matching input', () => {
      expect(extractLikelyProductQueryKeyword('普通对话内容')).toBeNull()
    })
  })
})
