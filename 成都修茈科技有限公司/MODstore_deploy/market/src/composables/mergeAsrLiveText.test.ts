import { describe, expect, it } from 'vitest'
import { mergeAsrLiveText } from './mergeAsrLiveText'

describe('mergeAsrLiveText', () => {
  it('extends partial with longer hypothesis', () => {
    expect(mergeAsrLiveText('问题就是我', '问题就是我这边说的字')).toBe('问题就是我这边说的字')
  })

  it('does not regress when online partial shrinks', () => {
    expect(mergeAsrLiveText('问题就是我这边说的字', '的字他没')).toBe('问题就是我这边说的字')
  })

  it('prefers final offline text', () => {
    expect(
      mergeAsrLiveText('问题就是我这边说的字', '问题就是我这边说的字，他没显示全', true),
    ).toBe('问题就是我这边说的字，他没显示全')
  })

  it('joins overlapping suffix segments', () => {
    expect(mergeAsrLiveText('今天天气', '气怎么样')).toBe('今天天气怎么样')
  })
})
