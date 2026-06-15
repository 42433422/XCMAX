import { describe, it, expect } from 'vitest'
import { createEmptyEmployeeConfigV2, validateEmployeeConfigV2 } from './employeeConfigV2'

function validBase() {
  const cfg = createEmptyEmployeeConfigV2()
  cfg.identity = { ...cfg.identity, id: 'e1', name: '员工', version: '1.0.0' }
  cfg.collaboration = { workflow: { workflow_id: 7 } }
  return cfg
}

describe('validateEmployeeConfigV2 branch sweep', () => {
  it('rejects non-object input', () => {
    expect(validateEmployeeConfigV2(null).valid).toBe(false)
    expect(validateEmployeeConfigV2('x').valid).toBe(false)
  })

  it('flags missing workflow_id', () => {
    const cfg = createEmptyEmployeeConfigV2()
    cfg.identity = { ...cfg.identity, id: 'e', name: 'n', version: '1' }
    const r = validateEmployeeConfigV2(cfg)
    expect(r.errors.some((e) => e.includes('workflow'))).toBe(true)
  })

  it('rejects invalid role.tone', () => {
    const cfg = validBase()
    cfg.cognition!.agent!.role = { tone: 'angry' }
    const r = validateEmployeeConfigV2(cfg)
    expect(r.errors.some((e) => e.includes('tone'))).toBe(true)
  })

  it('accepts valid role.tone', () => {
    const cfg = validBase()
    cfg.cognition!.agent!.role = { tone: 'friendly' }
    expect(validateEmployeeConfigV2(cfg).valid).toBe(true)
  })

  it('rejects invalid model.provider', () => {
    const cfg = validBase()
    cfg.cognition!.agent!.model = { provider: 'unknown-llm' }
    expect(validateEmployeeConfigV2(cfg).errors.some((e) => e.includes('provider'))).toBe(true)
  })

  it('rejects temperature out of range', () => {
    const cfg = validBase()
    cfg.cognition!.agent!.model = { temperature: 2 }
    expect(validateEmployeeConfigV2(cfg).errors.some((e) => e.includes('temperature'))).toBe(true)
  })

  it('rejects top_p out of range', () => {
    const cfg = validBase()
    cfg.cognition!.agent!.model = { top_p: -1 }
    expect(validateEmployeeConfigV2(cfg).errors.some((e) => e.includes('top_p'))).toBe(true)
  })

  it('rejects non-positive max_tokens', () => {
    const cfg = validBase()
    cfg.cognition!.agent!.model = { max_tokens: 0 }
    expect(validateEmployeeConfigV2(cfg).errors.some((e) => e.includes('max_tokens'))).toBe(true)
  })

  it('rejects non-array behavior_rules', () => {
    const cfg = validBase()
    cfg.cognition!.agent!.behavior_rules = 'nope' as unknown as unknown[]
    expect(validateEmployeeConfigV2(cfg).errors.some((e) => e.includes('behavior_rules'))).toBe(true)
  })

  it('rejects non-array few_shot_examples', () => {
    const cfg = validBase()
    cfg.cognition!.agent!.few_shot_examples = 5 as unknown as unknown[]
    expect(validateEmployeeConfigV2(cfg).errors.some((e) => e.includes('few_shot_examples'))).toBe(true)
  })

  it('rejects invalid access_level', () => {
    const cfg = validBase()
    cfg.collaboration!.permissions = { access_level: 'super' }
    expect(validateEmployeeConfigV2(cfg).errors.some((e) => e.includes('access_level'))).toBe(true)
  })

  it('flags ASR without voice_output', () => {
    const cfg = validBase()
    cfg.perception = { audio: { asr: { enabled: true } } }
    expect(validateEmployeeConfigV2(cfg).errors.some((e) => e.includes('ASR'))).toBe(true)
  })

  it('flags long_term knowledge without cognition.agent', () => {
    const cfg = validBase()
    cfg.cognition = { agent: undefined }
    cfg.memory = { long_term: { enabled: true } }
    const r = validateEmployeeConfigV2(cfg)
    expect(r.errors.some((e) => e.includes('知识库') || e.includes('cognition'))).toBe(true)
  })
})
