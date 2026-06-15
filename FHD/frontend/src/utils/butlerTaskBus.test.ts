import { describe, expect, it } from 'vitest'
import { publishButlerTask } from './butlerTaskBus'

describe('butlerTaskBus', () => {
  it('publishButlerTask is no-op', () => {
    expect(() => publishButlerTask({ id: 't1' })).not.toThrow()
  })
})
