import { describe, expect, it } from 'vitest'
import { LegacyProMode, useProMode, useProModeStore } from './index'

describe('legacy/pro-mode index', () => {
  it('re-exports LegacyProMode component', () => {
    expect(LegacyProMode).toBeDefined()
  })

  it('re-exports useProMode composable', () => {
    expect(typeof useProMode).toBe('function')
  })

  it('re-exports useProModeStore', () => {
    expect(typeof useProModeStore).toBe('function')
  })
})
