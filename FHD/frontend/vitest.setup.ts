import { afterEach, beforeEach, vi } from 'vitest'
import { config } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { i18n } from '@/i18n'

config.global.plugins = [i18n]

function installMatchMediaMock() {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(() => false),
    })),
  })
}

function installEventSourceMock() {
  class MockEventSource {
    static CONNECTING = 0
    static OPEN = 1
    static CLOSED = 2

    url: string
    readyState = MockEventSource.CONNECTING
    onopen: ((event: Event) => void) | null = null
    onmessage: ((event: MessageEvent) => void) | null = null
    onerror: ((event: Event) => void) | null = null

    constructor(url: string) {
      this.url = url
    }

    close() {
      this.readyState = MockEventSource.CLOSED
    }

    addEventListener = vi.fn()
    removeEventListener = vi.fn()
    dispatchEvent = vi.fn(() => false)
  }

  Object.defineProperty(window, 'EventSource', {
    writable: true,
    configurable: true,
    value: MockEventSource,
  })
  Object.defineProperty(globalThis, 'EventSource', {
    writable: true,
    configurable: true,
    value: MockEventSource,
  })
}

beforeEach(() => {
  setActivePinia(createPinia())
  installMatchMediaMock()
  installEventSourceMock()
})

afterEach(() => {
  vi.unstubAllEnvs()
  try {
    localStorage.clear()
  } catch {
    /* jsdom */
  }
})
