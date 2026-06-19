import { describe, it, expect } from 'vitest'
import { formatPlanMdForDisplay, formatBriefGoalForDisplay } from './planMdDisplay'

describe('formatPlanMdForDisplay', () => {
  it('returns formatted text for normal markdown', () => {
    const md = '## Step 1\nDo something\n\n## Step 2\nDo another thing'
    const result = formatPlanMdForDisplay(md)
    expect(result).toContain('Step 1')
    expect(result).toContain('Step 2')
    expect(result).not.toContain('##')
  })

  it('returns （无计划摘要） for empty string', () => {
    expect(formatPlanMdForDisplay('')).toBe('（无计划摘要）')
  })

  it('returns （无计划摘要） for null', () => {
    expect(formatPlanMdForDisplay(null as unknown as string)).toBe('（无计划摘要）')
  })

  it('returns （无计划摘要） for undefined', () => {
    expect(formatPlanMdForDisplay(undefined as unknown as string)).toBe('（无计划摘要）')
  })

  it('strips heading markers', () => {
    const md = '### Heading 1\nContent'
    const result = formatPlanMdForDisplay(md)
    expect(result).not.toContain('#')
    expect(result).toContain('Heading 1')
  })

  it('collapses multiple newlines into double', () => {
    const md = 'Line 1\n\n\n\n\nLine 2'
    const result = formatPlanMdForDisplay(md)
    expect(result).not.toMatch(/\n{3,}/)
  })

  it('truncates text longer than max with ellipsis', () => {
    const longText = 'a'.repeat(2000)
    const result = formatPlanMdForDisplay(longText, 100)
    expect(result.length).toBeLessThanOrEqual(101)
    expect(result.endsWith('…')).toBe(true)
  })

  it('does not truncate text shorter than max', () => {
    const shortText = 'short text'
    const result = formatPlanMdForDisplay(shortText, 100)
    expect(result).toBe('short text')
    expect(result.endsWith('…')).toBe(false)
  })

  it('uses default max of 1200', () => {
    const longText = 'a'.repeat(1500)
    const result = formatPlanMdForDisplay(longText)
    expect(result.endsWith('…')).toBe(true)
    expect(result.length).toBeLessThanOrEqual(1201)
  })

  it('trims leading and trailing whitespace', () => {
    const md = '  \n\n  Content  \n\n  '
    const result = formatPlanMdForDisplay(md)
    expect(result).toBe('Content')
  })

  it('handles text with only headings', () => {
    const md = '## Title'
    const result = formatPlanMdForDisplay(md)
    expect(result).toBe('Title')
  })

  it('handles text with only whitespace', () => {
    expect(formatPlanMdForDisplay('   \n\n  \n  ')).toBe('（无计划摘要）')
  })
})

describe('formatBriefGoalForDisplay', () => {
  it('returns formatted text for normal goal', () => {
    const result = formatBriefGoalForDisplay('Generate a quarterly report')
    expect(result).toBe('Generate a quarterly report')
  })

  it('returns (无任务描述) for empty string', () => {
    expect(formatBriefGoalForDisplay('')).toBe('(无任务描述)')
  })

  it('returns (无任务描述) for null', () => {
    expect(formatBriefGoalForDisplay(null as unknown as string)).toBe('(无任务描述)')
  })

  it('returns (无任务描述) for undefined', () => {
    expect(formatBriefGoalForDisplay(undefined as unknown as string)).toBe('(无任务描述)')
  })

  it('collapses whitespace into single spaces', () => {
    const result = formatBriefGoalForDisplay('multiple    spaces\n\nand\tnewlines')
    expect(result).not.toMatch(/\s{2,}/)
    expect(result).toContain('multiple spaces')
  })

  it('truncates text longer than max with ellipsis', () => {
    const longText = 'a'.repeat(300)
    const result = formatBriefGoalForDisplay(longText, 50)
    expect(result.length).toBeLessThanOrEqual(51)
    expect(result.endsWith('…')).toBe(true)
  })

  it('does not truncate text shorter than max', () => {
    const result = formatBriefGoalForDisplay('short', 100)
    expect(result).toBe('short')
    expect(result.endsWith('…')).toBe(false)
  })

  it('uses default max of 200', () => {
    const longText = 'a'.repeat(300)
    const result = formatBriefGoalForDisplay(longText)
    expect(result.endsWith('…')).toBe(true)
    expect(result.length).toBeLessThanOrEqual(201)
  })

  it('trims leading and trailing whitespace', () => {
    const result = formatBriefGoalForDisplay('  \n  Goal text  \n  ')
    expect(result).toBe('Goal text')
  })

  it('handles text with only whitespace', () => {
    expect(formatBriefGoalForDisplay('   \n\n  \n  ')).toBe('(无任务描述)')
  })
})
