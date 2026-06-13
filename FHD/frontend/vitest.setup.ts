import { afterEach, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { config } from '@vue/test-utils'
import i18n from '@/i18n'

// 组件测试默认注入共享 i18n（多视图用 useI18n()，否则 mount 会抛
// "Need to install with `app.use`"）。单测可在 global.plugins 覆盖。
config.global.plugins = [i18n]

beforeEach(() => {
  setActivePinia(createPinia())
})

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

afterEach(() => {
  vi.unstubAllEnvs()
  try {
    localStorage.clear()
  } catch {
    /* jsdom */
  }
})
