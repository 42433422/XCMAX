import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test'
import fs from 'node:fs'
import net from 'node:net'
import os from 'node:os'
import path from 'node:path'

/**
 * 真实端到端：启动完整 Electron 应用（dist/main.js），由 stub-backend.mjs
 * 充当本地后端，验证单测（mock electron）无法覆盖的真实链路：
 *   主进程 bootstrap → spawn 后端子进程 → /api/ping 就绪探测 → splash 进度
 *   → loadURL 主界面 → preload contextBridge → 渲染进程 IPC invoke → 主进程 handle。
 */

let electronApp: ElectronApplication
let page: Page
let userDataDir: string
let backendPort: number

type XcagiDesktopBridge = {
  getDataDir: () => Promise<string>
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

test.beforeAll(async () => {
  backendPort = await findFreePort()
  userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-e2e-userdata-'))
  electronApp = await electron.launch({
    args: ['.'],
    cwd: path.resolve(__dirname, '..'),
    env: {
      ...process.env,
      // E2E 隔离开关：跳过登录项/协议注册/全局快捷键/OTA 自动检查（见 main.ts）
      XCAGI_DESKTOP_E2E: '1',
      XCAGI_DESKTOP_PORT: String(backendPort),
      XCAGI_DESKTOP_USER_DATA_DIR: userDataDir,
      // dev 模式后端可执行文件 → 指向 E2E stub（node shebang 脚本）
      PYTHON: path.resolve(__dirname, 'stub-backend.mjs'),
    },
  })
  page = await electronApp.firstWindow()
  page.on('console', msg => {
    if (msg.type() === 'error') {
      console.info(`[renderer console.error] ${msg.text()}`)
    }
  })
})

test.afterAll(async () => {
  if (electronApp) {
    await electronApp.close()
  }
  if (userDataDir) {
    fs.rmSync(userDataDir, { recursive: true, force: true })
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
