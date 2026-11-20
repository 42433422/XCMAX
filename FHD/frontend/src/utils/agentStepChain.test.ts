import { describe, expect, it } from 'vitest'
import {
  chainDurationMs,
  chainState,
  hasStepDetails,
  isDocumentTemplateChange,
  stepsFromNodeResults,
} from './agentStepChain'

describe('stepsFromNodeResults', () => {
  it('把成功的 node_results 映射为已完成步骤', () => {
    const steps = stepsFromNodeResults([
      { node_id: 'n1', success: true, tool_id: 'business_db', action: 'query', output_preview: '3 行', duration_ms: 320 },
    ])
    expect(steps).toHaveLength(1)
    expect(steps[0]).toMatchObject({
      id: 'n1',
      title: '业务数据库',
      subtitle: '查询',
      state: 'success',
      durationMs: 320,
      output: '3 行',
    })
    expect(hasStepDetails(steps[0])).toBe(true)
  })

  it('失败步骤保留错误与建议', () => {
    const steps = stepsFromNodeResults([
      {
        node_id: 'n2',
        success: false,
        tool_id: 'excel',
        action: 'write',
        error: '文件被占用',
        recovery_hint: '关闭 Excel 后重试',
        retries: 2,
      },
    ])
    expect(steps[0].state).toBe('failed')
    expect(steps[0].error).toBe('文件被占用')
    expect(steps[0].hint).toBe('关闭 Excel 后重试')
    expect(steps[0].retries).toBe(2)
  })

  it('空输入返回空数组', () => {
    expect(stepsFromNodeResults(undefined)).toEqual([])
    expect(stepsFromNodeResults([])).toEqual([])
  })
})

describe('chainState / chainDurationMs', () => {
  it('失败优先于其他状态', () => {
    const steps = stepsFromNodeResults([
      { node_id: 'a', success: true, tool_id: 'x', action: 'y' },
      { node_id: 'b', success: false, tool_id: 'x', action: 'y' },
    ])
    expect(chainState(steps)).toBe('failed')
  })

  it('全部成功时为 success', () => {
    const steps = stepsFromNodeResults([{ node_id: 'a', success: true, tool_id: 'x', action: 'y' }])
    expect(chainState(steps)).toBe('success')
  })

  it('累加各步骤耗时', () => {
    const steps = stepsFromNodeResults([
      { node_id: 'a', success: true, tool_id: 'x', action: 'y', duration_ms: 100 },
      { node_id: 'b', success: true, tool_id: 'x', action: 'y', duration_ms: 250 },
    ])
    expect(chainDurationMs(steps)).toBe(350)
  })

  it('无耗时返回 undefined', () => {
    expect(chainDurationMs([])).toBeUndefined()
  })
})

describe('isDocumentTemplateChange', () => {
  it('模板库工具完成时需要通知页面刷新', () => {
    expect(
      isDocumentTemplateChange({ phase: 'finished', tool_id: 'document_template', action: 'clear' }),
    ).toBe(true)
  })

  it('执行中或其它工具不触发刷新', () => {
    expect(isDocumentTemplateChange({ phase: 'started', tool_id: 'document_template' })).toBe(false)
    expect(isDocumentTemplateChange({ phase: 'finished', tool_id: 'elt_import' })).toBe(false)
    expect(isDocumentTemplateChange(undefined)).toBe(false)
  })
})
