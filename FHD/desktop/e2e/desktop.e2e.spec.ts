import { _electron as electron, expect, test, type ElectronApplication, type Frame, type Page } from '@playwright/test'
import fs from 'node:fs'
import net from 'node:net'
import os from 'node:os'
import path from 'node:path'
import { preserveElectronDiagnostics } from './diagnostics'

// 实际 Electron + stub 后端覆盖启动、preload 与 IPC 往返；不代替安装包业务验收。

let electronApp: ElectronApplication
let electronProcess: ReturnType<ElectronApplication['process']> | undefined
let page: Page
let userDataDir: string
let backendPort: number

type XcagiDesktopBridge = {
  getDataDir: () => Promise<string>
  getAppIdentity: () => Promise<{ version: string; name: string; isPackaged: boolean }>
  clipboardWriteText: (text: string) => Promise<{ ok: boolean }>
  clipboardReadText: () => Promise<string>
  consumeDeepLink: () => Promise<string | null>
  getAutoLaunch: () => Promise<boolean>
}

/** 断言 preload 桥已注入（桥对象的方法不可跨 evaluate 序列化，调用须在页面上下文内联）。 */
async function assertBridge(): Promise<void> {
  const hasBridge = await page.evaluate(() =>
    Boolean((window as unknown as { xcagiDesktop?: XcagiDesktopBridge }).xcagiDesktop),
  )
  if (!hasBridge) {
    throw new Error('window.xcagiDesktop 未暴露（preload/contextBridge 失效）')
  }
}

async function findFreePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const srv = net.createServer()
    srv.once('error', reject)
    srv.listen(0, '127.0.0.1', () => {
      const address = srv.address()
      if (!address || typeof address === 'string') {
        srv.close(() => reject(new Error('无法分配空闲端口')))
        return
      }
      srv.close(() => resolve(address.port))
    })
  })
}

async function launchApp(): Promise<void> {
  electronApp = await electron.launch({
    args: ['-r', path.join(__dirname, 'patch-backend.cjs'), '.'],
    cwd: path.resolve(__dirname, '..'),
    env: {
      ...process.env,
      // E2E 隔离开关：跳过登录项/协议注册/全局快捷键/OTA 自动检查（见 main.ts）
      XCAGI_DESKTOP_E2E: '1',
      XCAGI_DESKTOP_PORT: String(backendPort),
      XCAGI_DESKTOP_USER_DATA_DIR: userDataDir,
    },
  })
  electronProcess = electronApp.process()
  page = await electronApp.firstWindow()
  page.on('console', msg => {
    if (msg.type() === 'error') {
      console.info(`[renderer console.error] ${msg.text()}`)
    }
  })
}

test.beforeAll(async () => {
  backendPort = await findFreePort()
  userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-e2e-userdata-'))
  await launchApp()
})

test.afterAll(async ({}, testInfo) => {
  try {
    if (electronApp) await electronApp.close()
  } finally {
    if (userDataDir) {
      preserveElectronDiagnostics(electronProcess, userDataDir, testInfo)
      fs.rmSync(userDataDir, { recursive: true, force: true })
    }
  }
})

test('真实启动链路：splash → 后端就绪探测 → 加载主界面', async () => {
  // 窗口首先加载 splash（file:// 或 data:），后端 ping 就绪后跳主界面
  await page.waitForURL(`http://127.0.0.1:${backendPort}/?shell=1`, { timeout: 90_000 })
  await expect(page.locator('#e2e-marker')).toHaveText('XCAGI_E2E_OK')
  await expect(page).toHaveTitle('XCAGI')
})

test('安全基线：contextIsolation 生效，渲染进程无 Node API 泄漏', async () => {
  const leaked = await page.evaluate(() => ({
    requireType: typeof (window as unknown as { require?: unknown }).require,
    processType: typeof (window as unknown as { process?: unknown }).process,
  }))
  expect(leaked.requireType).toBe('undefined')
  expect(leaked.processType).toBe('undefined')
})

test('preload 桥存在且主进程 executeJavaScript 注入平台 class', async () => {
  const hasBridge = await page.evaluate(() =>
    Boolean((window as unknown as { xcagiDesktop?: unknown }).xcagiDesktop),
  )
  expect(hasBridge).toBe(true)
  // tagDesktopWebContents：主进程向渲染文档根节点注入 xcagi-electron 类
  await expect(page.locator('html')).toHaveClass(/xcagi-electron/)
})

test('真实 IPC 往返：getDataDir 返回主进程 userData 路径', async () => {
  await assertBridge()
  const dataDir = await page.evaluate(() =>
    (window as unknown as { xcagiDesktop: XcagiDesktopBridge }).xcagiDesktop.getDataDir(),
  )
  expect(dataDir).toBe(userDataDir)
  const identity = await page.evaluate(() => (window as unknown as { xcagiDesktop: XcagiDesktopBridge }).xcagiDesktop.getAppIdentity())
  expect(identity).toMatchObject({ version: 'dev', isPackaged: false })
})

