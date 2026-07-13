import { afterEach, describe, expect, it, vi } from 'vitest'
import { plainTextFromHtml } from './htmlPlainText'

describe('plainTextFromHtml', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('extracts visible text and preserves line breaks', () => {
    expect(plainTextFromHtml('<p>a<br>b&nbsp;c</p>')).toBe('a\nb c')
  })

  it('omits executable and embedded element contents', () => {
    expect(plainTextFromHtml('safe<script>alert(1)</script><style>bad{}</style>end')).toBe('safeend')
  })

  it('uses an inert scanner when DOMParser is unavailable', () => {
    vi.stubGlobal('DOMParser', undefined)
    expect(plainTextFromHtml('safe<br>text<script>alert(1)</script>')).toBe(
      'safe\ntextalert(1)',
    )
  })
})
