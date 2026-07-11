import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

// 必须在 import main 之前用 vi.hoisted + vi.mock 替换 electron 与 electron-updater
// vi.hoisted 内部不能用 ES import 的模块（尚未初始化），用 require() 拿原生模块
const electronMocks = vi.hoisted(() => {
  const nodeOs = require('node:os')
  const nodePath = require('node:path')
  const nodeFs = require('node:fs')
  const tmpDir = nodeOs.tmpdir()
  const stamp = `${Date.now()}-${Math.random().toString(36).slice(2)}`
  const userDataDir = nodePath.join(tmpDir, `xcagi-test-userdata-${stamp}`)
  nodeFs.mkdirSync(userDataDir, { recursive: true })

  const app = {
    isPackaged: false as boolean,
    getPath: vi.fn((name: string) => {
      if (name === 'userData') return userDataDir
      if (name === 'appData') return tmpDir
      if (name === 'downloads') return tmpDir
      return nodePath.join(tmpDir, `xcagi-mock-${name}`)
    }),
    setPath: vi.fn(),
    getVersion: vi.fn(() => '10.0.0'),
    commandLine: { appendSwitch: vi.fn() },
    quit: vi.fn(),
    requestSingleInstanceLock: vi.fn(() => true),
    on: vi.fn(),
    once: vi.fn(),
    whenReady: vi.fn(() => Promise.resolve()),
    setBadgeCount: vi.fn(),
    isQuitting: false as boolean
  }
  const BrowserWindow = vi.fn(() => ({
    loadURL: vi.fn(),
    on: vi.fn(),
    once: vi.fn(),
    webContents: { send: vi.fn(), on: vi.fn(), session: { setPermissionRequestHandler: vi.fn(), setPermissionCheckHandler: vi.fn() } },
    show: vi.fn(),
    focus: vi.fn(),
    restore: vi.fn(),
    isMinimized: vi.fn(() => false),
    isMaximized: vi.fn(() => false),
    isFullScreen: vi.fn(() => false),
    isDestroyed: vi.fn(() => false),
    getBounds: vi.fn(() => ({ x: 0, y: 0, width: 1280, height: 800 })),
    setMinimumSize: vi.fn(),
    setBounds: vi.fn(),
    flashFrame: vi.fn(),
    close: vi.fn(),
    destroy: vi.fn()
  }))
  ;(BrowserWindow as unknown as { getAllWindows: () => unknown[] }).getAllWindows = vi.fn(() => [])
  const Menu = { buildFromTemplate: vi.fn(() => ({})), setApplicationMenu: vi.fn() }
  const Tray = vi.fn(() => ({ setToolTip: vi.fn(), setContextMenu: vi.fn() }))
  const Notification = vi.fn(() => ({ show: vi.fn() }))
  ;(Notification as unknown as { isSupported: () => boolean }).isSupported = vi.fn(() => true)
  const dialog = {
    showErrorBox: vi.fn(),
    showMessageBox: vi.fn(() => Promise.resolve({ response: 0 })),
    showSaveDialog: vi.fn(() => Promise.resolve({ canceled: true })),
    showOpenDialog: vi.fn(() => Promise.resolve({ canceled: true }))
  }
  const ipcMain = { handle: vi.fn() }
  const shell = { openPath: vi.fn(), openExternal: vi.fn() }
  const session = {
    defaultSession: {
      setPermissionRequestHandler: vi.fn(),
      setPermissionCheckHandler: vi.fn(),
      setProxy: vi.fn(() => Promise.resolve())
    },
    fromPartition: vi.fn(() => ({
      setProxy: vi.fn(() => Promise.resolve())
    }))
  }
  const defaultDisplay = { workArea: { x: 0, y: 0, width: 1920, height: 1080 } }
  const screen = {
    getPrimaryDisplay: vi.fn(() => defaultDisplay),
    getDisplayMatching: vi.fn(() => defaultDisplay),
    on: vi.fn()
  }
  const nativeImage = { createFromPath: vi.fn(() => ({})), createEmpty: vi.fn(() => ({})) }
  return {
    app,
    BrowserWindow,
    Menu,
    Tray,
    Notification,
    dialog,
    ipcMain,
    shell,
    session,
    screen,
    nativeImage,
    __userDataDir: userDataDir
  }
})

