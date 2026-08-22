import { describe, it, expect, beforeEach, vi } from 'vitest'

// 隔离重依赖：window-manager 顶层 import 了 backend-process / desktop-config /
// rollback / updater / desktop-navigation，测试只关注 showMainWindow 与 toggleMainWindow 语义。
vi.mock('electron', () => ({
  BrowserWindow: vi.fn(),
  app: { getPath: vi.fn(() => '/tmp/xcagi-test'), isQuitting: false },
  dialog: {},
  screen: {},
  shell: {},
}))
vi.mock('./backend-process', () => ({
  checkForceUpgrade: vi.fn(),
  packagedBackendHealthTimeoutMs: vi.fn(),
  showDbRecoveryDialogIfNeeded: vi.fn(),
  waitForBackendApplicationReady: vi.fn(),
  waitForBackendPing: vi.fn(),
  waitForBackendStatus: vi.fn(),
  writeBackendLog: vi.fn(),
}))
vi.mock('./desktop-config', () => ({
  APP_NAME: 'XCAGI',
  DEFAULT_PORT: 17500,
  desktopInitialUrl: vi.fn(() => 'http://127.0.0.1:17500/'),
  markFrontendCacheCleared: vi.fn(),
  shellIconPath: vi.fn(() => '/tmp/icon.png'),
  shouldClearFrontendCache: vi.fn(() => false),
}))
vi.mock('./window-state', () => ({
  clampWindowBounds: vi.fn((b: unknown) => b),
  readWindowState: vi.fn(() => null),
  writeWindowState: vi.fn(),
}))
vi.mock('./rollback', () => ({ checkPendingRollback: vi.fn(() => null) }))
vi.mock('./updater', () => ({ configureUpdater: vi.fn() }))
vi.mock('./desktop-navigation', () => ({
  handleDesktopWindowOpen: vi.fn(),
  isBenignDesktopLoadAbort: vi.fn(),
  isTrustedDesktopOrigin: vi.fn(),
}))

import { showMainWindow, toggleMainWindow } from './window-manager'
import { desktopRuntime } from './runtime-state'

function makeWindow(overrides: Partial<{
  isVisible: boolean
  isMinimized: boolean
}> = {}) {
  const win = {
    isDestroyed: vi.fn(() => false),
    isVisible: vi.fn(() => overrides.isVisible ?? true),
    isMinimized: vi.fn(() => overrides.isMinimized ?? false),
    show: vi.fn(),
    hide: vi.fn(),
    focus: vi.fn(),
    restore: vi.fn(),
  }
  return win as unknown as NonNullable<typeof desktopRuntime.mainWindow>
}

describe('showMainWindow（语音唤起专用：只显示聚焦，绝不隐藏）', () => {
  beforeEach(() => {
    desktopRuntime.mainWindow = null
  })

  it('窗口可见时：仅 show + focus，不调用 hide（修复 toggle 语音唤起反向隐藏的 bug）', () => {
    const win = makeWindow({ isVisible: true, isMinimized: false })
    desktopRuntime.mainWindow = win

    showMainWindow()

    expect(win.show).toHaveBeenCalled()
    expect(win.focus).toHaveBeenCalled()
    expect(win.hide).not.toHaveBeenCalled()
  })

  it('窗口最小化时：restore + show + focus', () => {
    const win = makeWindow({ isVisible: true, isMinimized: true })
    desktopRuntime.mainWindow = win

    showMainWindow()

    expect(win.restore).toHaveBeenCalled()
    expect(win.show).toHaveBeenCalled()
    expect(win.focus).toHaveBeenCalled()
  })
})

describe('toggleMainWindow（托盘显隐切换语义保持不变）', () => {
  beforeEach(() => {
    desktopRuntime.mainWindow = null
  })

  it('窗口可见时：隐藏（区别于 showMainWindow）', () => {
    const win = makeWindow({ isVisible: true })
    desktopRuntime.mainWindow = win

    toggleMainWindow()

    expect(win.hide).toHaveBeenCalled()
    expect(win.show).not.toHaveBeenCalled()
  })

  it('窗口不可见时：show + focus（复用 showMainWindow）', () => {
    const win = makeWindow({ isVisible: false, isMinimized: true })
    desktopRuntime.mainWindow = win

    toggleMainWindow()

    expect(win.show).toHaveBeenCalled()
    expect(win.focus).toHaveBeenCalled()
    expect(win.hide).not.toHaveBeenCalled()
  })
})