import { describe, expect, it } from 'vitest'
import {
  applyToolCallEvent,
  buildLiveStep,
  chainDurationMs,
  chainState,
  hasStepDetails,
  isDocumentTemplateChange,
  stepsFromNodeResults,
  withLiveStep,
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

describe('buildLiveStep', () => {
  it('去掉「正在调用工具」前缀作为标题', () => {
    expect(buildLiveStep('正在调用工具：搜索')).toMatchObject({ title: '搜索', state: 'running', live: true })
  })

  it('空文案返回 null', () => {
    expect(buildLiveStep('   ')).toBeNull()
  })
})

describe('withLiveStep', () => {
  it('没有真实步骤时用占位步骤撑起链路', () => {
    const live = buildLiveStep('正在执行任务')
    expect(withLiveStep([], live)).toHaveLength(1)
  })

  it('已有进行中的真实步骤时不再追加占位', () => {
    const steps = stepsFromNodeResults([{ node_id: 'n', success: false, tool_id: 'x', action: 'y' }]).map((s) => ({
      ...s,
      state: 'running' as const,
    }))
    expect(withLiveStep(steps, buildLiveStep('正在执行任务'))).toHaveLength(1)
  })

  it('已有终态步骤时追加新的进行中步骤', () => {
    const steps = stepsFromNodeResults([{ node_id: 'n', success: true, tool_id: 'x', action: 'y' }])
    expect(withLiveStep(steps, buildLiveStep('正在执行任务'))).toHaveLength(2)
  })
})

describe('applyToolCallEvent', () => {
  it('started 事件新增一个执行中步骤', () => {
    const steps = applyToolCallEvent([], { phase: 'started', node_id: 'n1', tool_id: 'excel', action: 'write' })
    expect(steps).toHaveLength(1)
    expect(steps[0]).toMatchObject({ id: 'n1', title: '表格', subtitle: '写入', state: 'running' })
  })

  it('finished 事件按 node_id 原地更新为成功', () => {
    let steps = applyToolCallEvent([], { phase: 'started', node_id: 'n1', tool_id: 'excel', action: 'write' })
    steps = applyToolCallEvent(steps, {
      phase: 'finished',
      node_id: 'n1',
      tool_id: 'excel',
      action: 'write',
      success: true,
      duration_ms: 420,
      output_preview: '已写入 3 行',
    })
    expect(steps).toHaveLength(1)
    expect(steps[0]).toMatchObject({ state: 'success', durationMs: 420, output: '已写入 3 行' })
  })

  it('finished 失败事件保留错误与建议', () => {
    const steps = applyToolCallEvent([], {
      phase: 'finished',
      node_id: 'n2',
      tool_id: 'business_db',
      action: 'write',
      success: false,
      error: '唯一约束冲突',
      recovery_hint: '改用更新动作',
      retries: 1,
    })
    expect(steps[0]).toMatchObject({ state: 'failed', error: '唯一约束冲突', hint: '改用更新动作', retries: 1 })
  })

  it('多个节点按到达顺序累积', () => {
    let steps = applyToolCallEvent([], { phase: 'started', node_id: 'a', tool_id: 'x', action: 'query' })
    steps = applyToolCallEvent(steps, { phase: 'started', node_id: 'b', tool_id: 'y', action: 'read' })
    expect(steps.map((s) => s.id)).toEqual(['a', 'b'])
  })

  it('缺少 node_id 的事件被忽略', () => {
    expect(applyToolCallEvent([], { phase: 'started', tool_id: 'x' })).toEqual([])
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
