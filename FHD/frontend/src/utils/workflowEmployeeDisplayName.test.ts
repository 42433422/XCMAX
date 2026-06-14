import { describe, expect, it } from 'vitest'
import { shortNameFromPanelTitle } from './workflowEmployeeDisplayName'

describe('workflowEmployeeDisplayName', () => {
  it('returns default for empty', () => {
    expect(shortNameFromPanelTitle('')).toBe('员工')
    expect(shortNameFromPanelTitle('   ')).toBe('员工')
  })

  it('strips workflow prefix and AI suffix', () => {
    expect(shortNameFromPanelTitle('工作流 · 标签打印 AI 员工')).toBe('标签打印')
  })

  it('handles bullet variants', () => {
    expect(shortNameFromPanelTitle('工作流 • 出货管理 AI 员工')).toBe('出货管理')
  })

  it('collapses whitespace', () => {
    expect(shortNameFromPanelTitle('  自定义  名称  ')).toBe('自定义 名称')
  })
})
