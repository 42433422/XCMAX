import { describe, expect, it, beforeEach } from 'vitest'
import { useImSounds } from './useImSounds'

describe('useImSounds', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('defaults mode to all', () => {
    const { mode } = useImSounds()
    expect(mode.value).toBe('all')
  })

  it('persists mode changes', () => {
    const { setMode, mode } = useImSounds()
    setMode('mute')
    expect(mode.value).toBe('mute')
    expect(localStorage.getItem('xcagi.im.soundMode')).toBe('mute')
  })

  it('playOutgoing no-ops in mute', () => {
    const { setMode, playOutgoing } = useImSounds()
    setMode('mute')
    expect(() => playOutgoing()).not.toThrow()
  })

  it('playIncoming no-ops in mute', async () => {
    const { setMode, playIncoming } = useImSounds()
    setMode('mute')
    await expect(playIncoming('hi')).resolves.toBeUndefined()
  })
})
