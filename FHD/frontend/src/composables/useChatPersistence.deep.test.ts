import { describe, it, expect, beforeEach } from 'vitest'
import {
  resolveExcelFilePathFromAnalysis,
  resolveExcelSheetOptionsFromContext,
  resolveLinkedSheetGridPreview,
  extractLikelyProductQueryKeyword,
  readPersistedTaskPanelState,
  persistTaskPanelState,
  toPlainText,
  isWelcomeMessage,
} from './useChatPersistence'

describe('useChatPersistence deep branches', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  it('resolveExcelFilePathFromAnalysis checks all candidate paths', () => {
    expect(resolveExcelFilePathFromAnalysis({ data: { file_path: '/d.xlsx' } })).toBe('/d.xlsx')
    expect(resolveExcelFilePathFromAnalysis({ document: { filepath: '/e.xlsx' } })).toBe('/e.xlsx')
    expect(resolveExcelFilePathFromAnalysis({ meta: { file_path: '/f.xlsx' } })).toBe('/f.xlsx')
    expect(resolveExcelFilePathFromAnalysis({ upload: { file_path: '/g.xlsx' } })).toBe('/g.xlsx')
    expect(resolveExcelFilePathFromAnalysis({ source: { file_path: '/h.xlsx' } })).toBe('/h.xlsx')
  })

  it('resolveExcelSheetOptionsFromContext uses all_sheets branch', () => {
    const sheets = resolveExcelSheetOptionsFromContext({
      preview_data: {
        all_sheets: [
          { sheet_name: 'A', sheet_index: 2 },
          { sheet_name: '', sheet_index: 3 },
        ],
      },
    })
    expect(sheets).toEqual([{ sheet_name: 'A', sheet_index: 2 }])
  })

  it('resolveLinkedSheetGridPreview builds preview by name and index', () => {
    const ctx = {
      preview_data: {
        all_sheets: [
          {
            sheet_name: 'Sheet1',
            sheet_index: 1,
            fields: [{ label: '型号' }],
            sample_rows: [['a']],
            grid_preview: { rows: [['h1', 'h2']] },
          },
        ],
      },
    }
    const preview = resolveLinkedSheetGridPreview(ctx, { sheet_name: 'Sheet1', sheet_index: 1 })
    expect(preview?.sheet_name).toBe('Sheet1')
    expect(preview?.field_names).toContain('型号')
    expect(resolveLinkedSheetGridPreview(null, { sheet_name: 'X', sheet_index: 1 })).toBeNull()
  })

  it('extractLikelyProductQueryKeyword rejects blocked intents', () => {
    expect(extractLikelyProductQueryKeyword('什么价格')).toBeNull()
    expect(extractLikelyProductQueryKeyword('帮我导出出货单')).toBeNull()
    expect(extractLikelyProductQueryKeyword('x')).toBeNull()
  })

  it('extractLikelyProductQueryKeyword parses query patterns', () => {
    expect(extractLikelyProductQueryKeyword('查询 ABC-99')).toBe('ABC-99')
    expect(extractLikelyProductQueryKeyword('查一下「XYZ」的价格')).toBe('XYZ')
  })

  it('readPersistedTaskPanelState normalizes filter and tasks', () => {
    persistTaskPanelState('sess-br', {
      taskList: [{ id: 't1', type: 'shipment', status: 'running', title: 'T' }],
      activeTaskId: 't1',
      expandedTaskIds: ['t1'],
      taskFilter: 'running',
      currentTask: null,
      savedAt: 1,
    })
    const state = readPersistedTaskPanelState('sess-br')
    expect(state?.taskFilter).toBe('running')
    expect(state?.taskList).toHaveLength(1)
    expect(readPersistedTaskPanelState('')).toBeNull()
  })

  it('toPlainText handles objects and arrays', () => {
    expect(toPlainText({ a: 1 })).toBe('[object Object]')
    expect(toPlainText([1, 2])).toContain('1')
  })

  it('isWelcomeMessage matches industry welcome text', () => {
    expect(isWelcomeMessage({ role: 'ai', content: '您好！我是您的智能考勤助手' })).toBe(true)
    expect(isWelcomeMessage({ role: 'ai', content: 'random' })).toBe(false)
  })
})