const updaterMocks = vi.hoisted(() => ({
  autoUpdater: {
    autoDownload: false,
    autoInstallOnAppQuit: true,
    setFeedURL: vi.fn(),
    on: vi.fn(),
    checkForUpdates: vi.fn(() => Promise.resolve({})),
    downloadUpdate: vi.fn(() => Promise.resolve()),
    quitAndInstall: vi.fn()
  }
}))

vi.mock('electron', () => electronMocks)
vi.mock('electron-updater', () => ({ autoUpdater: updaterMocks.autoUpdater }))

describe('main — work-area-aware window geometry', () => {
  it('centres the default window inside a normal primary work area', async () => {
    const { calculateInitialWindowLayout } = await import('./main.js')

    expect(calculateInitialWindowLayout({ x: 0, y: 0, width: 1920, height: 1040 })).toEqual({
      x: 240,
      y: 60,
      width: 1440,
      height: 920,
      minWidth: 1180,
      minHeight: 760
    })
  })

  it('shrinks the initial size and minimums when the taskbar leaves a small work area', async () => {
    const { calculateInitialWindowLayout } = await import('./main.js')

    expect(calculateInitialWindowLayout({ x: 100, y: 40, width: 1024, height: 720 })).toEqual({
      x: 108,
      y: 48,
      width: 1008,
      height: 704,
      minWidth: 1008,
      minHeight: 704
    })
  })

  it('clamps a window from a removed display into the complete remaining work area', async () => {
    const { clampWindowBoundsToWorkArea } = await import('./main.js')

    expect(
      clampWindowBoundsToWorkArea(
        { x: 2100, y: -120, width: 1440, height: 920 },
        { x: 0, y: 0, width: 1366, height: 728 }
      )
    ).toEqual({ x: 8, y: 8, width: 1350, height: 712 })
  })

  it('updates the native minimum size before applying corrected bounds', async () => {
    const bounds = { x: 2100, y: -120, width: 1440, height: 920 }
    const setMinimumSize = vi.fn()
    const setBounds = vi.fn()
    const win = {
      isMaximized: vi.fn(() => false),
      isFullScreen: vi.fn(() => false),
      getBounds: vi.fn(() => bounds),
      setMinimumSize,
      setBounds
    } as unknown as Electron.BrowserWindow
    electronMocks.screen.getDisplayMatching.mockReturnValueOnce({
      workArea: { x: 0, y: 0, width: 1366, height: 728 }
    })
    const { ensureWindowInWorkArea } = await import('./main.js')

    ensureWindowInWorkArea(win)

    expect(electronMocks.screen.getDisplayMatching).toHaveBeenCalledWith(bounds)
    expect(setMinimumSize).toHaveBeenCalledWith(1180, 712)
    expect(setBounds).toHaveBeenCalledWith({ x: 8, y: 8, width: 1350, height: 712 })
  })

  it.each([
    ['maximized', true, false],
    ['full-screen', false, true]
  ])('does not mutate a %s window during display metric changes', async (_state, maximized, fullScreen) => {
    const getBounds = vi.fn(() => ({ x: 0, y: 0, width: 1920, height: 1040 }))
    const setMinimumSize = vi.fn()
    const setBounds = vi.fn()
    const win = {
      isMaximized: vi.fn(() => maximized),
      isFullScreen: vi.fn(() => fullScreen),
      getBounds,
      setMinimumSize,
      setBounds
    } as unknown as Electron.BrowserWindow
    const { ensureWindowInWorkArea } = await import('./main.js')

    ensureWindowInWorkArea(win)

    expect(getBounds).not.toHaveBeenCalled()
    expect(setMinimumSize).not.toHaveBeenCalled()
    expect(setBounds).not.toHaveBeenCalled()
  })
})

