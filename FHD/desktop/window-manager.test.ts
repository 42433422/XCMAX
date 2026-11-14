import { describe, it, expect, beforeEach, vi } from 'vitest'

const sessionMocks = vi.hoisted(() => {
  const partitions = new Map<string, {
    cookies: { get: ReturnType<typeof vi.fn>; set: ReturnType<typeof vi.fn> }
    on: ReturnType<typeof vi.fn>
    clearStorageData: ReturnType<typeof vi.fn>
    clearCache: ReturnType<typeof vi.fn>
  }>()
  return {
    partitions,
    defaultGet: vi.fn(async () => [] as Array<Record<string, unknown>>),
    fromPartition: vi.fn((name: string) => {
      let store = partitions.get(name)
      if (!store) {
        store = {
          cookies: { get: vi.fn(async () => []), set: vi.fn(async () => undefined) },
          on: vi.fn(),
          clearStorageData: vi.fn(async () => undefined),
          clearCache: vi.fn(async () => undefined),
        }
        partitions.set(name, store)
      }
      return store
    }),
  }
})

import { app, BrowserWindow } from 'electron'
import fs from 'node:fs'
import { waitForBackendPing, waitForBackendApplicationReady, waitForBackendStatus } from './backend-process'
vi.mock('electron', () => ({
  BrowserWindow: vi.fn(),
  app: { getPath: vi.fn(() => '/tmp/xcagi-test'), isQuitting: false, focus: vi.fn() },
  dialog: { showErrorBox: vi.fn() },
  screen: { getPrimaryDisplay: vi.fn(() => ({ workArea: { x: 0, y: 0, width: 1280, height: 800 } })), getDisplayMatching: vi.fn(() => ({ workArea: { x: 0, y: 0, width: 1280, height: 800 } })) },
  shell: {},
  session: {
    defaultSession: { cookies: { get: sessionMocks.defaultGet } },
    fromPartition: sessionMocks.fromPartition,
  },
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
  DESKTOP_MIN_WIDTH: 800,
  DESKTOP_MIN_HEIGHT: 640,
  clampWindowBounds: vi.fn((b: unknown) => b),
  readWindowState: vi.fn(() => null),
  writeWindowState: vi.fn(),
}))
vi.mock('./rollback', () => ({ checkPendingRollback: vi.fn(() => null) }))
vi.mock('./updater', () => ({ configureUpdater: vi.fn() }))
vi.mock('./desktop-navigation', () => ({
  handleDesktopWindowOpen: vi.fn(),
  handleDesktopWillNavigate: vi.fn(),
  isBenignDesktopLoadAbort: vi.fn(),
  isTrustedDesktopOrigin: vi.fn(),
}))

import { clampWindowBounds } from './window-state'
import { isTrustedDesktopOrigin } from './desktop-navigation'
import { createWindow, desktopWindowCount, MAX_DESKTOP_WINDOWS, openAuxiliaryWindow, resetAuxiliaryPartitionSerialForTests, showMainWindow, toggleMainWindow } from './window-manager'
import { desktopRuntime } from './runtime-state'
import { checkPendingRollback } from './rollback'
import { reportRendererError } from './desktop-resilience'
import { writeBackendLog } from './backend-process'
vi.mock('./desktop-resilience', () => ({ reportRendererError: vi.fn() }))
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
    setAlwaysOnTop: vi.fn(),
    moveTop: vi.fn(),
    getBounds: vi.fn(() => ({ x: 0, y: 0, width: 1280, height: 800 })),
    setBounds: vi.fn(),
  }
  return win as unknown as NonNullable<typeof desktopRuntime.mainWindow>
}
beforeEach(() => {
  desktopRuntime.splashUrl = ''
  desktopRuntime.mainWindow = null
  desktopRuntime.mainApplicationReady = null
  desktopRuntime.auxiliaryWindows.clear()
  vi.mocked(BrowserWindow).mockReset()
  vi.mocked(isTrustedDesktopOrigin).mockReset()
})

