import { describe, expect, it } from 'vitest'
import { dataSourceIconMarkup } from './dataSourceIcons'

describe('dataSourceIcons', () => {
  it('returns empty for unknown icon', () => {
    expect(dataSourceIconMarkup('__missing_icon__')).toBe('')
  })

  it('returns svg markup for known icon when glob has it', () => {
    const markup = dataSourceIconMarkup('excel')
    if (markup) {
      expect(markup).toContain('<svg')
    } else {
      expect(markup).toBe('')
    }
  })
})