describe('main — resolveDesktopUserDataPath', () => {
  it('uses the XCAGI default below appData when no override is configured', async () => {
    const { resolveDesktopUserDataPath } = await import('./main.js')
    const appData = path.join(os.tmpdir(), 'xcagi-app-data')

    expect(resolveDesktopUserDataPath(appData, '')).toBe(path.join(appData, 'XCAGI'))
  })

  it('uses an explicit XCAGI_DATA_DIR for isolated launch and startup measurements', async () => {
    const { resolveDesktopUserDataPath } = await import('./main.js')
    const isolated = path.join(os.tmpdir(), 'xcagi-isolated-data')

    expect(resolveDesktopUserDataPath('/ignored', `  ${isolated}  `)).toBe(path.resolve(isolated))
  })
})

describe('main — waitForDesktopRendererReady', () => {
  it('returns evidence only after the trusted Vue renderer is mounted', async () => {
    const executeJavaScript = vi
      .fn()
      .mockResolvedValueOnce({
        url: 'http://127.0.0.1:17500/',
        vueActive: true,
        rootChildCount: 0
      })
      .mockResolvedValueOnce({
        url: 'http://127.0.0.1:17500/',
        vueActive: true,
        rootChildCount: 2
      })
    const win = {
      isDestroyed: vi.fn(() => false),
      webContents: { executeJavaScript }
    } as unknown as Electron.BrowserWindow
    const { waitForDesktopRendererReady } = await import('./main.js')

    await expect(waitForDesktopRendererReady(win, 100, 0)).resolves.toEqual({
      url: 'http://127.0.0.1:17500/',
      vueActive: true,
      rootChildCount: 2
    })
    expect(executeJavaScript).toHaveBeenCalledTimes(2)
  })

  it('rejects an unmounted renderer instead of treating process survival as success', async () => {
    const win = {
      isDestroyed: vi.fn(() => false),
      webContents: {
        executeJavaScript: vi.fn().mockResolvedValue({
          url: 'http://127.0.0.1:17500/',
          vueActive: false,
          rootChildCount: 0
        })
      }
    } as unknown as Electron.BrowserWindow
    const { waitForDesktopRendererReady } = await import('./main.js')

    await expect(waitForDesktopRendererReady(win, 0, 0)).rejects.toThrow(
      'Electron renderer did not become ready within 0ms'
    )
  })
})

describe('main — strict backend application readiness', () => {
  it('requires an explicit readyForUi signal for the desktop smoke handshake', async () => {
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce({
        ok: true,
        headers: { get: vi.fn(() => 'uvicorn') }
      } as unknown as Response)
      .mockResolvedValueOnce({
        ok: true,
        json: vi.fn(async () => ({ readyForUi: true }))
      } as unknown as Response)
    const { waitForBackendApplicationReady } = await import('./main.js')

    try {
      await expect(waitForBackendApplicationReady(17500, 100, true)).resolves.toBeUndefined()
      expect(fetchSpy).toHaveBeenNthCalledWith(
        1,
        'http://127.0.0.1:17500/api/ping',
        expect.any(Object)
      )
      expect(fetchSpy).toHaveBeenNthCalledWith(
        2,
        'http://127.0.0.1:17500/api/desktop/status',
        expect.any(Object)
      )
    } finally {
      fetchSpy.mockRestore()
    }
  })

  it('rejects a responsive backend that never becomes ready for UI', async () => {
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce({
        ok: true,
        headers: { get: vi.fn(() => 'uvicorn') }
      } as unknown as Response)
      .mockResolvedValue({
        ok: true,
        json: vi.fn(async () => ({ readyForUi: false }))
      } as unknown as Response)
    const { waitForBackendApplicationReady } = await import('./main.js')

    try {
      await expect(waitForBackendApplicationReady(17500, 1, true)).rejects.toThrow(
        '/api/desktop/status'
      )
    } finally {
      fetchSpy.mockRestore()
    }
  })
})

