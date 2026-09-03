import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => {
  const handlers = new Map<string, (payload: Record<string, unknown>) => void>()
  const autoUpdater = {
    autoDownload: true,
    autoInstallOnAppQuit: true,
    setFeedURL: vi.fn(),
    on: vi.fn((name: string, handler: (payload: Record<string, unknown>) => void) => {
      handlers.set(name, handler)
    }),
    checkForUpdates: vi.fn(),
    downloadUpdate: vi.fn(),
    quitAndInstall: vi.fn(),
  }
  return { autoUpdater, handlers }
})

vi.mock('electron-updater', () => ({ autoUpdater: mocks.autoUpdater }))
vi.mock('electron', () => ({
  app: {
    isPackaged: true,
    getVersion: vi.fn(() => '1.0.0'),
    getPath: vi.fn(() => '/tmp/xcagi-updater-test'),
  },
  net: {},
  session: {
    defaultSession: {
      resolveProxy: vi.fn(async () => 'DIRECT'),
      setProxy: vi.fn(async () => undefined),
    },
  },
}))

describe('updater install rollback contract', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.resetModules()
    mocks.handlers.clear()
    mocks.autoUpdater.on.mockClear()
    mocks.autoUpdater.quitAndInstall.mockReset()
    delete process.env.XCAGI_UPDATE_URL
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  async function markDownloaded(version: string, buildSha = '') {
    const updater = await import('./updater.js')
    updater.configureUpdater({
      isDestroyed: () => false,
      webContents: { send: vi.fn() },
    } as never)
    const handler = mocks.handlers.get('update-downloaded')
    expect(handler).toBeTypeOf('function')
    handler?.({ version, buildSha, files: [] })
    return updater
  }

  it('passes the downloaded version to rollback preparation', async () => {
    const updater = await markDownloaded('1.0.0', 'abcdef1234567890')
    const beforeInstall = vi.fn(async () => undefined)
    await updater.installUpdate(beforeInstall)
    expect(beforeInstall).toHaveBeenCalledWith('1.0.0+abcdef123456')
    expect(mocks.autoUpdater.quitAndInstall).toHaveBeenCalledWith(false, true)
  })

  it('blocks quitAndInstall and cleans the marker when preparation fails', async () => {
    const updater = await markDownloaded('1.0.0.0')
    const cleanup = vi.fn(async () => undefined)
    await expect(
      updater.installUpdate(
        async () => {
          throw new Error('rollback backup failed')
        },
        cleanup,
      ),
    ).rejects.toThrow('rollback backup failed')
    expect(cleanup).toHaveBeenCalledOnce()
    expect(mocks.autoUpdater.quitAndInstall).not.toHaveBeenCalled()
  })

  it('cleans the marker when quitAndInstall throws synchronously', async () => {
    const updater = await markDownloaded('1.0.0.0')
    mocks.autoUpdater.quitAndInstall.mockImplementationOnce(() => {
      throw new Error('installer launch failed')
    })
    const cleanup = vi.fn()
    await expect(updater.installUpdate(async () => undefined, cleanup)).rejects.toThrow(
      'installer launch failed',
    )
    expect(cleanup).toHaveBeenCalledOnce()
  })

  it('stops the backend via prepareQuit before quitAndInstall', async () => {
    const updater = await markDownloaded('1.0.0.1')
    const callOrder: string[] = []
    const prepareQuit = vi.fn(async () => {
      callOrder.push('prepareQuit')
    })
    mocks.autoUpdater.quitAndInstall.mockImplementationOnce(() => {
      callOrder.push('quitAndInstall')
    })

    await updater.installUpdate(undefined, undefined, prepareQuit)

    // 原生 quitAndInstall 的 terminate 路径下 will-quit 异步关闭后端不可靠，
    // 必须在交出退出控制权前完成后端停止。
    expect(callOrder).toEqual(['prepareQuit', 'quitAndInstall'])
  })

  it('blocks quitAndInstall when prepareQuit fails and runs cleanup', async () => {
    const updater = await markDownloaded('1.0.0.1')
    const cleanup = vi.fn(async () => undefined)
    const prepareQuit = vi.fn(async () => {
      throw new Error('backend stop failed')
    })

    await expect(
      updater.installUpdate(undefined, cleanup, prepareQuit),
    ).rejects.toThrow('backend stop failed')
    expect(cleanup).toHaveBeenCalledOnce()
    expect(mocks.autoUpdater.quitAndInstall).not.toHaveBeenCalled()
  })
})
