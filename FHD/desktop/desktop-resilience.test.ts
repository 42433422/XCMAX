import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  quit: vi.fn(),
  showMessageBox: vi.fn(),
  downloadUpdate: vi.fn(),
  installUpdate: vi.fn(),
  forceRequired: vi.fn(),
}))

vi.mock('electron', () => ({
  app: { quit: mocks.quit, getPath: vi.fn(), getVersion: vi.fn(), setPath: vi.fn() },
  crashReporter: { start: vi.fn() },
  dialog: { showMessageBox: mocks.showMessageBox },
}))

vi.mock('./updater', () => ({
  downloadUpdate: mocks.downloadUpdate,
  installUpdate: mocks.installUpdate,
  isForceUpgradeRequired: mocks.forceRequired,
  readLocalProductVersion: vi.fn(() => '1.0.0.0'),
}))

import { createForceUpgradeHandler } from './desktop-resilience'

describe('desktop resilience force-upgrade handler', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.forceRequired.mockReturnValue(true)
    mocks.showMessageBox.mockResolvedValue({ response: 0 })
    mocks.downloadUpdate.mockResolvedValue(undefined)
    mocks.installUpdate.mockResolvedValue(undefined)
  })

  it('does nothing when the signed policy does not require an upgrade', async () => {
    mocks.forceRequired.mockReturnValue(false)
    const handler = createForceUpgradeHandler({
      appName: 'XCAGI',
      writeLog: vi.fn(),
      beforeInstall: vi.fn(),
      onInstallFailed: vi.fn(),
      prepareQuit: vi.fn(),
    })

    await handler()

    expect(mocks.showMessageBox).not.toHaveBeenCalled()
    expect(mocks.downloadUpdate).not.toHaveBeenCalled()
  })

  it('downloads and installs after explicit confirmation', async () => {
    const beforeInstall = vi.fn()
    const onInstallFailed = vi.fn()
    const prepareQuit = vi.fn()
    const handler = createForceUpgradeHandler({
      appName: 'XCAGI',
      writeLog: vi.fn(),
      beforeInstall,
      onInstallFailed,
      prepareQuit,
    })

    await handler()

    expect(mocks.downloadUpdate).toHaveBeenCalledOnce()
    expect(mocks.installUpdate).toHaveBeenCalledWith(beforeInstall, onInstallFailed, prepareQuit)
  })

  it('quits without downloading when the user rejects the blocking upgrade', async () => {
    mocks.showMessageBox.mockResolvedValue({ response: 1 })
    const handler = createForceUpgradeHandler({
      appName: 'XCAGI',
      writeLog: vi.fn(),
      beforeInstall: vi.fn(),
      onInstallFailed: vi.fn(),
      prepareQuit: vi.fn(),
    })

    await handler()

    expect(mocks.quit).toHaveBeenCalledOnce()
    expect(mocks.downloadUpdate).not.toHaveBeenCalled()
  })
})
