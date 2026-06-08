import { describe, it, expect } from 'vitest'
import { extractModNames } from './useStartupSplash'

describe('useStartupSplash helpers', () => {
  it('extractModNames deduplicates by name or id', () => {
    expect(
      extractModNames([
        { name: 'Alpha', id: 'a' },
        { name: 'Alpha', id: 'b' },
        { id: 'gamma' },
        { name: '', id: '' },
      ])
    ).toEqual(['Alpha', 'gamma'])
  })

  it('extractModNames returns empty for non-array input', () => {
    expect(extractModNames(null as unknown as unknown[])).toEqual([])
  })
})
