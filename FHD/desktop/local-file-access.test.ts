import { beforeEach, expect, it, vi } from 'vitest'
import type { IpcMainInvokeEvent } from 'electron'
import fs from 'node:fs'

const mocks = vi.hoisted(() => ({
  handlers: new Map<string, (...args: any[]) => any>(),
  openDialog: vi.fn(),
  openExternal: vi.fn(() => Promise.resolve()),
  home: '/synthetic/home',
}))
vi.mock('electron', () => ({
  ipcMain: {
    handle: (name: string, handler: (...args: any[]) => any) => mocks.handlers.set(name, handler),
  },
  app: { getPath: (name: string) => (name === 'home' ? mocks.home : '/synthetic/userdata') },
  clipboard: {},
  shell: { openExternal: mocks.openExternal },
  dialog: { showOpenDialog: mocks.openDialog },
  Notification: Object.assign(vi.fn(), { isSupported: () => true }),
}))
vi.mock('./desktop-config', () => ({ APP_NAME: 'test', DEFAULT_PORT: 18500, readPackagedAppVersion: vi.fn() }))
vi.mock('./window-manager', () => ({ broadcastToRenderer: vi.fn() }))
vi.mock('./backend-process', () => ({ writeBackendLog: vi.fn(), stopBackend: vi.fn(), runBackendMigrationWithRollback: vi.fn() }))
vi.mock('./app-shell', () => ({}))
vi.mock('./updater', () => ({}))
vi.mock('./rollback', () => ({}))
vi.mock('./desktop-install-update', () => ({}))
vi.mock('./data-bridge', () => ({ desktopOfflineDbPath: () => '/synthetic/db' }))
vi.mock('./data-bridge-session', () => ({ queryOfflineForSession: vi.fn() }))
vi.mock('./secure-store', () => ({ getSecret: vi.fn(), setSecret: vi.fn(), deleteSecret: vi.fn(), listSecrets: vi.fn() }))
vi.mock('./desktop-resilience', () => ({ reportRendererError: vi.fn() }))

import { registerDesktopIpcHandlers } from './ipc-handlers'
import { desktopRuntime } from './runtime-state'

function trustedSender(): IpcMainInvokeEvent {
  const frame = { url: 'http://127.0.0.1:18500/' }
  desktopRuntime.mainWindow = {
    isDestroyed: () => false,
    webContents: { id: 17, mainFrame: frame },
  } as unknown as NonNullable<typeof desktopRuntime.mainWindow>
  return { sender: { id: 17, session: {} }, senderFrame: frame } as unknown as IpcMainInvokeEvent
}

beforeEach(() => {
  mocks.handlers.clear()
  mocks.openDialog.mockReset()
  mocks.openExternal.mockReset()
  desktopRuntime.auxiliaryWindows.clear()
  desktopRuntime.splashUrl = 'file:///trusted/splash.html'
  registerDesktopIpcHandlers()
})

it('choose-directory forwards the picked folder and tolerates cancel', async () => {
  mocks.openDialog.mockResolvedValueOnce({ canceled: false, filePaths: ['/Users/me/Docs'] })
  expect(await mocks.handlers.get('xcagi:choose-directory')!(trustedSender())).toEqual({
    canceled: false,
    paths: ['/Users/me/Docs'],
  })
  mocks.openDialog.mockResolvedValueOnce({ canceled: true, filePaths: [] })
  expect(await mocks.handlers.get('xcagi:choose-directory')!(trustedSender())).toEqual({
    canceled: true,
    paths: [],
  })
})

it('choose-files allows multi-selection', async () => {
  mocks.openDialog.mockResolvedValueOnce({ canceled: false, filePaths: ['/a.pdf', '/b.xlsx'] })
  const result = await mocks.handlers.get('xcagi:choose-files')!(trustedSender())
  expect(result.paths).toEqual(['/a.pdf', '/b.xlsx'])
  expect(mocks.openDialog.mock.calls.at(-1)?.[1]?.properties).toContain('multiSelections')
})

it('full-disk probe reports denied when the protected path cannot be read', async () => {
  const spy = vi.spyOn(fs, 'openSync').mockImplementation(() => {
    const error = new Error('denied') as NodeJS.ErrnoException
    error.code = 'EACCES'
    throw error
  })
  const result = await mocks.handlers.get('xcagi:full-disk-access-status')!(trustedSender())
  expect(result.status === 'denied' || result.status === 'not_required').toBe(true)
  spy.mockRestore()
})

it('opens the macOS privacy settings deep link', async () => {
  const result = await mocks.handlers.get('xcagi:open-privacy-settings')!(trustedSender())
  if (process.platform === 'darwin') {
    expect(mocks.openExternal).toHaveBeenCalledWith(
      'x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles',
    )
    expect(result).toEqual({ ok: true })
  } else {
    expect(result).toEqual({ ok: false, reason: 'not_macos' })
  }
})
