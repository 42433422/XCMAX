import { afterEach, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { config } from '@vue/test-utils'
import i18n from '@/i18n'

// 组件测试默认注入共享 i18n（多视图用 useI18n()，否则 mount 会抛
// "Need to install with `app.use`"）。单测可在 global.plugins 覆盖。
config.global.plugins = [i18n]

// matchMedia stub 用「普通函数」而非 vi.fn()：部分用例调用
// vi.restoreAllMocks()/resetAllMocks() 会把 vi.fn() 实现清空（返回 undefined），
// 而异步组件（如 MainLayout 的 onMounted）可能在用例结束后才读 window.matchMedia，
// 跨文件 fork 复用时就会抛 "reading 'matches'" 未捕获异常。普通函数不受 mock 重置影响。
function installMatchMediaStub() {
  const noop = () => {}
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    configurable: true,
    value: (query: string) => ({
      matches: false,
      media: String(query ?? ''),
      onchange: null,
      addListener: noop,
      removeListener: noop,
      addEventListener: noop,
      removeEventListener: noop,
      dispatchEvent: () => false,
    }),
  })
}

beforeEach(() => {
  setActivePinia(createPinia())
  installMatchMediaStub()
})

installMatchMediaStub()

afterEach(() => {
  vi.unstubAllEnvs()
  try {
    localStorage.clear()
  } catch {
    /* jsdom */
  }
})
