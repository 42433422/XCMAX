import { afterEach, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

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
