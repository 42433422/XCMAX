import { describe, expect, it } from 'vitest'
import {
  applyTemplateV2,
  createEmptyEmployeeConfigV2,
  upgradeLegacyToV2,
  validateEmployeeConfigV2,
} from './employeeConfigV2'

describe('employeeConfigV2', () => {
  it('creates a workflow employee config with required defaults', () => {
    const config = createEmptyEmployeeConfigV2()

    expect(config.identity.artifact).toBe('employee_pack')
    expect(config.cognition.agent.model.provider).toBe('auto')
    expect(config.cognition.agent.model.model_name).toBe('auto')
    expect(config.collaboration.workflow.workflow_id).toBe(0)
  })

  it('allows overriding default LLM vendor/model', () => {
    const config = createEmptyEmployeeConfigV2({
      model: { provider: 'openai', model_name: 'gpt-4o-mini' },
    })
    expect(config.cognition.agent.model.provider).toBe('openai')
    expect(config.cognition.agent.model.model_name).toBe('gpt-4o-mini')
  })

  it('applies templates without mutating base defaults', () => {
    const phone = applyTemplateV2('phone')
    const workflow = applyTemplateV2('workflow')

    expect(phone.perception.audio.enabled).toBe(true)
    expect(workflow.perception).toBeUndefined()
  })

  it('upgrades legacy manifest fields into v2 shape', () => {
    const upgraded = upgradeLegacyToV2({
      id: 'sales-agent',
      name: '销售员工',
      panel_summary: '负责线索跟进',
      workflow_employees: [{ workflow_id: 42 }],
      commerce: { price: 99 },
    })

    expect(upgraded.identity.id).toBe('sales-agent')
    expect(upgraded.cognition.agent.system_prompt).toBe('负责线索跟进')
    expect(upgraded.collaboration.workflow.workflow_id).toBe(42)
    expect(upgraded.commerce.price).toBe(99)
  })

  it('validates required identity and workflow fields', () => {
    const invalid = validateEmployeeConfigV2(createEmptyEmployeeConfigV2())
    const validConfig = createEmptyEmployeeConfigV2()
    validConfig.identity.id = 'agent-1'
    validConfig.identity.name = 'Agent 1'
    validConfig.collaboration.workflow.workflow_id = 10

    expect(invalid.valid).toBe(false)
    expect(invalid.errors).toContain('缺少 identity.id')
    expect(validateEmployeeConfigV2(validConfig)).toEqual({ valid: true, errors: [] })
  })
})
