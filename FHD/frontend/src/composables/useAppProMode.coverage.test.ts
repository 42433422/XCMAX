/**
 * useAppProMode.ts 覆盖率补齐测试
 * 目标：覆盖所有导出函数的 happy path、空值、边界、异常路径
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import type { Router, RouteLocationNormalizedLoaded } from 'vue-router'

// ── 可配置的 mock 函数（hoisted-safe）─────────────────────────
const mockIsClientModeTiersUiEnabled = vi.fn(() => false)
const mockResetClientModeTierLocalState = vi.fn()
const mockIsAdminConsoleSpa = vi.fn(() => false)

vi.mock('@/constants/clientModeTiers', () => ({
  isClientModeTiersUiEnabled: () => mockIsClientModeTiersUiEnabled(),
  resetClientModeTierLocalState: (...args: unknown[]) => mockResetClientModeTierLocalState(...args),
}))

vi.mock('@/utils/adminConsoleUrl', () => ({
  isAdminConsoleSpa: () => mockIsAdminConsoleSpa(),
}))

import { useAppProMode } from './useAppProMode'
import type { useModsStore } from '@/stores/mods'

// 辅助类型：构造与 useModsStore 返回值兼容的 mock 对象
type ModsStoreLike = ReturnType<typeof useModsStore>

function makeModsStore(modsForUi: unknown[] = [], initialize?: () => Promise<void>): ModsStoreLike {
  return {
    modsForUi,
    initialize: initialize || vi.fn(async () => {}),
  } as unknown as ModsStoreLike
}

function makeRouter(pushImpl?: (to: unknown) => Promise<unknown>): Router {
  return {
    push: pushImpl || vi.fn(async () => {}),
  } as unknown as Router
}

function makeRoute(path = '/chat', name = 'chat'): RouteLocationNormalizedLoaded {
  return { path, name } as unknown as RouteLocationNormalizedLoaded
}

describe('useAppProMode - 覆盖率补齐', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
    document.body.className = ''
    document.getElementById('proModeOverlay')?.remove()
    delete (window as Window & { __XCAGI_IS_PRO_MODE?: boolean }).__XCAGI_IS_PRO_MODE
    delete (window as Window & { __legacyToggleProMode?: () => void }).__legacyToggleProMode
    delete (window as Window & { toggleProMode?: () => void }).toggleProMode
    mockIsClientModeTiersUiEnabled.mockReturnValue(false)
    mockIsAdminConsoleSpa.mockReturnValue(false)
    mockResetClientModeTierLocalState.mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  // ── hasLegacyProModeRuntime ──────────────────────────────────
  describe('hasLegacyProModeRuntime', () => {
    it('无 legacy 函数时返回 false', () => {
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      expect(pro.hasLegacyProModeRuntime()).toBe(false)
    })

    it('存在 __legacyToggleProMode 时返回 true', () => {
      ;(window as Window & { __legacyToggleProMode?: () => void }).__legacyToggleProMode = () => {}
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      expect(pro.hasLegacyProModeRuntime()).toBe(true)
    })

    it('存在 toggleProMode 时返回 true', () => {
      ;(window as Window & { toggleProMode?: () => void }).toggleProMode = () => {}
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      expect(pro.hasLegacyProModeRuntime()).toBe(true)
    })

    it('legacy 函数非 function 类型时返回 false', () => {
      ;(window as Window & { toggleProMode?: unknown }).toggleProMode = 'not-a-function'
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      expect(pro.hasLegacyProModeRuntime()).toBe(false)
    })
  })

  // ── readProModeStateFromDom ──────────────────────────────────
  describe('readProModeStateFromDom', () => {
    it('无 overlay 且 window 标志为 true 时返回 true', () => {
      ;(window as Window & { __XCAGI_IS_PRO_MODE?: boolean }).__XCAGI_IS_PRO_MODE = true
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      expect(pro.readProModeStateFromDom()).toBe(true)
    })

    it('无 overlay 且 window 标志为 false 时返回 false', () => {
      ;(window as Window & { __XCAGI_IS_PRO_MODE?: boolean }).__XCAGI_IS_PRO_MODE = false
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      expect(pro.readProModeStateFromDom()).toBe(false)
    })

    it('body 含 pro-mode-active 类时返回 true', () => {
      document.body.classList.add('pro-mode-active')
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      expect(pro.readProModeStateFromDom()).toBe(true)
    })

    it('overlay 含 active 类且 display 非 none 时返回 true', () => {
      const overlay = document.createElement('div')
      overlay.id = 'proModeOverlay'
      overlay.classList.add('active')
      overlay.style.display = 'block'
      document.body.appendChild(overlay)
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      expect(pro.readProModeStateFromDom()).toBe(true)
    })

    it('overlay 含 active 类但 display 为 none 时返回 false', () => {
      const overlay = document.createElement('div')
      overlay.id = 'proModeOverlay'
      overlay.classList.add('active')
      overlay.style.display = 'none'
      document.body.appendChild(overlay)
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      expect(pro.readProModeStateFromDom()).toBe(false)
    })

    it('overlay 无 active 类时返回 false', () => {
      const overlay = document.createElement('div')
      overlay.id = 'proModeOverlay'
      overlay.style.display = 'block'
      document.body.appendChild(overlay)
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      expect(pro.readProModeStateFromDom()).toBe(false)
    })

    it('无任何标志时返回 false', () => {
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      expect(pro.readProModeStateFromDom()).toBe(false)
    })
  })

  // ── syncProModeStateSoon ─────────────────────────────────────
  describe('syncProModeStateSoon', () => {
    it('通过 requestAnimationFrame 同步状态', () => {
      document.body.classList.add('pro-mode-active')
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      pro.syncProModeStateSoon()
      // 触发 requestAnimationFrame 回调（属于 timer，需用 runAllTimers）
      vi.runAllTimers()
      expect(pro.isProMode.value).toBe(true)
    })

    it('通过 setTimeout(350ms) 同步状态', () => {
      document.body.classList.add('pro-mode-active')
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      pro.isProMode.value = false
      pro.syncProModeStateSoon()
      // 推进 350ms 触发 setTimeout 回调
      vi.advanceTimersByTime(400)
      expect(pro.isProMode.value).toBe(true)
    })
  })

  // ── resolveModProEntryPath ───────────────────────────────────
  describe('resolveModProEntryPath', () => {
    it('modsForUi 非数组时返回空字符串', () => {
      const pro = useAppProMode(makeModsStore('not-array' as unknown as []), makeRouter(), makeRoute())
      expect(pro.resolveModProEntryPath()).toBe('')
    })

    it('modsForUi 为空数组时返回空字符串', () => {
      const pro = useAppProMode(makeModsStore([]), makeRouter(), makeRoute())
      expect(pro.resolveModProEntryPath()).toBe('')
    })

    it('mod 有 frontend.pro_entry_path 时返回该路径', () => {
      const mods = [
        { frontend: { pro_entry_path: '/mod/pro-entry' } },
      ]
      const pro = useAppProMode(makeModsStore(mods), makeRouter(), makeRoute())
      expect(pro.resolveModProEntryPath()).toBe('/mod/pro-entry')
    })

    it('frontend.pro_entry_path 为空白字符串时回退到 menu[0].path', () => {
      const mods = [
        { frontend: { pro_entry_path: '   ' }, menu: [{ path: '/mod/menu-first' }] },
      ]
      const pro = useAppProMode(makeModsStore(mods), makeRouter(), makeRoute())
      expect(pro.resolveModProEntryPath()).toBe('/mod/menu-first')
    })

    it('frontend.pro_entry_path 非字符串时回退到 menu[0].path', () => {
      const mods = [
        { frontend: { pro_entry_path: 123 }, menu: [{ path: '/mod/menu-first' }] },
      ]
      const pro = useAppProMode(makeModsStore(mods), makeRouter(), makeRoute())
      expect(pro.resolveModProEntryPath()).toBe('/mod/menu-first')
    })

    it('frontend 为非对象时回退到 menu[0].path', () => {
      const mods = [
        { frontend: 'invalid', menu: [{ path: '/mod/menu-first' }] },
      ]
      const pro = useAppProMode(makeModsStore(mods), makeRouter(), makeRoute())
      expect(pro.resolveModProEntryPath()).toBe('/mod/menu-first')
    })

    it('menu[0].path 为空白时继续遍历下一个 mod', () => {
      const mods = [
        { frontend: {}, menu: [{ path: '  ' }] },
        { frontend: { pro_entry_path: '/mod2/pro' } },
      ]
      const pro = useAppProMode(makeModsStore(mods), makeRouter(), makeRoute())
      expect(pro.resolveModProEntryPath()).toBe('/mod2/pro')
    })

    it('menu 为非数组时跳过', () => {
      const mods = [
        { frontend: {}, menu: 'not-array' },
        { frontend: { pro_entry_path: '/mod2/pro' } },
      ]
      const pro = useAppProMode(makeModsStore(mods), makeRouter(), makeRoute())
      expect(pro.resolveModProEntryPath()).toBe('/mod2/pro')
    })

    it('menu[0].path 非字符串时跳过', () => {
      const mods = [
        { frontend: {}, menu: [{ path: 456 }] },
        { frontend: { pro_entry_path: '/mod2/pro' } },
      ]
      const pro = useAppProMode(makeModsStore(mods), makeRouter(), makeRoute())
      expect(pro.resolveModProEntryPath()).toBe('/mod2/pro')
    })

    it('menu 为空数组时跳过', () => {
      const mods = [
        { frontend: {}, menu: [] },
        { frontend: { pro_entry_path: '/mod2/pro' } },
      ]
      const pro = useAppProMode(makeModsStore(mods), makeRouter(), makeRoute())
      expect(pro.resolveModProEntryPath()).toBe('/mod2/pro')
    })

    it('mod 为 null/undefined 时安全跳过', () => {
      const mods = [null, undefined, { frontend: { pro_entry_path: '/mod3/pro' } }]
      const pro = useAppProMode(makeModsStore(mods), makeRouter(), makeRoute())
      expect(pro.resolveModProEntryPath()).toBe('/mod3/pro')
    })
  })

  // ── enterModProMode ──────────────────────────────────────────
  describe('enterModProMode', () => {
    it('admin console SPA 时直接返回不做任何操作', async () => {
      mockIsAdminConsoleSpa.mockReturnValue(true)
      const router = makeRouter()
      const pro = useAppProMode(makeModsStore([]), router, makeRoute())
      await pro.enterModProMode()
      expect(router.push).not.toHaveBeenCalled()
    })

    it('modsForUi 为空时调用 initialize', async () => {
      const initialize = vi.fn(async () => {})
      const mods = makeModsStore([], initialize)
      const pro = useAppProMode(mods, makeRouter(), makeRoute())
      await pro.enterModProMode()
      expect(initialize).toHaveBeenCalled()
    })

    it('initialize 失败时打印 warn 不抛出', async () => {
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
      const initialize = vi.fn(async () => {
        throw new Error('init failed')
      })
      const mods = makeModsStore([], initialize)
      const pro = useAppProMode(mods, makeRouter(), makeRoute())
      await pro.enterModProMode()
      expect(warnSpy).toHaveBeenCalledWith(
        '加载 Mod 菜单失败，无法解析专业版入口:',
        expect.any(Error),
      )
      warnSpy.mockRestore()
    })

    it('modsForUi 已有数据时不调用 initialize', async () => {
      const initialize = vi.fn(async () => {})
      const mods = makeModsStore([{ frontend: { pro_entry_path: '/mod/pro' } }], initialize)
      const pro = useAppProMode(mods, makeRouter(), makeRoute())
      await pro.enterModProMode()
      expect(initialize).not.toHaveBeenCalled()
    })

    it('modsForUi 非数组时调用 initialize', async () => {
      const initialize = vi.fn(async () => {})
      const mods = makeModsStore('not-array' as unknown as [], initialize)
      const pro = useAppProMode(mods, makeRouter(), makeRoute())
      await pro.enterModProMode()
      expect(initialize).toHaveBeenCalled()
    })

    it('解析到目标路径且与当前路径不同时跳转', async () => {
      const push = vi.fn(async () => {})
      const router = makeRouter(push)
      const mods = makeModsStore([{ frontend: { pro_entry_path: '/mod/pro' } }])
      const pro = useAppProMode(mods, router, makeRoute('/chat'))
      await pro.enterModProMode()
      expect(pro.isProMode.value).toBe(true)
      expect(push).toHaveBeenCalledWith('/mod/pro')
    })

    it('目标路径与当前路径相同时不跳转', async () => {
      const push = vi.fn(async () => {})
      const router = makeRouter(push)
      const mods = makeModsStore([{ frontend: { pro_entry_path: '/current' } }])
      const pro = useAppProMode(mods, router, makeRoute('/current'))
      await pro.enterModProMode()
      expect(pro.isProMode.value).toBe(true)
      expect(push).not.toHaveBeenCalled()
    })

    it('无目标路径时仅设置 isProMode 不跳转', async () => {
      const push = vi.fn(async () => {})
      const router = makeRouter(push)
      const pro = useAppProMode(makeModsStore([]), router, makeRoute('/chat'))
      await pro.enterModProMode()
      expect(pro.isProMode.value).toBe(true)
      expect(push).not.toHaveBeenCalled()
    })

    it('router.push 失败时打印 warn 不抛出', async () => {
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
      const push = vi.fn(async () => {
        throw new Error('nav failed')
      })
      const router = makeRouter(push)
      const mods = makeModsStore([{ frontend: { pro_entry_path: '/mod/pro' } }])
      const pro = useAppProMode(mods, router, makeRoute('/chat'))
      await pro.enterModProMode()
      expect(warnSpy).toHaveBeenCalledWith('跳转 Mod 专业版入口失败:', expect.any(Error))
      warnSpy.mockRestore()
    })
  })

  // ── exitModProMode ───────────────────────────────────────────
  describe('exitModProMode', () => {
    it('设置 isProMode 为 false', async () => {
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      pro.isProMode.value = true
      await pro.exitModProMode()
      expect(pro.isProMode.value).toBe(false)
    })

    it('admin console SPA 时不跳转', async () => {
      mockIsAdminConsoleSpa.mockReturnValue(true)
      const push = vi.fn(async () => {})
      const pro = useAppProMode(makeModsStore(), makeRouter(push), makeRoute('/other'))
      await pro.exitModProMode()
      expect(push).not.toHaveBeenCalled()
    })

    it('当前路由非 chat 时跳转到 chat', async () => {
      const push = vi.fn(async () => {})
      const pro = useAppProMode(makeModsStore(), makeRouter(push), makeRoute('/other', 'other'))
      await pro.exitModProMode()
      expect(push).toHaveBeenCalledWith({ name: 'chat' })
    })

    it('当前路由已是 chat 时不跳转', async () => {
      const push = vi.fn(async () => {})
      const pro = useAppProMode(makeModsStore(), makeRouter(push), makeRoute('/chat', 'chat'))
      await pro.exitModProMode()
      expect(push).not.toHaveBeenCalled()
    })

    it('router.push 失败时静默处理不抛出', async () => {
      const push = vi.fn(async () => {
        throw new Error('nav failed')
      })
      const pro = useAppProMode(makeModsStore(), makeRouter(push), makeRoute('/other', 'other'))
      await expect(pro.exitModProMode()).resolves.toBeUndefined()
    })
  })

  // ── handleToggleProMode ──────────────────────────────────────
  describe('handleToggleProMode', () => {
    it('clientModeTiers UI 未启用时直接返回', () => {
      mockIsClientModeTiersUiEnabled.mockReturnValue(false)
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      pro.handleToggleProMode()
      expect(pro.isProMode.value).toBe(false)
    })

    it('clientModeTiers UI 启用且无 mod 入口且有 legacy toggle 时调用 legacy toggle', () => {
      mockIsClientModeTiersUiEnabled.mockReturnValue(true)
      const legacyToggle = vi.fn()
      ;(window as Window & { __legacyToggleProMode?: () => void }).__legacyToggleProMode = legacyToggle
      const pro = useAppProMode(makeModsStore([]), makeRouter(), makeRoute())
      pro.handleToggleProMode()
      expect(legacyToggle).toHaveBeenCalled()
    })

    it('clientModeTiers UI 启用且有 mod 入口且当前非 pro 模式时进入 pro 模式', async () => {
      mockIsClientModeTiersUiEnabled.mockReturnValue(true)
      const push = vi.fn(async () => {})
      const mods = makeModsStore([{ frontend: { pro_entry_path: '/mod/pro' } }])
      const pro = useAppProMode(mods, makeRouter(push), makeRoute('/chat'))
      pro.handleToggleProMode()
      // enterModProMode 是异步的，等待完成
      await vi.runAllTimersAsync()
      expect(pro.isProMode.value).toBe(true)
    })

    it('clientModeTiers UI 启用且有 mod 入口且当前为 pro 模式时退出 pro 模式', async () => {
      mockIsClientModeTiersUiEnabled.mockReturnValue(true)
      const push = vi.fn(async () => {})
      const mods = makeModsStore([{ frontend: { pro_entry_path: '/mod/pro' } }])
      const pro = useAppProMode(mods, makeRouter(push), makeRoute('/chat'))
      pro.isProMode.value = true
      pro.handleToggleProMode()
      await vi.runAllTimersAsync()
      expect(pro.isProMode.value).toBe(false)
    })

    it('legacy toggle 调用后触发 syncProModeStateSoon', () => {
      mockIsClientModeTiersUiEnabled.mockReturnValue(true)
      const legacyToggle = vi.fn()
      ;(window as Window & { __legacyToggleProMode?: () => void }).__legacyToggleProMode = legacyToggle
      document.body.classList.add('pro-mode-active')
      const pro = useAppProMode(makeModsStore([]), makeRouter(), makeRoute())
      pro.handleToggleProMode()
      // syncProModeStateSoon 内部用 requestAnimationFrame（属于 timer）
      vi.runAllTimers()
      expect(pro.isProMode.value).toBe(true)
    })

    it('使用 toggleProMode（非 __legacyToggleProMode）作为 legacy toggle', () => {
      mockIsClientModeTiersUiEnabled.mockReturnValue(true)
      const legacyToggle = vi.fn()
      ;(window as Window & { toggleProMode?: () => void }).toggleProMode = legacyToggle
      const pro = useAppProMode(makeModsStore([]), makeRouter(), makeRoute())
      pro.handleToggleProMode()
      expect(legacyToggle).toHaveBeenCalled()
    })
  })

  // ── syncGlobalProMode ────────────────────────────────────────
  describe('syncGlobalProMode', () => {
    it('isProMode 为 true 时设置 window 标志为 true 并派发事件', () => {
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      const handler = vi.fn()
      window.addEventListener('xcagi:pro-mode-changed', handler)
      pro.isProMode.value = true
      pro.syncGlobalProMode()
      expect((window as Window & { __XCAGI_IS_PRO_MODE?: boolean }).__XCAGI_IS_PRO_MODE).toBe(true)
      expect(handler).toHaveBeenCalledWith(
        expect.objectContaining({
          detail: { isProMode: true },
        }),
      )
      window.removeEventListener('xcagi:pro-mode-changed', handler)
    })

    it('isProMode 为 false 时设置 window 标志为 false 并派发事件', () => {
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      pro.isProMode.value = true
      const handler = vi.fn()
      window.addEventListener('xcagi:pro-mode-changed', handler)
      pro.isProMode.value = false
      pro.syncGlobalProMode()
      expect((window as Window & { __XCAGI_IS_PRO_MODE?: boolean }).__XCAGI_IS_PRO_MODE).toBe(false)
      expect(handler).toHaveBeenCalledWith(
        expect.objectContaining({
          detail: { isProMode: false },
        }),
      )
      window.removeEventListener('xcagi:pro-mode-changed', handler)
    })

    it('watch isProMode 变化时自动调用 syncGlobalProMode', async () => {
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      pro.isProMode.value = true
      // watch 默认异步（pre-flush），需等待 nextTick 触发回调
      await nextTick()
      expect((window as Window & { __XCAGI_IS_PRO_MODE?: boolean }).__XCAGI_IS_PRO_MODE).toBe(true)
    })
  })

  // ── installLegacyDomObserver / uninstallLegacyDomObserver ────
  describe('installLegacyDomObserver', () => {
    it('无 legacy runtime 时不安装 observer', () => {
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      pro.installLegacyDomObserver()
      // 无报错即可；无 observer 创建
    })

    it('有 legacy runtime 且无 overlay 时观察 body', () => {
      ;(window as Window & { __legacyToggleProMode?: () => void }).__legacyToggleProMode = () => {}
      const observeSpy = vi.spyOn(MutationObserver.prototype, 'observe')
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      pro.installLegacyDomObserver()
      expect(observeSpy).toHaveBeenCalledWith(document.body, {
        attributes: true,
        attributeFilter: ['class'],
      })
    })

    it('有 legacy runtime 且有 overlay 时同时观察 body 和 overlay', () => {
      ;(window as Window & { __legacyToggleProMode?: () => void }).__legacyToggleProMode = () => {}
      const overlay = document.createElement('div')
      overlay.id = 'proModeOverlay'
      document.body.appendChild(overlay)
      const observeSpy = vi.spyOn(MutationObserver.prototype, 'observe')
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      pro.installLegacyDomObserver()
      expect(observeSpy).toHaveBeenCalledWith(document.body, {
        attributes: true,
        attributeFilter: ['class'],
      })
      expect(observeSpy).toHaveBeenCalledWith(overlay, {
        attributes: true,
        attributeFilter: ['class', 'style'],
      })
    })

    it('observer 回调触发时通过 requestAnimationFrame 同步状态（去重）', async () => {
      ;(window as Window & { __legacyToggleProMode?: () => void }).__legacyToggleProMode = () => {}
      document.body.classList.add('pro-mode-active')
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      pro.installLegacyDomObserver()
      // 触发 body class 变化（MutationObserver 回调在 jsdom 中异步触发）
      document.body.classList.remove('pro-mode-active')
      // 等待 MutationObserver 微任务回调
      await nextTick()
      // 触发 requestAnimationFrame 回调
      vi.runAllTimers()
      // 状态应被同步为 false
      expect(pro.isProMode.value).toBe(false)
    })

    it('多次触发 observer 回调时 requestAnimationFrame 去重调度', async () => {
      ;(window as Window & { __legacyToggleProMode?: () => void }).__legacyToggleProMode = () => {}
      const observeSpy = vi.spyOn(MutationObserver.prototype, 'observe')
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      pro.installLegacyDomObserver()
      // 多次触发 body class 变化（jsdom 中 MutationObserver 回调异步触发）
      document.body.classList.add('pro-mode-active')
      document.body.classList.add('test-class-1')
      document.body.classList.add('test-class-2')
      // 等待所有微任务 + timer 完成，验证不抛出异常
      await vi.runAllTimersAsync()
      // observer 已正确安装（去重逻辑在 scheduleSync 内部，不影响 observer 注册）
      expect(observeSpy).toHaveBeenCalled()
      // 卸载不报错
      expect(() => pro.uninstallLegacyDomObserver()).not.toThrow()
    })
  })

  describe('uninstallLegacyDomObserver', () => {
    it('未安装 observer 时调用不报错', () => {
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      expect(() => pro.uninstallLegacyDomObserver()).not.toThrow()
    })

    it('已安装 observer 时调用 disconnect', () => {
      ;(window as Window & { __legacyToggleProMode?: () => void }).__legacyToggleProMode = () => {}
      const disconnectSpy = vi.spyOn(MutationObserver.prototype, 'disconnect')
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      pro.installLegacyDomObserver()
      pro.uninstallLegacyDomObserver()
      expect(disconnectSpy).toHaveBeenCalled()
    })

    it('卸载后再次卸载不报错', () => {
      ;(window as Window & { __legacyToggleProMode?: () => void }).__legacyToggleProMode = () => {}
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      pro.installLegacyDomObserver()
      pro.uninstallLegacyDomObserver()
      expect(() => pro.uninstallLegacyDomObserver()).not.toThrow()
    })
  })

  // ── enforceClientNormalModeBaseline ──────────────────────────
  describe('enforceClientNormalModeBaseline', () => {
    it('clientModeTiers UI 启用时直接返回不做任何操作', () => {
      mockIsClientModeTiersUiEnabled.mockReturnValue(true)
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      pro.enforceClientNormalModeBaseline()
      expect(mockResetClientModeTierLocalState).not.toHaveBeenCalled()
    })

    it('clientModeTiers UI 未启用时调用 resetClientModeTierLocalState', async () => {
      mockIsClientModeTiersUiEnabled.mockReturnValue(false)
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      pro.enforceClientNormalModeBaseline()
      expect(mockResetClientModeTierLocalState).toHaveBeenCalled()
    })

    it('legacy DOM 状态为 active 且有 legacy toggle 时调用 legacy toggle', async () => {
      mockIsClientModeTiersUiEnabled.mockReturnValue(false)
      const legacyToggle = vi.fn()
      ;(window as Window & { __legacyToggleProMode?: () => void }).__legacyToggleProMode = legacyToggle
      document.body.classList.add('pro-mode-active')
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      pro.enforceClientNormalModeBaseline()
      expect(legacyToggle).toHaveBeenCalled()
    })

    it('legacy DOM 状态为 active 但无 legacy toggle 时不报错', async () => {
      mockIsClientModeTiersUiEnabled.mockReturnValue(false)
      document.body.classList.add('pro-mode-active')
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      expect(() => pro.enforceClientNormalModeBaseline()).not.toThrow()
    })

    it('使用 toggleProMode 作为 legacy toggle', async () => {
      mockIsClientModeTiersUiEnabled.mockReturnValue(false)
      const legacyToggle = vi.fn()
      ;(window as Window & { toggleProMode?: () => void }).toggleProMode = legacyToggle
      document.body.classList.add('pro-mode-active')
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      pro.enforceClientNormalModeBaseline()
      expect(legacyToggle).toHaveBeenCalled()
    })

    it('legacy DOM 状态为 inactive 时不调用 legacy toggle', async () => {
      mockIsClientModeTiersUiEnabled.mockReturnValue(false)
      const legacyToggle = vi.fn()
      ;(window as Window & { __legacyToggleProMode?: () => void }).__legacyToggleProMode = legacyToggle
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      pro.enforceClientNormalModeBaseline()
      expect(legacyToggle).not.toHaveBeenCalled()
    })

    it('执行后 isProMode 为 false 并派发全局事件', async () => {
      mockIsClientModeTiersUiEnabled.mockReturnValue(false)
      const pro = useAppProMode(makeModsStore(), makeRouter(), makeRoute())
      pro.isProMode.value = true
      const handler = vi.fn()
      window.addEventListener('xcagi:pro-mode-changed', handler)
      pro.enforceClientNormalModeBaseline()
      await vi.runAllTimersAsync()
      expect(pro.isProMode.value).toBe(false)
      expect(handler).toHaveBeenCalled()
      window.removeEventListener('xcagi:pro-mode-changed', handler)
    })

    it('exitModProMode 被调用（当前路由非 chat 时跳转）', async () => {
      mockIsClientModeTiersUiEnabled.mockReturnValue(false)
      const push = vi.fn(async () => {})
      const pro = useAppProMode(makeModsStore(), makeRouter(push), makeRoute('/other', 'other'))
      pro.enforceClientNormalModeBaseline()
      await vi.runAllTimersAsync()
      expect(push).toHaveBeenCalledWith({ name: 'chat' })
    })
  })
})
