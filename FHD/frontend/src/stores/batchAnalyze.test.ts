import { describe, it, expect, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useBatchAnalyzeStore } from './batchAnalyze'

describe('useBatchAnalyzeStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('initializes with default state', () => {
    const store = useBatchAnalyzeStore()
    expect(store.phase).toBe('idle')
    expect(store.totalFiles).toBe(0)
    expect(store.processedFiles).toBe(0)
    expect(store.progress).toBe(0)
    expect(store.errorMessage).toBe('')
    expect(store.extractedSheets).toEqual([])
    expect(store.groups).toEqual([])
    expect(store.selectedGroupId).toBeNull()
    expect(store.sessionId).toBe('')
    expect(store.failedFiles).toEqual([])
  })

  it('phaseLabel returns correct labels', () => {
    const store = useBatchAnalyzeStore()
    expect(store.phaseLabel).toBe('等待开始')
    store.phase = 'extracting'
    expect(store.phaseLabel).toBe('正在拆解文档')
    store.phase = 'grouping'
    expect(store.phaseLabel).toBe('正在分组')
    store.phase = 'matching'
    expect(store.phaseLabel).toBe('正在匹配模板')
    store.phase = 'done'
    expect(store.phaseLabel).toBe('分析完成')
    store.phase = 'error'
    expect(store.phaseLabel).toBe('发生错误')
  })

  it('progressText returns empty for idle', () => {
    const store = useBatchAnalyzeStore()
    expect(store.progressText).toBe('')
  })

  it('progressText returns extracting info', () => {
    const store = useBatchAnalyzeStore()
    store.phase = 'extracting'
    store.totalFiles = 5
    store.processedFiles = 2
    store.currentFileName = 'test.xlsx'
    expect(store.progressText).toContain('拆解中')
    expect(store.progressText).toContain('2/5')
  })

  it('progressText returns grouping info', () => {
    const store = useBatchAnalyzeStore()
    store.phase = 'grouping'
    store.totalSheets = 10
    expect(store.progressText).toContain('10')
  })

  it('progressText returns matching info', () => {
    const store = useBatchAnalyzeStore()
    store.phase = 'matching'
    expect(store.progressText).toContain('匹配模板')
  })

  it('progressText returns done info', () => {
    const store = useBatchAnalyzeStore()
    store.phase = 'done'
    store.groups = [{ id: '1' } as any, { id: '2' } as any]
    expect(store.progressText).toContain('2')
  })

  it('canStartAnalyze is false when no sheets', () => {
    const store = useBatchAnalyzeStore()
    expect(store.canStartAnalyze).toBe(false)
  })

  it('canStartAnalyze is true when sheets exist and phase is idle', () => {
    const store = useBatchAnalyzeStore()
    store.extractedSheets = [{ fileName: 'a.xlsx', sheetName: 'Sheet1', sheetIndex: 0, fields: [], rowCount: 0, sampleRows: [] }]
    expect(store.canStartAnalyze).toBe(true)
  })

  it('canStartAnalyze is false when phase is not idle', () => {
    const store = useBatchAnalyzeStore()
    store.extractedSheets = [{ fileName: 'a.xlsx', sheetName: 'Sheet1', sheetIndex: 0, fields: [], rowCount: 0, sampleRows: [] }]
    store.phase = 'extracting'
    expect(store.canStartAnalyze).toBe(false)
  })

  it('selectedGroup returns null when no group selected', () => {
    const store = useBatchAnalyzeStore()
    expect(store.selectedGroup).toBeNull()
  })

  it('selectedGroup returns the selected group', () => {
    const store = useBatchAnalyzeStore()
    store.groups = [{ id: '1', name: 'Group 1' } as any, { id: '2', name: 'Group 2' } as any]
    store.selectedGroupId = '2'
    expect(store.selectedGroup?.id).toBe('2')
  })

  it('reset clears all state', () => {
    const store = useBatchAnalyzeStore()
    store.phase = 'done'
    store.totalFiles = 5
    store.progress = 100
    store.errorMessage = 'test'
    store.extractedSheets = [{ fileName: 'a.xlsx', sheetName: 'Sheet1', sheetIndex: 0, fields: [], rowCount: 0, sampleRows: [] }]
    store.reset()
    expect(store.phase).toBe('idle')
    expect(store.totalFiles).toBe(0)
    expect(store.progress).toBe(0)
    expect(store.errorMessage).toBe('')
    expect(store.extractedSheets).toEqual([])
  })

  it('startNewSession generates sessionId', () => {
    const store = useBatchAnalyzeStore()
    store.startNewSession()
    expect(store.sessionId).toBeTruthy()
    expect(store.phase).toBe('idle')
  })

  it('addFailedFile adds to failedFiles', () => {
    const store = useBatchAnalyzeStore()
    store.addFailedFile('bad.xlsx', 'parse error')
    expect(store.failedFiles).toHaveLength(1)
    expect(store.failedFiles[0].fileName).toBe('bad.xlsx')
  })

  it('setPhase updates phase', () => {
    const store = useBatchAnalyzeStore()
    store.setPhase('extracting')
    expect(store.phase).toBe('extracting')
  })

  it('updateProgress updates specified fields', () => {
    const store = useBatchAnalyzeStore()
    store.updateProgress({ totalFiles: 10, progress: 50 })
    expect(store.totalFiles).toBe(10)
    expect(store.progress).toBe(50)
    expect(store.processedFiles).toBe(0)
  })

  it('addExtractedSheets appends sheets', () => {
    const store = useBatchAnalyzeStore()
    const sheet = { fileName: 'a.xlsx', sheetName: 'Sheet1', sheetIndex: 0, fields: [], rowCount: 0, sampleRows: [] }
    store.addExtractedSheets([sheet])
    expect(store.extractedSheets).toHaveLength(1)
  })

  it('setGroups replaces groups', () => {
    const store = useBatchAnalyzeStore()
    store.setGroups([{ id: '1' } as any])
    expect(store.groups).toHaveLength(1)
  })

  it('setError sets error message and phase', () => {
    const store = useBatchAnalyzeStore()
    store.setError('Something failed')
    expect(store.errorMessage).toBe('Something failed')
    expect(store.phase).toBe('error')
  })

  it('selectGroup sets selectedGroupId', () => {
    const store = useBatchAnalyzeStore()
    store.selectGroup('g1')
    expect(store.selectedGroupId).toBe('g1')
  })

  it('selectGroup with null clears selection', () => {
    const store = useBatchAnalyzeStore()
    store.selectGroup('g1')
    store.selectGroup(null)
    expect(store.selectedGroupId).toBeNull()
  })

  it('updateGroupTemplate updates group fields', () => {
    const store = useBatchAnalyzeStore()
    store.groups = [{ id: '1', recommendedTemplateId: '', recommendedTemplateName: '', matchScore: 0 } as any]
    store.updateGroupTemplate('1', 'tmpl-1', 'Template 1', 0.95)
    expect(store.groups[0].recommendedTemplateId).toBe('tmpl-1')
    expect(store.groups[0].recommendedTemplateName).toBe('Template 1')
    expect(store.groups[0].matchScore).toBe(0.95)
  })

  it('updateSheetGridData updates matching sheet', () => {
    const store = useBatchAnalyzeStore()
    store.extractedSheets = [{ fileName: 'a.xlsx', sheetName: 'Sheet1', sheetIndex: 0, fields: [], rowCount: 0, sampleRows: [] }]
    store.updateSheetGridData('a.xlsx', 'Sheet1', { rows: [] })
    expect(store.extractedSheets[0].gridData).toEqual({ rows: [] })
  })

  it('updateGroupExtractStatus updates group status', () => {
    const store = useBatchAnalyzeStore()
    store.groups = [{ id: '1', extractStatus: 'pending' } as any]
    store.updateGroupExtractStatus('1', 'done')
    expect(store.groups[0].extractStatus).toBe('done')
  })

  it('updateGroupExtractStatus sets error on group', () => {
    const store = useBatchAnalyzeStore()
    store.groups = [{ id: '1', extractStatus: 'pending' } as any]
    store.updateGroupExtractStatus('1', 'failed', 'timeout')
    expect(store.groups[0].extractStatus).toBe('failed')
    expect(store.groups[0].extractError).toBe('timeout')
  })

  it('updateGroupSheets replaces matched sheets', () => {
    const store = useBatchAnalyzeStore()
    store.groups = [{ id: '1', matchedSheets: [] } as any]
    const newSheets = [{ fileName: 'b.xlsx', sheetName: 'Sheet2', sheetIndex: 0, fields: [], rowCount: 0, sampleRows: [] }]
    store.updateGroupSheets('1', newSheets)
    expect(store.groups[0].matchedSheets).toHaveLength(1)
  })
})