describe('main — resolveDefaultDesktopPort', () => {
  beforeEach(() => {
    delete process.env.XCAGI_DESKTOP_PORT
  })

  it('returns 17500 by default (avoids macOS AirPlay 5000 conflict)', async () => {
    const { resolveDefaultDesktopPort } = await import('./main.js')
    expect(resolveDefaultDesktopPort()).toBe(17500)
  })

  it('respects XCAGI_DESKTOP_PORT env when valid', async () => {
    process.env.XCAGI_DESKTOP_PORT = '18000'
    const { resolveDefaultDesktopPort } = await import('./main.js')
    expect(resolveDefaultDesktopPort()).toBe(18000)
  })

  it('rejects non-numeric env and falls back to 17500', async () => {
    process.env.XCAGI_DESKTOP_PORT = 'not-a-port'
    const { resolveDefaultDesktopPort } = await import('./main.js')
    expect(resolveDefaultDesktopPort()).toBe(17500)
  })

  it('rejects 0 and negative ports', async () => {
    process.env.XCAGI_DESKTOP_PORT = '0'
    const { resolveDefaultDesktopPort } = await import('./main.js')
    expect(resolveDefaultDesktopPort()).toBe(17500)
    process.env.XCAGI_DESKTOP_PORT = '-1'
    expect(resolveDefaultDesktopPort()).toBe(17500)
  })

  it('rejects port >= 65536', async () => {
    process.env.XCAGI_DESKTOP_PORT = '65536'
    const { resolveDefaultDesktopPort } = await import('./main.js')
    expect(resolveDefaultDesktopPort()).toBe(17500)
  })

  it('accepts port 1 (minimum valid)', async () => {
    process.env.XCAGI_DESKTOP_PORT = '1'
    const { resolveDefaultDesktopPort } = await import('./main.js')
    expect(resolveDefaultDesktopPort()).toBe(1)
  })

  it('floors fractional port numbers', async () => {
    process.env.XCAGI_DESKTOP_PORT = '17500.9'
    const { resolveDefaultDesktopPort } = await import('./main.js')
    expect(resolveDefaultDesktopPort()).toBe(17500)
  })
})

describe('main — resolveDesktopBackendBindHost', () => {
  const saved = process.env.XCAGI_DESKTOP_API_HOST

  afterEach(() => {
    if (saved === undefined) delete process.env.XCAGI_DESKTOP_API_HOST
    else process.env.XCAGI_DESKTOP_API_HOST = saved
  })

  it('defaults to 0.0.0.0 for LAN pairing', async () => {
    delete process.env.XCAGI_DESKTOP_API_HOST
    const { resolveDesktopBackendBindHost } = await import('./main.js')
    expect(resolveDesktopBackendBindHost()).toBe('0.0.0.0')
  })

  it('respects XCAGI_DESKTOP_API_HOST override', async () => {
    process.env.XCAGI_DESKTOP_API_HOST = '127.0.0.1'
    const { resolveDesktopBackendBindHost } = await import('./main.js')
    expect(resolveDesktopBackendBindHost()).toBe('127.0.0.1')
  })
})

describe('main — isPortAvailable', () => {
  it('returns true for a free port', async () => {
    const { isPortAvailable } = await import('./main.js')
    // 用一个几乎不可能被占用的端口
    const port = 37891 + Math.floor(Math.random() * 100)
    expect(await isPortAvailable(port)).toBe(true)
  })

  it('returns false when port is already bound', async () => {
    const { isPortAvailable, DESKTOP_BACKEND_BIND_HOST } = await import('./main.js')
    const net = await import('node:net')
    const server = net.createServer()
    await new Promise<void>(resolve => {
      server.listen(0, DESKTOP_BACKEND_BIND_HOST, () => resolve())
    })
    const port = (server.address() as { port: number }).port
    try {
      expect(await isPortAvailable(port)).toBe(false)
    } finally {
      server.close()
    }
  })
})

describe('main — portOccupiedHint', () => {
  it('includes the port number and env var guidance', async () => {
    const { portOccupiedHint } = await import('./main.js')
    const hint = portOccupiedHint(17500)
    expect(hint).toContain('17500')
    expect(hint).toContain('XCAGI_DESKTOP_PORT')
  })

  it('appends AirPlay hint for legacy port 5000', async () => {
    const { portOccupiedHint } = await import('./main.js')
    const hint = portOccupiedHint(5000)
    expect(hint).toContain('5000')
    expect(hint).toMatch(/历史开发端口|17500/)
  })

  it('omits AirPlay hint for non-5000 ports', async () => {
    const { portOccupiedHint } = await import('./main.js')
    const hint = portOccupiedHint(17500)
    expect(hint).not.toMatch(/历史开发端口/)
  })
})

