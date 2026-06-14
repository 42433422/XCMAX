import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('../api/templatePreview', () => ({
  default: {
    extractGrid: vi.fn().mockResolvedValue({ grid: [] }),
    listTemplates: vi.fn().mockResolvedValue({ success: true, templates: [] }),
  },
}))

vi.mock('xlsx', () => ({
  read: vi.fn(() => ({
    SheetNames: ['Sheet1'],
    Sheets: { Sheet1: {} },
  })),
  utils: {
    sheet_to_json: vi.fn(() => [
      ['产品型号', '产品名称', '价格'],
      ['A001', '测试', 100],
    ]),
  },
}))

import { useBatchAnalyze } from './useBatchAnalyze'

describe('useBatchAnalyze', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('calculateFieldSimilarity returns high score for identical fields', () => {
    const { calculateFieldSimilarity } = useBatchAnalyze()
    expect(calculateFieldSimilarity(['型号', '价格'], ['型号', '价格'])).toBeGreaterThan(0.5)
  })

  it('calculateFieldSimilarity returns 0 when one side empty', () => {
    const { calculateFieldSimilarity } = useBatchAnalyze()
    expect(calculateFieldSimilarity([], ['型号'])).toBe(0)
    expect(calculateFieldSimilarity(['型号'], [])).toBe(0)
  })

  it('calculateFieldSimilarity returns 1 for both empty', () => {
    const { calculateFieldSimilarity } = useBatchAnalyze()
    expect(calculateFieldSimilarity([], [])).toBe(1)
  })

  it('inferTemplateTypeByFields returns template metadata', () => {
    const { inferTemplateTypeByFields } = useBatchAnalyze()
    const result = inferTemplateTypeByFields(['产品型号', '产品名称', '价格', '数量'])
    expect(result).toHaveProperty('templateType')
    expect(result).toHaveProperty('scopeKey')
    expect(result.matchScore).toBeGreaterThanOrEqual(0)
  })

  it('groupSheetsBySimilarity groups similar sheets', () => {
    const { groupSheetsBySimilarity } = useBatchAnalyze()
    const sheets = [
      { fileName: 'a.xlsx', sheetName: 'S1', fields: ['型号', '价格', '名称'], rowCount: 10 },
      { fileName: 'b.xlsx', sheetName: 'S2', fields: ['型号', '价格', '名称'], rowCount: 8 },
      { fileName: 'c.xlsx', sheetName: 'S3', fields: ['客户名称', '地址'], rowCount: 5 },
    ]
    const groups = groupSheetsBySimilarity(sheets)
    expect(groups.length).toBeGreaterThanOrEqual(1)
    expect(groups[0].matchedSheets.length).toBeGreaterThanOrEqual(1)
  })

  it('groupSheetsBySimilarity returns empty for no sheets', () => {
    const { groupSheetsBySimilarity } = useBatchAnalyze()
    expect(groupSheetsBySimilarity([])).toEqual([])
  })

  it('startBatchAnalyze rejects non-excel files', async () => {
    const { startBatchAnalyze, store } = useBatchAnalyze()
    const txt = new File(['hello'], 'notes.txt', { type: 'text/plain' })
    const groups = await startBatchAnalyze([txt])
    expect(groups).toEqual([])
    expect(store.errorMessage).toContain('Excel')
  })

  it('extractGridForSheet calls api and returns result', async () => {
    const { extractGridForSheet } = useBatchAnalyze()
    const file = new File(['x'], 'test.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    const result = await extractGridForSheet(file, 'Sheet1')
    expect(result).toEqual({ grid: [] })
  })
})
