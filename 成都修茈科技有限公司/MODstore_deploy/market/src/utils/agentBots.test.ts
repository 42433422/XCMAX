import { beforeEach, describe, expect, it } from 'vitest'
import {
  BUILTIN_BOTS,
  loadActiveBotId,
  loadAllBots,
  loadFavorites,
  loadMyBots,
  saveActiveBotId,
  saveFavorites,
  saveMyBots,
} from './agentBots'

describe('agentBots', () => {
  beforeEach(() => {
    if (typeof localStorage !== 'undefined') localStorage.clear()
  })

  it('returns builtin bots in loadAllBots when nothing saved', () => {
    const all = loadAllBots()
    expect(all.length).toBeGreaterThanOrEqual(BUILTIN_BOTS.length)
    expect(all[0].builtin).toBe(true)
  })

  it('persists my bots and merges them in', () => {
    saveMyBots([
      {
        id: 'mybot_1',
        name: 'My Helper',
        desc: 'mine',
        icon: '⚙️',
        category: 'mine',
        mine: true,
      },
    ])
    const my = loadMyBots()
    expect(my.length).toBe(1)
    expect(my[0].mine).toBe(true)
    const all = loadAllBots()
    expect(all.find((b) => b.id === 'mybot_1')).toBeTruthy()
  })

  it('persists favorites', () => {
    const favSet = new Set(['builtin_redbook'])
    saveFavorites(favSet)
    const all = loadAllBots()
    const target = all.find((b) => b.id === 'builtin_redbook')
    expect(target?.favorite).toBe(true)
    expect(loadFavorites().has('builtin_redbook')).toBe(true)
  })

  it('persists active bot id', () => {
    saveActiveBotId('builtin_coder')
    expect(loadActiveBotId()).toBe('builtin_coder')
  })
})
