import { describe, expect, it } from 'vitest'
import { WORKFLOW_SANDBOX_PRESETS, presetById } from './workflowSandboxPresets'

describe('WORKFLOW_SANDBOX_PRESETS', () => {
  it('has at least 4 presets', () => {
    expect(WORKFLOW_SANDBOX_PRESETS.length).toBeGreaterThanOrEqual(4)
  })

  it('each preset has required fields', () => {
    for (const p of WORKFLOW_SANDBOX_PRESETS) {
      expect(p.id).toBeTruthy()
      expect(p.label).toBeTruthy()
      expect(typeof p.input_data).toBe('object')
    }
  })

  it('contains minimal preset', () => {
    const minimal = WORKFLOW_SANDBOX_PRESETS.find((p) => p.id === 'minimal')
    expect(minimal).toBeDefined()
    expect(minimal!.input_data).toEqual({})
  })

  it('contains topic preset', () => {
    const topic = WORKFLOW_SANDBOX_PRESETS.find((p) => p.id === 'topic')
    expect(topic).toBeDefined()
    expect(topic!.input_data).toHaveProperty('topic')
  })

  it('contains phone_wechat preset', () => {
    const phone = WORKFLOW_SANDBOX_PRESETS.find((p) => p.id === 'phone_wechat')
    expect(phone).toBeDefined()
    expect(phone!.input_data).toHaveProperty('channel', 'wechat')
  })

  it('contains flags preset', () => {
    const flags = WORKFLOW_SANDBOX_PRESETS.find((p) => p.id === 'flags')
    expect(flags).toBeDefined()
    expect(flags!.input_data).toHaveProperty('approved', true)
  })
})

describe('presetById', () => {
  it('returns matching preset for valid id', () => {
    const result = presetById('minimal')
    expect(result).not.toBeNull()
    expect(result!.id).toBe('minimal')
  })

  it('returns null for unknown id', () => {
    expect(presetById('non_existent')).toBeNull()
  })

  it('returns null for empty string', () => {
    expect(presetById('')).toBeNull()
  })

  it('returns correct preset for each known id', () => {
    for (const p of WORKFLOW_SANDBOX_PRESETS) {
      expect(presetById(p.id)).toEqual(p)
    }
  })
})
