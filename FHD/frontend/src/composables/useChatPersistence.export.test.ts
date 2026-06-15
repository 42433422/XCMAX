import { describe, it, expect, beforeEach } from 'vitest'
import {
  readPersistedExcelAnalysisContext,
  persistExcelAnalysisContext,
  resolveExcelFilePathFromAnalysis,
  resolveExcelSheetOptionsFromContext,
  extractLikelyProductQueryKeyword,
  readPersistedTaskPanelState,
  persistTaskPanelState,
  clearPersistedTaskPanelState,
  toPlainText,
  isWelcomeMessage,
  toHistoryTimestamp,
  EXCEL_ANALYSIS_STORAGE_PREFIX,
  CHAT_TASK_PANEL_STORAGE_PREFIX,
} from './useChatPersistence'

describe('useChatPersistence exports', () => {
  beforeEach(() => {
    sessionStorage.clear()
    localStorage.clear()
  })

  it('persists and reads excel analysis context', () => {
    const ctx = { file_name: 'a.xlsx', summary: 'ok' }
    persistExcelAnalysisContext('sess1', ctx)
    expect(readPersistedExcelAnalysisContext('sess1')).toEqual(ctx)
    persistExcelAnalysisContext('sess1', null)
    expect(readPersistedExcelAnalysisContext('sess1')).toBeNull()
  })

  it('resolveExcelFilePathFromAnalysis scans nested paths', () => {
    expect(resolveExcelFilePathFromAnalysis({ file_path: '/a.xlsx' })).toBe('/a.xlsx')
    expect(resolveExcelFilePathFromAnalysis({ preview_data: { file_path: '/b.xlsx' } })).toBe('/b.xlsx')
    expect(resolveExcelFilePathFromAnalysis(null)).toBe('')
  })

  it('resolveExcelSheetOptionsFromContext maps sheet_names', () => {
    const sheets = resolveExcelSheetOptionsFromContext({
      preview_data: { sheet_names: ['S1'] },
    })
    expect(sheets).toEqual([{ sheet_name: 'S1', sheet_index: 1 }])
  })

  it('extractLikelyProductQueryKeyword finds product terms', () => {
    expect(extractLikelyProductQueryKeyword('查一下 ABC-123 库存')).toBeTruthy()
    expect(extractLikelyProductQueryKeyword('')).toBeNull()
  })

  it('persists task panel state', () => {
    const state = {
      taskList: [],
      activeTaskId: '',
      expandedTaskIds: [],
      taskFilter: 'all' as const,
      currentTask: null,
      savedAt: Date.now(),
    }
    persistTaskPanelState('sess2', state)
    const raw = sessionStorage.getItem(CHAT_TASK_PANEL_STORAGE_PREFIX + 'sess2')
    expect(raw).toBeTruthy()
    expect(readPersistedTaskPanelState('sess2')?.taskFilter).toBe('all')
    clearPersistedTaskPanelState('sess2')
    expect(readPersistedTaskPanelState('sess2')).toBeNull()
  })

  it('toPlainText strips html-ish content', () => {
    expect(toPlainText('<b>hi</b>')).toContain('hi')
    expect(toPlainText(null)).toBe('')
  })

  it('isWelcomeMessage detects industry welcome text', () => {
    expect(isWelcomeMessage({ role: 'ai', content: '您好！我是您的智能考勤助手' })).toBe(true)
    expect(isWelcomeMessage({ role: 'user', content: 'hello' })).toBe(false)
  })

  it('toHistoryTimestamp returns 0 for invalid input', () => {
    expect(toHistoryTimestamp('bad')).toBe(0)
    expect(toHistoryTimestamp('2024-01-01T00:00:00.000Z')).toBeGreaterThan(0)
  })

  it('storage prefixes are stable', () => {
    expect(EXCEL_ANALYSIS_STORAGE_PREFIX).toContain('excel')
    expect(CHAT_TASK_PANEL_STORAGE_PREFIX).toContain('task_panel')
  })
})
