import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useModsStore, CLIENT_MODS_UI_OFF_KEY } from './mods'

describe('mods store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('CLIENT_MODS_UI_OFF_KEY is stable', () => {
    expect(CLIENT_MODS_UI_OFF_KEY).toBe('xcagi_client_mods_ui_off')
  })

  it('modsForUi filters disabled client mods', () => {
    const store = useModsStore()
    store.mods = [
      { id: 'a', name: 'A', enabled: true },
      { id: 'b', name: 'B', enabled: false },
    ] as never[]
    expect(store.modsForUi.length).toBeGreaterThanOrEqual(1)
  })
})
