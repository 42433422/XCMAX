import { describe, expect, it } from 'vitest'
import { initialOptionalTemplateIndex, isOfficeEltToolMessage, pickOptionalTemplate } from './optionalTemplateSelection'

describe('optional template selection', () => {
  it('starts empty when optional and applies only an explicit in-range pick', () => {
    expect(initialOptionalTemplateIndex(true)).toBe(-1)
    expect(initialOptionalTemplateIndex(false)).toBe(0)
    expect(pickOptionalTemplate(2, -1)).toBeNull()
    expect(pickOptionalTemplate(2, 1)).toBe(1)
    expect(pickOptionalTemplate(2, 1, true)).toBeNull()
    expect(pickOptionalTemplate(2, 1.5)).toBeNull()
    expect(pickOptionalTemplate(2, Number.NaN)).toBeNull()
  })

  it('recognizes an office import that must not be aborted', () => {
    expect(isOfficeEltToolMessage('@uploads/宗南.xlsx导入数据库')).toBe(true)
    expect(isOfficeEltToolMessage('hello')).toBe(false)
  })
})
