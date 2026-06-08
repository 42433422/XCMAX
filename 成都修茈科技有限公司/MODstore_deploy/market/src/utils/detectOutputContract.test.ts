import { describe, expect, it } from 'vitest'
import { detectOutputContract, outputContractSystemRules } from './detectOutputContract'

describe('detectOutputContract', () => {
  it('detects json-only prompts', () => {
    expect(detectOutputContract('reply json only')).toBe('json')
    expect(detectOutputContract('仅 JSON 输出')).toBe('json')
  })

  it('detects code-only prompts', () => {
    expect(detectOutputContract('code only: hello world')).toBe('code')
    expect(detectOutputContract('只输出代码')).toBe('code')
  })

  it('returns null for normal chat', () => {
    expect(detectOutputContract('reply ok')).toBe(null)
    expect(detectOutputContract('1+1')).toBe(null)
  })

  it('outputContractSystemRules forbids fences for json', () => {
    const rules = outputContractSystemRules('json')
    expect(rules).toContain('禁止')
    expect(rules).toContain('```')
  })
})
