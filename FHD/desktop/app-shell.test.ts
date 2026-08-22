import { describe, it, expect, vi } from 'vitest'

// 隔离 app-shell 的重依赖，仅验证 openKellaiDesktop 的跨平台语义。
vi.mock('electron', () => ({
  BrowserWindow: { getFocusedWindow: vi.fn(() => null) },
  Menu: { buildFromTemplate: vi.fn(() => ({})), setApplicationMenu: vi.fn() },
  Tray: vi.fn(),
  app: { getPath: vi.fn(() => '/tmp/xcagi-test'), getName: vi.fn(() => 'XCAGI'), isQuitting: false },
  clipboard: {},
  desktopCapturer: {},
  dialog: {},
  nativeImage: {},
  screen: {},
  session: { defaultSession: { cookies: { get: vi.fn(() => Promise.resolve([])) } } },
  shell: { openPath: vi.fn(), openExternal: vi.fn(() => Promise.resolve()) },
}))
vi.mock('node:child_process', () => ({
  execFile: vi.fn(),
}))
vi.mock('./desktop-config', () => ({
  APP_NAME: 'XCAGI',
  DEFAULT_PORT: 17500,
  shellIconPath: vi.fn(() => '/tmp/icon.png'),
}))
vi.mock('./window-manager', () => ({
  broadcastToRenderer: vi.fn(),
  toggleMainWindow: vi.fn(),
}))
vi.mock('./backend-process', () => ({ writeBackendLog: vi.fn() }))
vi.mock('./updater', () => ({
  readLocalProductVersion: vi.fn(() => '1.0.0.1'),
  runUpdateCheckWithDirectNet: vi.fn(),
}))
vi.mock('./desktop-navigation', () => ({ parseDesktopDeepLink: vi.fn(() => null) }))

import { execFile } from 'node:child_process'
import { openKellaiDesktop } from './app-shell'

const execFileMock = execFile as unknown as ReturnType<typeof vi.fn>

describe('openKellaiDesktop（客来来第三方联动）', () => {
  it('macOS：open -b 找不到应用时返回友好提示（不再透传底层英文错误）', async () => {
    const originalPlatform = process.platform
    Object.defineProperty(process, 'platform', { value: 'darwin', configurable: true })

    execFileMock.mockImplementationOnce((_cmd: string, _args: string[], cb: (err: Error | null) => void) => {
      cb(new Error('application not found'))
    })

    const result = await openKellaiDesktop()

    expect(result.ok).toBe(false)
    expect(result.reason).toBe('未检测到客来来桌面端，请先安装并打开一次客来来。')

    Object.defineProperty(process, 'platform', { value: originalPlatform, configurable: true })
  })

  it('macOS：open -b 成功时返回 ok:true', async () => {
    const originalPlatform = process.platform
    Object.defineProperty(process, 'platform', { value: 'darwin', configurable: true })

    execFileMock.mockImplementationOnce((_cmd: string, _args: string[], cb: (err: Error | null) => void) => {
      cb(null)
    })

    const result = await openKellaiDesktop()

    expect(result.ok).toBe(true)

    Object.defineProperty(process, 'platform', { value: originalPlatform, configurable: true })
  })
})