describe('main — SKU constants', () => {
  it('maps personal → minimal, enterprise → full', async () => {
    const { SKU_RUNTIME_EDITION } = await import('./main.js')
    expect(SKU_RUNTIME_EDITION.personal).toBe('minimal')
    expect(SKU_RUNTIME_EDITION.enterprise).toBe('full')
  })

  it('provides distinct update URLs per SKU', async () => {
    const { SKU_UPDATE_URL } = await import('./main.js')
    expect(SKU_UPDATE_URL.personal).toMatch(/\/personal\/$/)
    expect(SKU_UPDATE_URL.enterprise).toMatch(/\/enterprise\/$/)
    expect(SKU_UPDATE_URL.personal).not.toBe(SKU_UPDATE_URL.enterprise)
  })
})

describe('main — desktop splash & ping readiness', () => {
  it('resolveDesktopSplashUrl returns file or data url', async () => {
    const { resolveDesktopSplashUrl } = await import('./main.js')
    const url = resolveDesktopSplashUrl()
    expect(url.startsWith('file://') || url.startsWith('data:text/html')).toBe(true)
  })
})

describe('main — OTA proxy PAC', () => {
  it('routes update hosts DIRECT and others via proxy with DIRECT fallback', async () => {
    const { buildOtaPacScript } = await import('./main.js')
    const pac = buildOtaPacScript('127.0.0.1:7890')
    expect(pac).toContain("host === 'xiu-ci.com'")
    expect(pac).toContain("return 'PROXY 127.0.0.1:7890; DIRECT'")
  })

  it('parses proxy endpoint host and port', async () => {
    const { parseProxyEndpoint } = await import('./main.js')
    expect(parseProxyEndpoint('127.0.0.1:7890')).toEqual({ host: '127.0.0.1', port: 7890 })
    expect(parseProxyEndpoint('bad')).toBeNull()
  })
})

describe('main — ED25519_PUBLIC_KEY_PEM', () => {
  it('is a valid PEM-formatted Ed25519 public key', async () => {
    const { ED25519_PUBLIC_KEY_PEM } = await import('./main.js')
    expect(ED25519_PUBLIC_KEY_PEM).toContain('-----BEGIN PUBLIC KEY-----')
    expect(ED25519_PUBLIC_KEY_PEM).toContain('-----END PUBLIC KEY-----')
    // 必须能被 crypto.createPublicKey 解析
    const crypto = await import('node:crypto')
    expect(() => crypto.createPublicKey(ED25519_PUBLIC_KEY_PEM)).not.toThrow()
  })
})

describe('main — desktopInitialUrl', () => {
  it('returns base URL with ?shell=1 for non-enterprise SKU', async () => {
    const { desktopInitialUrl, DEFAULT_PORT } = await import('./main.js')
    // dev 模式 + 无 SKU env → readPackagedProductSku 返回 null
    delete process.env.XCAGI_PRODUCT_SKU
    const url = desktopInitialUrl()
    expect(url).toBe(`http://127.0.0.1:${DEFAULT_PORT}/?shell=1`)
  })

  it('returns base URL without shell query for enterprise SKU', async () => {
    process.env.XCAGI_PRODUCT_SKU = 'enterprise'
    const { desktopInitialUrl, DEFAULT_PORT } = await import('./main.js')
    const url = desktopInitialUrl()
    expect(url).toBe(`http://127.0.0.1:${DEFAULT_PORT}/`)
    delete process.env.XCAGI_PRODUCT_SKU
  })
})

