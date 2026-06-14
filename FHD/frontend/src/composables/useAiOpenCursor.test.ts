import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createRouter, createMemoryHistory } from 'vue-router'
import {
  aiopenCursorEnabled,
  setAiOpenCursorEnabled,
  initAiOpenCursor,
  useAiOpenCursor,
} from './useAiOpenCursor'

vi.mock('@/utils/apiBase', () => ({
  getApiBase: () => 'http://127.0.0.1:5000',
}))

describe('useAiOpenCursor', () => {
  beforeEach(() => {
    localStorage.clear()
    aiopenCursorEnabled.value = false
  })

  it('setAiOpenCursorEnabled toggles ref and localStorage', () => {
    setAiOpenCursorEnabled(true)
    expect(aiopenCursorEnabled.value).toBe(true)
    expect(localStorage.getItem('xcagi_aiopen_remote_control')).toBe('1')
    setAiOpenCursorEnabled(false)
    expect(aiopenCursorEnabled.value).toBe(false)
  })

  it('initAiOpenCursor stores router reference', () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/', component: { template: '<div />' } }],
    })
    expect(() => initAiOpenCursor(router)).not.toThrow()
  })

  it('useAiOpenCursor returns cursor state API', () => {
    const api = useAiOpenCursor()
    expect(api.enabled).toBeDefined()
    expect(typeof api.setEnabled).toBe('function')
  })
})
