import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const mocks = vi.hoisted(() => ({
  quit: vi.fn(),
  showMessageBox: vi.fn(),
  downloadUpdate: vi.fn(),
  installUpdate: vi.fn(),
  forceRequired: vi.fn(),
  getPath: vi.fn(),
  setPath: vi.fn(),
  crashReporterStart: vi.fn(),
}))

vi.mock('electron', () => ({
  app: {
    quit: mocks.quit,
    getPath: mocks.getPath,
    getVersion: vi.fn(),
    setPath: mocks.setPath,
  },
  crashReporter: { start: mocks.crashReporterStart },
  dialog: { showMessageBox: mocks.showMessageBox },
}))

vi.mock('./updater', () => ({
  downloadUpdate: mocks.downloadUpdate,
  isForceUpgradeRequired: mocks.forceRequired,
  readLocalProductVersion: vi.fn(() => '1.0.0.0'),
}))
vi.mock('./desktop-install-update', () => ({
  installUpdate: mocks.installUpdate,
}))

import { createForceUpgradeHandler, initializeLocalCrashReporting, reportRendererError } from './desktop-resilience'

describe('desktop resilience force-upgrade handler', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.forceRequired.mockReturnValue(true)
    mocks.showMessageBox.mockResolvedValue({ response: 0 })
    mocks.downloadUpdate.mockResolvedValue(undefined)
    mocks.installUpdate.mockResolvedValue(undefined)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
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

/**
 * M12 回归：桌面崩溃上报通道必须携带 `X-XCAGI-Desktop-Local: 1`。
 *
 * 后端 `app/middleware/csrf.py` 只对「带该专用头」的本机桌面上报做 CSRF 豁免；
 * 缺少该头时 Electron 主进程的每一次上报都会在中间件层被 403 拒绝，且失败在
 * 客户端是静默的（只写一行 `[crash] upload failed ...`），崩溃现场永远不落盘。
 */
describe('desktop crash reporting — M12 CSRF 豁免请求头', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('JSON 渲染错误上报携带专用头且保留 application/json', () => {
    const fetchMock = vi.fn(async () => ({ ok: true, status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    reportRendererError({ port: 17500, writeLog: vi.fn() }, { type: 'renderer', error: 'boom' })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('http://127.0.0.1:17500/api/desktop/crash-report')
    expect(init.method).toBe('POST')
    expect(init.headers).toEqual({
      'Content-Type': 'application/json',
      'X-XCAGI-Desktop-Local': '1',
    })
  })

  it('minidump 上报携带专用头，且不得手工设置 Content-Type（否则丢失 boundary）', async () => {
    const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-m12-'))
    const crashDir = path.join(tmpRoot, 'crash-dumps')
    fs.mkdirSync(crashDir, { recursive: true })
    fs.writeFileSync(path.join(crashDir, 'crash-1.dmp'), Buffer.from('dump'))
    mocks.getPath.mockImplementation((name: string) =>
      name === 'crashDumps' ? crashDir : tmpRoot,
    )

    const fetchMock = vi.fn(async () => ({ ok: true, status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    vi.useFakeTimers()

    try {
      initializeLocalCrashReporting({ port: 17500, writeLog: vi.fn() })
      await vi.advanceTimersByTimeAsync(30_001)

      expect(fetchMock).toHaveBeenCalledTimes(1)
      const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
      expect(url).toBe('http://127.0.0.1:17500/api/desktop/crash-report')
      expect(init.headers).toEqual({ 'X-XCAGI-Desktop-Local': '1' })
      expect(Object.keys(init.headers as Record<string, string>)).not.toContain('Content-Type')
      // 上报成功后写入 `.uploaded` 标记，避免下次启动重复上报
      expect(fs.existsSync(path.join(crashDir, '.uploaded-markers', 'crash-1.dmp.ok'))).toBe(true)
    } finally {
      vi.useRealTimers()
      fs.rmSync(tmpRoot, { recursive: true, force: true })
    }
  })
})