describe('main — readPackagedProductSku', () => {
  beforeEach(() => {
    delete process.env.XCAGI_PRODUCT_SKU
    electronMocks.app.isPackaged = false
  })

  it('returns null in dev mode without env', async () => {
    const { readPackagedProductSku } = await import('./main.js')
    expect(readPackagedProductSku()).toBeNull()
  })

  it('returns "personal" when env XCAGI_PRODUCT_SKU=personal', async () => {
    process.env.XCAGI_PRODUCT_SKU = 'personal'
    const { readPackagedProductSku } = await import('./main.js')
    expect(readPackagedProductSku()).toBe('personal')
  })

  it('returns "enterprise" when env XCAGI_PRODUCT_SKU=enterprise', async () => {
    process.env.XCAGI_PRODUCT_SKU = 'ENTERPRISE'
    const { readPackagedProductSku } = await import('./main.js')
    expect(readPackagedProductSku()).toBe('enterprise')
  })

  it('returns null for unknown SKU values', async () => {
    process.env.XCAGI_PRODUCT_SKU = 'unknown'
    const { readPackagedProductSku } = await import('./main.js')
    expect(readPackagedProductSku()).toBeNull()
  })

  it('returns null for empty env string', async () => {
    process.env.XCAGI_PRODUCT_SKU = '   '
    const { readPackagedProductSku } = await import('./main.js')
    expect(readPackagedProductSku()).toBeNull()
  })

  it('returns null when packaged but product-sku.json missing (graceful fallback)', async () => {
    // 模拟 packaged 模式，但 resourcesPath 下没有 product-sku.json
    electronMocks.app.isPackaged = true
    const tmpResources = path.join(os.tmpdir(), `xcagi-test-resources-${Date.now()}`)
    fs.mkdirSync(tmpResources, { recursive: true })
    const savedResourcesPath = (process as { resourcesPath?: string }).resourcesPath
    ;(process as { resourcesPath?: string }).resourcesPath = tmpResources
    try {
      const { readPackagedProductSku } = await import('./main.js')
      expect(readPackagedProductSku()).toBeNull()
    } finally {
      if (savedResourcesPath === undefined) {
        delete (process as { resourcesPath?: string }).resourcesPath
      } else {
        (process as { resourcesPath?: string }).resourcesPath = savedResourcesPath
      }
      electronMocks.app.isPackaged = false
    }
  })

  it('returns SKU from product-sku.json when packaged', async () => {
    electronMocks.app.isPackaged = true
    const tmpResources = path.join(os.tmpdir(), `xcagi-test-resources-${Date.now()}-${Math.random().toString(36).slice(2)}`)
    fs.mkdirSync(tmpResources, { recursive: true })
    fs.writeFileSync(path.join(tmpResources, 'product-sku.json'), JSON.stringify({ sku: 'enterprise' }))
    const savedResourcesPath = (process as { resourcesPath?: string }).resourcesPath
    ;(process as { resourcesPath?: string }).resourcesPath = tmpResources
    try {
      const { readPackagedProductSku } = await import('./main.js')
      expect(readPackagedProductSku()).toBe('enterprise')
    } finally {
      if (savedResourcesPath === undefined) {
        delete (process as { resourcesPath?: string }).resourcesPath
      } else {
        (process as { resourcesPath?: string }).resourcesPath = savedResourcesPath
      }
      electronMocks.app.isPackaged = false
    }
  })
})

describe('main — backendEditionEnv', () => {
  beforeEach(() => {
    delete process.env.XCAGI_PRODUCT_SKU
  })

  it('returns generic edition env when no SKU (dev mode)', async () => {
    const { backendEditionEnv } = await import('./main.js')
    const env = backendEditionEnv()
    expect(env.XCAGI_PRODUCT_SKU).toBe('generic')
    expect(env.XCAGI_GENERIC_EDITION).toBe('1')
    expect(env.XCAGI_PLATFORM_SHELL).toBe('1')
    expect(env.XCAGI_DEFAULT_EDITION).toBe('generic')
  })

  it('returns full edition env for enterprise SKU', async () => {
    process.env.XCAGI_PRODUCT_SKU = 'enterprise'
    const { backendEditionEnv } = await import('./main.js')
    const env = backendEditionEnv()
    expect(env.XCAGI_PRODUCT_SKU).toBe('enterprise')
    expect(env.XCAGI_PLATFORM_SHELL).toBe('0')
    expect(env.XCAGI_DEFAULT_EDITION).toBe('full')
    expect(env.XCAGI_EDITION).toBe('full')
  })

  it('returns minimal edition env for personal SKU', async () => {
    process.env.XCAGI_PRODUCT_SKU = 'personal'
    const { backendEditionEnv } = await import('./main.js')
    const env = backendEditionEnv()
    expect(env.XCAGI_PRODUCT_SKU).toBe('personal')
    expect(env.XCAGI_PLATFORM_SHELL).toBe('1')
    expect(env.XCAGI_DEFAULT_EDITION).toBe('minimal')
    expect(env.XCAGI_EDITION).toBe('minimal')
    expect(env.XCAGI_MINIMAL_EDITION).toBe('1')
  })
})