describe('showMainWindow（语音唤起专用：只显示聚焦，绝不隐藏）', () => {
  it('窗口可见时：仅 show + focus，不调用 hide（修复 toggle 语音唤起反向隐藏的 bug）', () => {
    const win = makeWindow({ isVisible: true, isMinimized: false })
    desktopRuntime.mainWindow = win
    showMainWindow()
    expect(win.show).toHaveBeenCalled()
    expect(win.focus).toHaveBeenCalled()
    expect(win.hide).not.toHaveBeenCalled()
    expect(win.setBounds).not.toHaveBeenCalled()
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

  it('最小化但仍 isVisible 时：恢复而不是再隐藏', () => {
    const win = makeWindow({ isVisible: true, isMinimized: true })
    desktopRuntime.mainWindow = win
    toggleMainWindow()
    expect(win.hide).not.toHaveBeenCalled()
    expect(win.restore).toHaveBeenCalled()
    expect(win.show).toHaveBeenCalled()
  })
})

it('拉回几乎不在工作区里的窗口，避免托盘单击后仍看不见', () => {
  const win = makeWindow({ isVisible: false })
  win.getBounds = vi.fn(() => ({ x: -4000, y: 80, width: 1280, height: 800 }))
  desktopRuntime.mainWindow = win
  vi.mocked(clampWindowBounds).mockClear()
  showMainWindow()
  expect(clampWindowBounds).toHaveBeenCalled()
  expect(win.setBounds).toHaveBeenCalled()
  expect(win.show).toHaveBeenCalled()
  expect(win.focus).toHaveBeenCalled()
})

it('Windows 托盘唤起会把窗口临时置顶，否则 show 后仍留在别的窗口后面', () => {
  const original = process.platform
  Object.defineProperty(process, 'platform', { value: 'win32', configurable: true })
  try {
    const win = makeWindow({ isVisible: false })
    desktopRuntime.mainWindow = win
    showMainWindow()
    expect(win.setAlwaysOnTop).toHaveBeenNthCalledWith(1, true)
    expect(win.moveTop).toHaveBeenCalled()
    expect(win.setAlwaysOnTop).toHaveBeenNthCalledWith(2, false)
    expect(win.show).toHaveBeenCalled()
  } finally {
    Object.defineProperty(process, 'platform', { value: original, configurable: true })
  }
})

it('macOS 托盘唤起会抢前台，隐藏窗口才能露出来', () => {
  const original = process.platform
  Object.defineProperty(process, 'platform', { value: 'darwin', configurable: true })
  try {
    const win = makeWindow({ isVisible: false })
    desktopRuntime.mainWindow = win
    showMainWindow()
    expect(app.focus).toHaveBeenCalledWith({ steal: true })
    expect(win.show).toHaveBeenCalled()
    expect(win.focus).toHaveBeenCalled()
  } finally {
    Object.defineProperty(process, 'platform', { value: original, configurable: true })
  }
})

it('keeps the activated startup window and its in-flight readiness task', async () => {
  const win = makeWindow()
  const ready = new Promise<void>(() => {})
  desktopRuntime.mainWindow = win
  desktopRuntime.mainApplicationReady = ready
  vi.mocked(BrowserWindow).mockImplementationOnce(() => { throw new Error('duplicate startup window') })
  await expect(createWindow()).resolves.toBeUndefined()
  expect(desktopRuntime.mainWindow).toBe(win)
  expect(desktopRuntime.mainApplicationReady).toBe(ready)
  expect(BrowserWindow).not.toHaveBeenCalled()
})

it.each([false, true])('ignores a clean renderer exit when quitting is %s', async (quitting) => {
  vi.mocked(waitForBackendPing).mockResolvedValue(undefined)
  vi.mocked(waitForBackendApplicationReady).mockResolvedValue(undefined)
  vi.mocked(waitForBackendStatus).mockResolvedValue(null)
  let onGone: ((event: unknown, details: { reason: string; exitCode: number }) => void) | undefined
  const win = Object.assign(makeWindow(), {
    on: vi.fn(), once: vi.fn(), reload: vi.fn(),
    setAutoHideMenuBar: vi.fn(), setMenuBarVisibility: vi.fn(), loadURL: vi.fn(async () => undefined),
    webContents: {
      on: vi.fn((event: string, listener: typeof onGone) => { if (event === 'render-process-gone') onGone = listener }),
      getURL: vi.fn(() => 'http://127.0.0.1:17500/'), setWindowOpenHandler: vi.fn(),
      session: { on: vi.fn() }, executeJavaScript: vi.fn(async () => undefined),
    },
  })
  vi.mocked(BrowserWindow).mockImplementationOnce(function () { return win as unknown as BrowserWindow })
  await createWindow()
  await desktopRuntime.mainApplicationReady
  vi.mocked(checkPendingRollback).mockClear()
  vi.mocked(reportRendererError).mockClear()
  vi.mocked(writeBackendLog).mockClear()
  app.isQuitting = quitting
  try {
    expect(onGone).toBeTypeOf('function')
    onGone?.({}, { reason: 'clean-exit', exitCode: 0 })
    expect(checkPendingRollback).not.toHaveBeenCalled()
    expect(reportRendererError).not.toHaveBeenCalled()
    expect(writeBackendLog).not.toHaveBeenCalled()
    expect(desktopRuntime.rendererFailedDuringStartup).toBe(false)
    expect(win.reload).not.toHaveBeenCalled()
  } finally {
    app.isQuitting = false
  }
})

it('still records a real renderer crash during rollback observation', async () => {
  vi.mocked(waitForBackendPing).mockResolvedValue(undefined)
  vi.mocked(waitForBackendApplicationReady).mockResolvedValue(undefined)
  vi.mocked(waitForBackendStatus).mockResolvedValue(null)
  let onGone: ((event: unknown, details: { reason: string; exitCode: number }) => void) | undefined
  const win = Object.assign(makeWindow(), {
    on: vi.fn(), once: vi.fn(), reload: vi.fn(),
    setAutoHideMenuBar: vi.fn(), setMenuBarVisibility: vi.fn(), loadURL: vi.fn(async () => undefined),
    webContents: {
      on: vi.fn((event: string, listener: typeof onGone) => { if (event === 'render-process-gone') onGone = listener }),
      getURL: vi.fn(() => 'http://127.0.0.1:17500/'), setWindowOpenHandler: vi.fn(),
      session: { on: vi.fn() }, executeJavaScript: vi.fn(async () => undefined),
    },
  })
  vi.mocked(BrowserWindow).mockImplementationOnce(function () { return win as unknown as BrowserWindow })
  await createWindow()
  await desktopRuntime.mainApplicationReady
  vi.mocked(checkPendingRollback).mockClear()
  vi.mocked(reportRendererError).mockClear()
  vi.mocked(writeBackendLog).mockClear()
  vi.mocked(checkPendingRollback).mockReturnValueOnce({} as never)
  app.isQuitting = false
  try {
    expect(onGone).toBeTypeOf('function')
    onGone?.({}, { reason: 'crashed', exitCode: 1 })
    expect(reportRendererError).toHaveBeenCalled()
    expect(writeBackendLog).toHaveBeenCalledWith(expect.stringContaining('reason=crashed'))
    expect(desktopRuntime.rendererFailedDuringStartup).toBe(true)
    expect(win.reload).not.toHaveBeenCalled()
  } finally {
    desktopRuntime.rendererFailedDuringStartup = false
  }
})

it.each([
  ['crashed', 1],
  ['oom', 137],
  ['abnormal-exit', 1],
  ['integrity-failure', 3],
  ['killed', 1],
  // Windows 也会用 clean-exit 配非零退出码：仍属于异常退出。
  ['clean-exit', 1],
])('records abnormal renderer exit (%s, exitCode=%i) and reloads in place', async (reason, exitCode) => {
  vi.mocked(waitForBackendPing).mockResolvedValue(undefined)
  vi.mocked(waitForBackendApplicationReady).mockResolvedValue(undefined)
  vi.mocked(waitForBackendStatus).mockResolvedValue(null)
  let onGone: ((event: unknown, details: { reason: string; exitCode: number }) => void) | undefined
  const win = Object.assign(makeWindow(), {
    on: vi.fn(), once: vi.fn(), reload: vi.fn(),
    setAutoHideMenuBar: vi.fn(), setMenuBarVisibility: vi.fn(), loadURL: vi.fn(async () => undefined),
    webContents: {
      on: vi.fn((event: string, listener: typeof onGone) => { if (event === 'render-process-gone') onGone = listener }),
      getURL: vi.fn(() => 'http://127.0.0.1:17500/'), setWindowOpenHandler: vi.fn(),
      session: { on: vi.fn() }, executeJavaScript: vi.fn(async () => undefined),
    },
  })
  vi.mocked(BrowserWindow).mockImplementationOnce(function () { return win as unknown as BrowserWindow })
  await createWindow()
  await desktopRuntime.mainApplicationReady
  vi.mocked(reportRendererError).mockClear()
  vi.mocked(writeBackendLog).mockClear()
  const now = vi.spyOn(Date, 'now').mockReturnValue(Date.now() + 60_000)
  app.isQuitting = false
  try {
    expect(onGone).toBeTypeOf('function')
    onGone?.({}, { reason, exitCode })
    expect(writeBackendLog).toHaveBeenCalledWith(expect.stringContaining(`reason=${reason}`))
    expect(reportRendererError).toHaveBeenCalled()
    expect(win.reload).toHaveBeenCalledOnce()
    expect(desktopRuntime.rendererFailedDuringStartup).toBe(false)
  } finally {
    now.mockRestore()
    app.isQuitting = false
  }
})

it.each([true, false])('records selected splash before loading (file exists: %s)', async (exists) => {
  vi.spyOn(fs, 'existsSync').mockReturnValue(exists)
  vi.mocked(waitForBackendPing).mockResolvedValue(undefined)
  vi.mocked(waitForBackendApplicationReady).mockResolvedValue(undefined)
  vi.mocked(waitForBackendStatus).mockResolvedValue(null)
  const loaded: Array<[string, string]> = []
  const win = Object.assign(makeWindow(), {
    on: vi.fn(),
    once: vi.fn(),
    setAutoHideMenuBar: vi.fn(), setMenuBarVisibility: vi.fn(),
    loadURL: vi.fn(async (url: string) => { loaded.push([url, desktopRuntime.splashUrl]) }),
    webContents: {
      on: vi.fn(), getURL: vi.fn(() => 'http://127.0.0.1:17500/'), setWindowOpenHandler: vi.fn(),
      session: { on: vi.fn() },
      executeJavaScript: vi.fn(async () => undefined),
    },
  })
  vi.mocked(BrowserWindow).mockImplementationOnce(function () { return win as unknown as BrowserWindow })
  await createWindow()
  await desktopRuntime.mainApplicationReady
  expect(loaded[0][0]).toBe(loaded[0][1])
  expect(loaded[0][0].startsWith(exists ? 'file:' : 'data:')).toBe(true)
})

it.each(['paint', 'aborted', 'failed'])('keeps splash paint readiness across %s startup', async (outcome) => {
  vi.spyOn(fs, 'existsSync').mockReturnValue(true)
  vi.mocked(waitForBackendPing).mockResolvedValue(undefined)
  vi.mocked(waitForBackendApplicationReady).mockResolvedValue(undefined)
  vi.mocked(waitForBackendStatus).mockResolvedValue(null)
  let onReadyToShow: (() => void) | undefined
  const win = Object.assign(makeWindow(), {
    on: vi.fn(),
    once: vi.fn((event: string, listener: () => void) => {
      if (event === 'ready-to-show') onReadyToShow = listener
    }),
    setAutoHideMenuBar: vi.fn(), setMenuBarVisibility: vi.fn(),
    loadURL: vi.fn(async () => undefined),
    webContents: {
      on: vi.fn(), getURL: vi.fn(() => 'file:///trusted/splash.html'), setWindowOpenHandler: vi.fn(),
      session: { on: vi.fn() },
      executeJavaScript: vi.fn(async () => undefined),
    },
  })
  if (outcome !== 'paint') {
    win.loadURL.mockRejectedValueOnce(new Error(outcome === 'aborted' ? 'ERR_ABORTED (-3)' : 'ERR_FAILED'))
  }
  vi.mocked(BrowserWindow).mockImplementationOnce(function () { return win as unknown as BrowserWindow })

  await createWindow()
  await desktopRuntime.mainApplicationReady

  expect(BrowserWindow).toHaveBeenCalledWith(expect.objectContaining({ show: false }))
  expect(win.once).toHaveBeenCalledWith('ready-to-show', expect.any(Function))
  expect(win.show).toHaveBeenCalledTimes(outcome === 'failed' ? 1 : 0)
  const focusBeforePaint = vi.mocked(win.focus).mock.calls.length
  if (outcome !== 'failed') expect(focusBeforePaint).toBe(0)
  expect(onReadyToShow).toBeTypeOf('function')
  onReadyToShow?.()
  expect(win.show).toHaveBeenCalledTimes(1)
  expect(win.focus).toHaveBeenCalledTimes(focusBeforePaint + (outcome === 'failed' ? 0 : 1))
  onReadyToShow?.()
  expect(win.show).toHaveBeenCalledTimes(1)
})

describe('同一进程附加窗口', () => {
  beforeEach(() => {
    resetAuxiliaryPartitionSerialForTests()
    sessionMocks.partitions.clear()
    sessionMocks.defaultGet.mockReset()
    sessionMocks.defaultGet.mockResolvedValue([])
    sessionMocks.fromPartition.mockClear()
  })

  function fakeAux() {
    const listeners: Record<string, Array<() => void>> = {}
    const win = {
      isDestroyed: vi.fn(() => false),
      on: vi.fn((event: string, cb: () => void) => {
        ;(listeners[event] ||= []).push(cb)
      }),
      destroy: vi.fn(() => {
        win.isDestroyed.mockReturnValue(true)
        for (const cb of listeners.closed || []) cb()
      }),
      getBounds: vi.fn(() => ({ x: 10, y: 10, width: 1200, height: 800 })),
      loadURL: vi.fn(async () => undefined),
      webContents: {
        on: vi.fn(),
        setWindowOpenHandler: vi.fn(),
        session: { on: vi.fn() },
        downloadURL: vi.fn(),
      },
    }
    return win
  }

  it('打开到上限后拒绝，关闭后不再占用进程内窗口名额', () => {
    vi.mocked(isTrustedDesktopOrigin).mockReturnValue(true)
    desktopRuntime.mainWindow = makeWindow()
    const created: ReturnType<typeof fakeAux>[] = []
    vi.mocked(BrowserWindow).mockImplementation(function () {
      const win = fakeAux()
      created.push(win)
      return win as unknown as BrowserWindow
    })
    const url = 'http://127.0.0.1:17500/'
    for (let i = 0; i < MAX_DESKTOP_WINDOWS - 1; i += 1) {
      expect(openAuxiliaryWindow(url)).not.toBeNull()
    }
    expect(desktopWindowCount()).toBe(MAX_DESKTOP_WINDOWS)
    expect(openAuxiliaryWindow(url)).toBeNull()
    created[0].destroy()
    expect(desktopWindowCount()).toBe(MAX_DESKTOP_WINDOWS - 1)
    expect(openAuxiliaryWindow(url)).not.toBeNull()
  })

  it('拒绝不可信地址，且不创建窗口', () => {
    vi.mocked(isTrustedDesktopOrigin).mockReturnValue(false)
    expect(openAuxiliaryWindow('https://evil.example/')).toBeNull()
    expect(BrowserWindow).not.toHaveBeenCalled()
    expect(desktopWindowCount()).toBe(0)
  })

  it('每个附加窗口使用独立存储分区，并只复制登录 cookie', async () => {
    vi.mocked(isTrustedDesktopOrigin).mockReturnValue(true)
    desktopRuntime.mainWindow = makeWindow()
    sessionMocks.defaultGet.mockResolvedValue([
      { name: 'session_id', value: 'live-session', path: '/', httpOnly: true, secure: false, sameSite: 'lax' },
      { name: 'csrf_token', value: 'csrf-live', path: '/', httpOnly: false, secure: false, sameSite: 'lax' },
    ])
    const created: ReturnType<typeof fakeAux>[] = []
    vi.mocked(BrowserWindow).mockImplementation(function () {
      const win = fakeAux()
      created.push(win)
      return win as unknown as BrowserWindow
    })
    const first = openAuxiliaryWindow('http://127.0.0.1:17500/chat')
    const second = openAuxiliaryWindow('http://127.0.0.1:17500/chat')
    expect(first).not.toBeNull()
    expect(second).not.toBeNull()
    const partitions = vi.mocked(BrowserWindow).mock.calls.map(call => {
      const options = call[0] as { webPreferences?: { partition?: string } }
      return options.webPreferences?.partition
    })
    expect(partitions).toEqual(['xcagi-aux-1', 'xcagi-aux-2'])
    const firstStore = sessionMocks.partitions.get('xcagi-aux-1')
    const secondStore = sessionMocks.partitions.get('xcagi-aux-2')
    expect(firstStore).toBeDefined()
    expect(secondStore).toBeDefined()
    expect(firstStore).not.toBe(secondStore)
    await vi.waitFor(() => expect(firstStore!.cookies.set).toHaveBeenCalled())
    expect(firstStore!.cookies.set).toHaveBeenCalledWith(expect.objectContaining({ name: 'session_id', value: 'live-session' }))
    expect(secondStore!.cookies.set).toHaveBeenCalledWith(expect.objectContaining({ name: 'csrf_token', value: 'csrf-live' }))
    expect(sessionMocks.defaultGet.mock.calls.length).toBeGreaterThan(0)
    created[0].destroy()
    expect(sessionMocks.partitions.get('xcagi-aux-1')!.clearStorageData).toHaveBeenCalled()
    expect(first).not.toBeNull()
  })
})
