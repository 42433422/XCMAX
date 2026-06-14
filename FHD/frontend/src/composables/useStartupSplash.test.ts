import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { setActivePinia, createPinia } from 'pinia'
import { extractModNames, useStartupSplash } from './useStartupSplash'

vi.mock('@/stores/mods', () => ({
  useModsStore: () => ({
    modsForUi: [],
    fetchMods: vi.fn().mockResolvedValue(undefined),
  }),
}))

describe('useStartupSplash', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('extractModNames maps mod list', () => {
    expect(extractModNames([{ name: 'a' }, { name: 'b' }])).toEqual(['a', 'b'])
    expect(extractModNames(null)).toEqual([])
  })

  it('returns splash state refs', () => {
    const splash = useStartupSplash()
    expect(splash.startupVisible).toBeDefined()
    expect(splash.appReady).toBeDefined()
    expect(typeof splash.skipStartupSplash).toBe('function')
  })

  it('skipStartupSplash sets appReady', () => {
    const splash = useStartupSplash()
    splash.skipStartupSplash()
    expect(splash.appReady.value).toBe(true)
    expect(splash.startupVisible.value).toBe(false)
  })

  it('dismissStartupSplashImmediate hides splash', () => {
    const splash = useStartupSplash()
    splash.startupVisible.value = true
    splash.dismissStartupSplashImmediate()
    expect(splash.startupVisible.value).toBe(false)
  })
})