describe('main — readJsonTextFile', () => {
  it('reads UTF-8 file content', async () => {
    const { readJsonTextFile } = await import('./main.js')
    const tmp = path.join(os.tmpdir(), `xcagi-test-utf8-${Date.now()}.json`)
    fs.writeFileSync(tmp, '{"k": "v"}', 'utf8')
    expect(readJsonTextFile(tmp)).toBe('{"k": "v"}')
    fs.unlinkSync(tmp)
  })

  it('reads UTF-16LE file with BOM', async () => {
    const { readJsonTextFile } = await import('./main.js')
    const tmp = path.join(os.tmpdir(), `xcagi-test-utf16-${Date.now()}.json`)
    const content = '{"k": "v"}'
    const buf = Buffer.from(content, 'utf16le')
    const bom = Buffer.from([0xff, 0xfe])
    fs.writeFileSync(tmp, Buffer.concat([bom, buf]))
    const result = readJsonTextFile(tmp)
    expect(result).toBe(content)
    fs.unlinkSync(tmp)
  })

  it('strips UTF-8 BOM if present', async () => {
    const { readJsonTextFile } = await import('./main.js')
    const tmp = path.join(os.tmpdir(), `xcagi-test-bom-${Date.now()}.json`)
    fs.writeFileSync(tmp, '\uFEFF{"k": "v"}', 'utf8')
    expect(readJsonTextFile(tmp)).toBe('{"k": "v"}')
    fs.unlinkSync(tmp)
  })
})

describe('main — isTrustedDesktopOrigin', () => {
  it('accepts 127.0.0.1 with matching port', async () => {
    const { isTrustedDesktopOrigin } = await import('./main.js')
    expect(isTrustedDesktopOrigin('http://127.0.0.1:17500/', 17500)).toBe(true)
  })

  it('accepts localhost with matching port', async () => {
    const { isTrustedDesktopOrigin } = await import('./main.js')
    expect(isTrustedDesktopOrigin('http://localhost:17500/', 17500)).toBe(true)
  })

  it('rejects mismatched port', async () => {
    const { isTrustedDesktopOrigin } = await import('./main.js')
    expect(isTrustedDesktopOrigin('http://127.0.0.1:5000/', 17500)).toBe(false)
  })

  it('rejects external hostname', async () => {
    const { isTrustedDesktopOrigin } = await import('./main.js')
    expect(isTrustedDesktopOrigin('http://example.com:17500/', 17500)).toBe(false)
  })

  it('rejects https protocol', async () => {
    const { isTrustedDesktopOrigin } = await import('./main.js')
    expect(isTrustedDesktopOrigin('https://127.0.0.1:17500/', 17500)).toBe(false)
  })

  it('rejects file protocol', async () => {
    const { isTrustedDesktopOrigin } = await import('./main.js')
    expect(isTrustedDesktopOrigin('file:///etc/passwd', 17500)).toBe(false)
  })

  it('returns false for undefined input', async () => {
    const { isTrustedDesktopOrigin } = await import('./main.js')
    expect(isTrustedDesktopOrigin(undefined, 17500)).toBe(false)
  })

  it('returns false for malformed URL', async () => {
    const { isTrustedDesktopOrigin } = await import('./main.js')
    expect(isTrustedDesktopOrigin('not-a-url', 17500)).toBe(false)
  })
})

