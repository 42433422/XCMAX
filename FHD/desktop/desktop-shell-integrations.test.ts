import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterAll, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  handlers: new Map<string, (...args: unknown[]) => unknown>(),
  listeners: new Map<string, (...args: unknown[]) => unknown>(),
  getLoginItemSettings: vi.fn(() => ({ openAtLogin: false })),
  setLoginItemSettings: vi.fn(),
  setAsDefaultProtocolClient: vi.fn(),
  clipboardWriteImage: vi.fn(),
  dialogShowMessageBox: vi.fn(),
  globalShortcutRegister: vi.fn(),
  ipcHandle: vi.fn((channel: string, handler: (...args: unknown[]) => unknown) => {
    mocks.handlers.set(channel, handler)
  }),
  reportRendererError: vi.fn(),
}))

const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-shell-integrations-'))
const image = {
  isEmpty: () => false,
  toPNG: () => Buffer.from('png'),
}

vi.mock('electron', () => ({
  app: {
    getPath: () => userDataDir,
    getLoginItemSettings: mocks.getLoginItemSettings,
    setLoginItemSettings: mocks.setLoginItemSettings,
    setAsDefaultProtocolClient: mocks.setAsDefaultProtocolClient,
    on: vi.fn((event: string, handler: (...args: unknown[]) => unknown) => {
      mocks.listeners.set(event, handler)
    }),
  },
  clipboard: { writeImage: mocks.clipboardWriteImage },
  desktopCapturer: {
    getSources: vi.fn(async () => [{ display_id: '1', thumbnail: image }]),
  },
  dialog: { showMessageBox: mocks.dialogShowMessageBox },
  globalShortcut: { register: mocks.globalShortcutRegister },
  ipcMain: { handle: mocks.ipcHandle },
  screen: { getPrimaryDisplay: () => ({ id: 1, size: { width: 1280, height: 720 } }) },
}))

vi.mock('./desktop-resilience', () => ({ reportRendererError: mocks.reportRendererError }))
vi.mock('./updater', () => ({ readLocalProductVersion: () => '1.0.0.1' }))

import { captureFullScreenScreenshot, consumeReleaseNotes, createDesktopShellIntegrations } from './desktop-shell-integrations'

afterAll(() => fs.rmSync(userDataDir, { recursive: true, force: true }))

beforeEach(() => {
  mocks.handlers.clear()
  mocks.listeners.clear()
  vi.clearAllMocks()
  fs.rmSync(path.join(userDataDir, 'desktop-settings.json'), { force: true })
  fs.rmSync(path.join(userDataDir, 'release-note-state.json'), { force: true })
})

function setup() {
  const webContents = { isLoading: () => false, send: vi.fn() }
  const window = {
    isDestroyed: () => false,
    isMinimized: () => true,
    show: vi.fn(),
    restore: vi.fn(),
    focus: vi.fn(),
    webContents,
  }
  const integration = createDesktopShellIntegrations({
    appName: 'XCAGI',
    backendPort: 17500,
    getMainWindow: () => window as never,
    toggleMainWindow: vi.fn(),
    writeLog: vi.fn(),
  })
  return { integration, window, webContents }
}

describe('desktop shell integrations', () => {
  it('handles open-url and second-instance deep links through one pending channel', () => {
    const { integration, window, webContents } = setup()
    integration.registerProtocolHandlers()
    mocks.listeners.get('open-url')?.({ preventDefault: vi.fn() }, 'xcagi://chat?q=first')
    integration.handleSecondInstance(['XCAGI', 'xcagi://chat?q=second'])

    expect(window.show).toHaveBeenCalled()
    expect(window.restore).toHaveBeenCalled()
    expect(webContents.send).toHaveBeenCalledWith('xcagi:deep-link', 'xcagi://chat?q=second')
  })

  it('registers IPC, auto-launch, shortcuts, and consumes pending deep links once', () => {
    const { integration } = setup()
    integration.handleSecondInstance(['XCAGI', 'xcagi://chat?q=pending'])
    integration.initialize()

    expect(mocks.setAsDefaultProtocolClient).toHaveBeenCalledWith('xcagi')
    expect(mocks.setLoginItemSettings).toHaveBeenCalledWith({ openAtLogin: true })
    expect(mocks.handlers.has('xcagi:report-error')).toBe(true)
    expect(mocks.globalShortcutRegister).toHaveBeenCalledTimes(3)
    const consume = mocks.handlers.get('xcagi:consume-deep-link')!
    expect(consume()).toBe('xcagi://chat?q=pending')
    expect(consume()).toBeNull()
  })

  it('captures the primary display and persists release notes once per version', async () => {
    const result = await captureFullScreenScreenshot()
    expect(result.ok).toBe(true)
    expect(result.path && fs.existsSync(result.path)).toBe(true)
    expect(mocks.clipboardWriteImage).toHaveBeenCalledWith(image)

    expect(consumeReleaseNotes()).toMatchObject({ isFirstRun: true, toVersion: '1.0.0.1' })
    expect(consumeReleaseNotes()).toBeNull()
  })
})
