import { describe, it, expect } from 'vitest'
import {
  createEmptyEmployeeConfigV2,
  applyTemplateV2,
  upgradeLegacyToV2,
  validateEmployeeConfigV2,
} from './employeeConfigV2'

describe('employeeConfigV2', () => {
  it('createEmptyEmployeeConfigV2 returns default structure', () => {
    const cfg = createEmptyEmployeeConfigV2()
    expect(cfg.identity).toBeDefined()
    expect(cfg.cognition?.agent).toBeDefined()
    expect(cfg.collaboration).toBeDefined()
  })

  it('createEmptyEmployeeConfigV2 accepts model opts', () => {
    const cfg = createEmptyEmployeeConfigV2({ model: { provider: 'openai', model_name: 'gpt-4' } })
    expect(cfg.cognition?.agent?.model?.provider).toBe('openai')
    expect(cfg.cognition?.agent?.model?.model_name).toBe('gpt-4')
  })

  it('applyTemplateV2 returns config for workflow template', () => {
    const cfg = applyTemplateV2('workflow')
    expect(cfg.identity).toBeDefined()
    expect(cfg.collaboration?.workflow).toBeDefined()
  })

  it('applyTemplateV2 falls back for unknown template', () => {
    const cfg = applyTemplateV2('__unknown_template__')
    expect(cfg.identity).toBeDefined()
  })

  it('upgradeLegacyToV2 migrates flat manifest', () => {
    const legacy = { name: '旧员工', description: 'desc', industry: 'coating' }
    const cfg = upgradeLegacyToV2(legacy)
    expect(cfg.identity?.name).toBe('旧员工')
    expect(cfg.commerce?.industry).toBe('coating')
  })

  it('upgradeLegacyToV2 handles empty input', () => {
    const cfg = upgradeLegacyToV2()
    expect(cfg.identity).toBeDefined()
  })

  it('validateEmployeeConfigV2 rejects missing identity name', () => {
    const cfg = createEmptyEmployeeConfigV2()
    const result = validateEmployeeConfigV2(cfg)
    expect(result.valid).toBe(false)
    expect(result.errors.length).toBeGreaterThan(0)
  })

  it('validateEmployeeConfigV2 passes when required fields set', () => {
    const cfg = createEmptyEmployeeConfigV2()
    cfg.identity = { ...cfg.identity, name: '测试员工', id: 'emp-1', version: '1.0.0' }
    cfg.collaboration = { workflow: { workflow_id: 42 } }
    const result = validateEmployeeConfigV2(cfg)
    expect(result.valid).toBe(true)
    expect(result.errors).toEqual([])
  })
})
