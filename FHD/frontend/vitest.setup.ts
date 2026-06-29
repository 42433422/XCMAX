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

function installAnimationFrameMock() {
  const requestFrame = (callback: FrameRequestCallback) => window.setTimeout(() => {
    callback(window.performance?.now?.() ?? Date.now())
  }, 16)
  const cancelFrame = (handle: number) => window.clearTimeout(handle)

  if (typeof window.requestAnimationFrame !== 'function' || typeof globalThis.requestAnimationFrame !== 'function') {
    Object.defineProperty(window, 'requestAnimationFrame', {
      writable: true,
      configurable: true,
      value: requestFrame,
    })
    Object.defineProperty(globalThis, 'requestAnimationFrame', {
      writable: true,
      configurable: true,
      value: requestFrame,
    })
  }

  if (typeof window.cancelAnimationFrame !== 'function' || typeof globalThis.cancelAnimationFrame !== 'function') {
    Object.defineProperty(window, 'cancelAnimationFrame', {
      writable: true,
      configurable: true,
      value: cancelFrame,
    })
    Object.defineProperty(globalThis, 'cancelAnimationFrame', {
      writable: true,
      configurable: true,
      value: cancelFrame,
    })
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  installMatchMediaMock()
  installEventSourceMock()
  installAnimationFrameMock()
})

afterEach(() => {
  vi.unstubAllEnvs()
  try {
    localStorage.clear()
  } catch {
    /* jsdom */
  }
})