test('真实 IPC 往返：剪贴板写入后可读回', async () => {
  const token = `xcagi-e2e-${Date.now()}`
  await page.evaluate(
    value => (window as unknown as { xcagiDesktop: XcagiDesktopBridge }).xcagiDesktop.clipboardWriteText(value),
    token,
  )
  const text = await page.evaluate(() =>
    (window as unknown as { xcagiDesktop: XcagiDesktopBridge }).xcagiDesktop.clipboardReadText(),
  )
  expect(text).toBe(token)
})

async function expectRetiredWorkspaceCapability(target: Page | Frame): Promise<void> {
  // The normal stub 404 observes headers; it does not assert Python route retirement.
  const capability = await target.evaluate(async () => {
    const response = await fetch('/api/local-workspace/status', { headers: { 'X-XCAGI-Desktop-Local': '1' } })
    return response.headers.get('X-E2E-Workspace-Capability-Present')
  })
  expect(capability).toBe('false')
}

test('退役工作区能力不再注入任何窗口或子框架，未登记窗口仍被 IPC 拒绝', async () => {
  await expectRetiredWorkspaceCapability(page)
  const opened = electronApp.waitForEvent('window')
  await page.evaluate(() => (window as unknown as { xcagiDesktop: { openWindow: (url: string) => Promise<unknown> } })
    .xcagiDesktop.openWindow(window.location.origin))
  const auxiliary = await opened
  try {
    await auxiliary.waitForURL(`http://127.0.0.1:${backendPort}/`)
    await expectRetiredWorkspaceCapability(auxiliary)
    expect(await auxiliary.evaluate(() => (window as unknown as { xcagiDesktop: XcagiDesktopBridge }).xcagiDesktop.getDataDir())).toBe(userDataDir)
  } finally { await auxiliary.close() }
  await page.evaluate(() => {
    const iframe = document.createElement('iframe')
    iframe.id = 'retired-workspace-probe'
    iframe.src = '/'
    document.body.append(iframe)
  })
  try {
    await expect.poll(() => page.frames().length).toBe(2)
    const iframe = page.frames().find(frame => frame !== page.mainFrame())!
    await iframe.waitForURL(`http://127.0.0.1:${backendPort}/`)
    await expectRetiredWorkspaceCapability(iframe)
  } finally { await page.evaluate(() => document.getElementById('retired-workspace-probe')?.remove()) }
  const unregistered = electronApp.waitForEvent('window')
  await electronApp.evaluate(async ({ app, BrowserWindow }, port) => {
    const unrelated = new BrowserWindow({ show: false, webPreferences: {
      sandbox: true, contextIsolation: true, preload: process.getBuiltinModule('path').join(app.getAppPath(), 'dist/preload.js'),
    } })
    await unrelated.loadURL(`http://127.0.0.1:${port}/`)
  }, backendPort)
  const unrelated = await unregistered
  try {
    await expectRetiredWorkspaceCapability(unrelated)
    expect(await unrelated.evaluate(() => (window as unknown as { xcagiDesktop: XcagiDesktopBridge }).xcagiDesktop.getDataDir()))
      .toEqual({ ok: false, reason: 'untrusted_sender' })
  } finally { await unrelated.close() }
})

async function backendIdentity(restart = false) {
  return electronApp.evaluate(async ({ app }, { port, restart }) => {
    const requireFromApp = process.getBuiltinModule('module').createRequire(
      process.getBuiltinModule('path').join(app.getAppPath(), 'package.json'),
    )
    const state = requireFromApp('./dist/runtime-state.js')
    const backend = requireFromApp('./dist/backend-process.js')
    let invalidated = false
    if (restart) {
      await backend.stopBackend()
      invalidated = !state.hasVerifiedDesktopBackend()
      await backend.startBackend()
      await backend.waitForBackendPing(port, 15_000)
    }
    return { invalidated, verified: state.hasVerifiedDesktopBackend(), pid: state.desktopRuntime.backendProcess?.pid,
      fingerprint: process.getBuiltinModule('crypto').createHash('sha256')
        .update(requireFromApp('./dist/backend-env.js').desktopWorkspaceToken).digest('hex') }
  }, { port: backendPort, restart })
}

test('后端重启重新验证子进程，主进程重启轮换身份且不恢复工作区能力', async () => {
  const before = await backendIdentity()
  expect(before.verified).toBe(true)
  const restarted = await backendIdentity(true)
  expect(restarted).toMatchObject({ invalidated: true, verified: true, fingerprint: before.fingerprint })
  expect(restarted.pid).not.toBe(before.pid)
  await expectRetiredWorkspaceCapability(page)
  await electronApp.close()
  electronApp = undefined!
  await launchApp()
  await page.waitForURL(`http://127.0.0.1:${backendPort}/?shell=1`, { timeout: 90_000 })
  await expect(page.locator('#e2e-marker')).toHaveText('XCAGI_E2E_OK')
  const relaunched = await backendIdentity()
  expect(relaunched.verified).toBe(true)
  expect(relaunched.fingerprint).not.toBe(before.fingerprint)
  await expectRetiredWorkspaceCapability(page)
})
