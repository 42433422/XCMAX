import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: '/chat', name: 'chat' }),
}))

import { useRoute, useRouter } from 'vue-router'
import { useModsStore } from '@/stores/mods'
import { useAppProMode } from './useAppProMode'

describe('useAppProMode', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    document.body.className = ''
    delete (window as Window & { __XCAGI_IS_PRO_MODE?: boolean }).__XCAGI_IS_PRO_MODE
  })

  afterEach(() => {
    document.getElementById('proModeOverlay')?.remove()
  })

  it('readProModeStateFromDom reads window flag when overlay missing', () => {
    ;(window as Window & { __XCAGI_IS_PRO_MODE?: boolean }).__XCAGI_IS_PRO_MODE = true
    const proMode = useAppProMode(useModsStore(), useRouter(), useRoute())
    expect(proMode.readProModeStateFromDom()).toBe(true)
  })

  it('readProModeStateFromDom reads body class', () => {
    document.body.classList.add('pro-mode-active')
    const proMode = useAppProMode(useModsStore(), useRouter(), useRoute())
    expect(proMode.readProModeStateFromDom()).toBe(true)
  })
})
