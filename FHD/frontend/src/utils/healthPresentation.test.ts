import { describe, expect, it } from 'vitest'
import { presentHealth } from './healthPresentation'

describe('presentHealth', () => {
  it('reports healthy runtime as normal', () => {
    expect(presentHealth({ status: 'healthy', runtime: { status: 'healthy' } })).toEqual({
      label: '系统正常',
      detail: '核心服务运行正常',
      tone: 'online',
    })
  })

  it('does not claim the whole system is normal when only the LLM runtime is unavailable', () => {
    expect(
      presentHealth({
        status: 'degraded',
        degradedReasons: ['LLM_RUNTIME_UNAVAILABLE'],
        runtime: { status: 'healthy' },
      }),
    ).toEqual({
      label: '基础功能正常',
      detail: 'AI 服务待检查',
      tone: 'degraded',
    })
  })

  it('reports required component failures and request failures explicitly', () => {
    expect(
      presentHealth({
        status: 'degraded',
        runtime: {
          status: 'degraded',
          components: { etl: { required: true, ok: false } },
        },
      }),
    ).toMatchObject({ label: '系统异常', tone: 'offline' })
    expect(presentHealth(null, false)).toMatchObject({ label: '状态未知', tone: 'unknown' })
  })
})
