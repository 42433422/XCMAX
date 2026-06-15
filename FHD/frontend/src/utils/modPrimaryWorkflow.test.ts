import { describe, expect, it } from 'vitest'
import { resolveModPrimaryWorkflow } from './modPrimaryWorkflow'

describe('modPrimaryWorkflow', () => {
  it('returns null for invalid input', () => {
    expect(resolveModPrimaryWorkflow(null)).toBeNull()
    expect(resolveModPrimaryWorkflow('x')).toBeNull()
  })

  it('parses primary_workflow object', () => {
    const wf = resolveModPrimaryWorkflow({
      primary_workflow: {
        title: '测试流程',
        steps: [{ id: 'a', label: '步骤一', route: '/a' }],
      },
    })
    expect(wf?.title).toBe('测试流程')
    expect(wf?.steps).toHaveLength(1)
    expect(wf?.steps[0].route).toBe('/a')
  })

  it('parses string steps', () => {
    const wf = resolveModPrimaryWorkflow({
      frontend: { primaryWorkflow: { steps: ['上传', '导出'] } },
    })
    expect(wf?.steps.map((s) => s.label)).toEqual(['上传', '导出'])
  })

  it('returns attendance default for attendance-industry', () => {
    const wf = resolveModPrimaryWorkflow({ id: 'attendance-industry' })
    expect(wf?.title).toContain('考勤')
    expect(wf?.steps.length).toBeGreaterThan(2)
  })

  it('returns attendance default for taiyangniao-pro', () => {
    const wf = resolveModPrimaryWorkflow({ id: 'taiyangniao-pro' })
    expect(wf?.steps[0].label).toContain('考勤')
  })
})
