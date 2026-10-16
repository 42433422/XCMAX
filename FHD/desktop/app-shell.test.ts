import { afterEach, describe, it, expect, vi } from 'vitest'
import fs from 'node:fs'

vi.mock('electron', () => ({
  BrowserWindow: { getFocusedWindow: vi.fn(() => null) },
  ClipboardItem: class { types: string[]; constructor(data: Record<string, unknown>) { this.types = Object.keys(data) } },
  Menu: { buildFromTemplate: vi.fn(() => ({})), setApplicationMenu: vi.fn() },
  Tray: vi.fn(),
  app: { getPath: vi.fn(() => '/tmp/xcagi-test'), getName: vi.fn(() => 'XCAGI'), isQuitting: false },
  clipboard: { write: vi.fn() },
  desktopCapturer: { getSources: vi.fn(async () => [{ display_id: '1', thumbnail: { isEmpty: () => false, toPNG: () => Buffer.from('png') } }]) },
  dialog: {}, nativeImage: {},
  screen: { getPrimaryDisplay: () => ({ id: 1, size: { width: 10, height: 10 } }) },
  session: { defaultSession: { cookies: { get: vi.fn(() => Promise.resolve([])) } } },
  shell: { openPath: vi.fn(), openExternal: vi.fn(() => Promise.resolve()) },
}))
vi.mock('node:child_process', () => ({ execFile: vi.fn() }))
vi.mock('./desktop-config', () => ({ APP_NAME: 'XCAGI', DEFAULT_PORT: 17500, shellIconPath: vi.fn(() => '/tmp/icon.png') }))
vi.mock('./window-manager', () => ({ broadcastToRenderer: vi.fn(), toggleMainWindow: vi.fn() }))
vi.mock('./backend-process', () => ({ writeBackendLog: vi.fn() }))
vi.mock('./updater', () => ({ readLocalProductVersion: vi.fn(() => '1.0.0.1'), runUpdateCheckWithDirectNet: vi.fn() }))
vi.mock('./desktop-navigation', () => ({ parseDesktopDeepLink: vi.fn(() => null) }))

import { execFile } from 'node:child_process'
import { clipboard } from 'electron'
import { openKellaiDesktop, captureFullScreenScreenshot } from './app-shell'

afterEach(() => { vi.restoreAllMocks(); vi.clearAllMocks() })

describe('openKellaiDesktop（客来来第三方联动）', () => {
  it.each([false, true])('macOS application missing: %s', async missing => {
    const originalPlatform = process.platform
    Object.defineProperty(process, 'platform', { value: 'darwin', configurable: true })
    try {
      vi.mocked(execFile).mockImplementationOnce(((_cmd: string, _args: string[], cb: (err: Error | null) => void) => cb(missing ? new Error('application not found') : null)) as typeof execFile)
      expect(await openKellaiDesktop()).toEqual(missing
        ? { ok: false, reason: '未检测到客来来桌面端，请先安装并打开一次客来来。' } : { ok: true })
    } finally {
      Object.defineProperty(process, 'platform', { value: originalPlatform, configurable: true })
    }
  })
})

it.each([false, true])('screenshot waits for clipboard completion (reject: %s)', async reject => {
  let complete!: () => void
  vi.mocked(clipboard.write).mockReturnValueOnce(new Promise<void>((resolve, fail) => { complete = reject ? () => fail(new Error('clipboard denied')) : resolve }))
  const write = vi.spyOn(fs, 'writeFileSync').mockImplementation(() => {})
  vi.spyOn(fs, 'mkdirSync').mockReturnValue(undefined)
  const capturing = captureFullScreenScreenshot()
  await vi.waitFor(() => expect(clipboard.write).toHaveBeenCalled())
  expect(write).not.toHaveBeenCalled()
  complete()
  const result = await capturing
  expect(result.ok).toBe(!reject)
  if (reject) expect(result.error).toBe('clipboard denied')
  else expect(write).toHaveBeenCalledWith(expect.stringContaining('screenshot-'), Buffer.from('png'))
})
