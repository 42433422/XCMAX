import { describe, expect, it } from 'vitest'
import { dataSourceHasArtIcon, dataSourceIconMarkup } from './dataSourceIcons'

describe('dataSourceIcons', () => {
  it('returns empty for unknown icon', () => {
    expect(dataSourceIconMarkup('__missing_icon__')).toBe('')
    expect(dataSourceHasArtIcon('__missing_icon__')).toBe(false)
  })

  it('prefers the colored art asset when present', () => {
    expect(dataSourceHasArtIcon('qq')).toBe(true)
    const markup = dataSourceIconMarkup('qq')
    expect(markup).toContain('<img')
    expect(markup).toContain('data-source-card-icon--art')
  })

  it('falls back to the monochrome svg glyph', () => {
    expect(dataSourceHasArtIcon('foxmail')).toBe(false)
    const markup = dataSourceIconMarkup('foxmail')
    if (markup) {
      expect(markup).toContain('<svg')
    } else {
      expect(markup).toBe('')
    }
  })
})
