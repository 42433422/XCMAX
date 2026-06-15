import { describe, expect, it } from 'vitest'
import { pickDefaultActiveModId } from './xcagiModPick'

describe('xcagiModPick', () => {
  it('returns empty for empty list', () => {
    expect(pickDefaultActiveModId([])).toBe('')
  })

  it('returns sole mod id', () => {
    expect(pickDefaultActiveModId([{ id: 'only-one' }])).toBe('only-one')
  })

  it('prefers single primary', () => {
    expect(
      pickDefaultActiveModId([
        { id: 'b-mod' },
        { id: 'a-mod', primary: true },
        { id: 'c-mod' },
      ]),
    ).toBe('a-mod')
  })

  it('falls back to lexicographic first when no unique primary', () => {
    expect(
      pickDefaultActiveModId([
        { id: 'z-mod' },
        { id: 'a-mod' },
        { id: 'm-mod', primary: true },
        { id: 'n-mod', primary: true },
      ]),
    ).toBe('a-mod')
  })
})