describe('main — isSafeExternalUrl', () => {
  it.each([
    'https://xiu-ci.com/market',
    'http://192.168.1.10:17500/docs',
    'mailto:support@xiu-ci.com'
  ])('allows expected external link %s', async url => {
    const { isSafeExternalUrl } = await import('./main.js')
    expect(isSafeExternalUrl(url)).toBe(true)
  })

  it.each([
    'file:///etc/passwd',
    'smb://attacker/share',
    'javascript:alert(1)',
    'ms-msdt:/id PCWDiagnostic',
    'not a url',
    ''
  ])('blocks unsafe external link %s', async url => {
    const { isSafeExternalUrl } = await import('./main.js')
    expect(isSafeExternalUrl(url)).toBe(false)
  })

  it('blocks missing input', async () => {
    const { isSafeExternalUrl } = await import('./main.js')
    expect(isSafeExternalUrl(undefined)).toBe(false)
  })
})

describe('main — readPackagedAppVersion', () => {
  it('returns "dev" in unpackaged mode', async () => {
    electronMocks.app.isPackaged = false
    const { readPackagedAppVersion } = await import('./main.js')
    expect(readPackagedAppVersion()).toBe('dev')
  })
})

describe('main — frontend cache', () => {
  let savedResourcesPath: string | undefined
  let tmpResources: string

  beforeEach(() => {
    electronMocks.app.isPackaged = false
    savedResourcesPath = (process as { resourcesPath?: string }).resourcesPath
    tmpResources = path.join(os.tmpdir(), `xcagi-test-fe-cache-${Date.now()}-${Math.random().toString(36).slice(2)}`)
    fs.mkdirSync(tmpResources, { recursive: true })
    ;(process as { resourcesPath?: string }).resourcesPath = tmpResources
  })

  afterEach(() => {
    if (savedResourcesPath === undefined) {
      delete (process as { resourcesPath?: string }).resourcesPath
    } else {
      (process as { resourcesPath?: string }).resourcesPath = savedResourcesPath
    }
  })

  it('shouldClearFrontendCache returns true when marker missing (first run)', async () => {
    const { shouldClearFrontendCache } = await import('./main.js')
    // dev mode: readFrontendCacheKey returns "dev" (no hash)
    // 首次运行 marker 不存在 → should clear
    expect(shouldClearFrontendCache()).toBe(true)
  })

  it('markFrontendCacheCleared writes marker file', async () => {
    const { markFrontendCacheCleared, shouldClearFrontendCache } = await import('./main.js')
    markFrontendCacheCleared()
    // 在 dev 模式下 readFrontendCacheKey 恒返回 "dev"，写入后再读应一致 → 不需要清
    expect(shouldClearFrontendCache()).toBe(false)
  })
})

describe('main — bootstrap not called in test mode', () => {
  it('XCAGI_DESKTOP_TEST=1 prevents bootstrap from running', async () => {
    // 测试环境已通过 vitest.config.ts env 设置 XCAGI_DESKTOP_TEST=1
    expect(process.env.XCAGI_DESKTOP_TEST).toBe('1')
    // 重新 import main 不应触发 app.requestSingleInstanceLock 等 bootstrap 副作用
    electronMocks.app.requestSingleInstanceLock.mockClear()
    await import('./main.js')
    // bootstrap 未运行 → requestSingleInstanceLock 不应被调用
    expect(electronMocks.app.requestSingleInstanceLock).not.toHaveBeenCalled()
  })

  it('ipcMain.handle is not called by bootstrap in test mode', async () => {
    electronMocks.ipcMain.handle.mockClear()
    await import('./main.js')
    expect(electronMocks.ipcMain.handle).not.toHaveBeenCalled()
  })
})

describe('main — mobile pairing purpose isolation', () => {
  it('requires an explicit management purpose and defaults every other value to enterprise', async () => {
    const { normalizePairingPurpose } = await import('./main.js')

    expect(normalizePairingPurpose('management')).toBe('management')
    expect(normalizePairingPurpose('enterprise')).toBe('enterprise')
    expect(normalizePairingPurpose('admin')).toBe('enterprise')
    expect(normalizePairingPurpose(undefined)).toBe('enterprise')
  })
})
