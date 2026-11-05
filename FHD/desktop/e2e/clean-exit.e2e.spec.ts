import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test'
import fs from 'node:fs'
import net from 'node:net'
import os from 'node:os'
import path from 'node:path'

/** 真实 Electron 退出场景：正常退出不得记成崩溃，真实崩溃仍要记录。 */

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

type Launched = { app: ElectronApplication; page: Page; userDataDir: string; port: number; logPath: string }

async function launchApp(): Promise<Launched> {
  const port = await findFreePort()
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-e2e-exit-'))
  const app = await electron.launch({
    args: ['-r', path.join(__dirname, 'patch-backend.cjs'), '.'],
    cwd: path.resolve(__dirname, '..'),
    env: {
      ...process.env,
      XCAGI_DESKTOP_E2E: '1',
      XCAGI_DESKTOP_PORT: String(port),
      XCAGI_DESKTOP_USER_DATA_DIR: userDataDir,
      PYTHON: path.resolve(__dirname, 'stub-backend.mjs'),
    },
  })
  const page = await app.firstWindow()
  await page.waitForURL(`http://127.0.0.1:${port}/?shell=1`, { timeout: 90_000 })
  await expect(page.locator('#e2e-marker')).toHaveText('XCAGI_E2E_OK')
  return { app, page, userDataDir, port, logPath: path.join(userDataDir, 'logs', 'electron-backend.log') }
}

function readLog(launched: Launched): string {
  try {
    return fs.readFileSync(launched.logPath, 'utf8')
  } catch {
    return ''
  }
}

test('正常退出不写入渲染进程崩溃记录', async () => {
  const launched = await launchApp()
  try {
    await launched.app.close()
    const log = readLog(launched)
    expect(log).not.toContain('[crash] renderer gone')
    expect(log).not.toContain('[crash] reloading renderer')
    expect(log).not.toContain('[crash] skip reload')
  } finally {
    fs.rmSync(launched.userDataDir, { recursive: true, force: true })
  }
})

test('真实渲染进程崩溃仍被记录并触发重载', async () => {
  const launched = await launchApp()
  try {
    await launched.app.evaluate(({ BrowserWindow }) => {
      BrowserWindow.getAllWindows()[0]?.webContents.forcefullyCrashRenderer()
    })
    await new Promise(resolve => setTimeout(resolve, 3_000))
    await launched.app.close()
    const log = readLog(launched)
    expect(log).toContain('[crash] renderer gone')
    expect(log).toContain('reason=crashed')
    expect(log).toContain('[crash] reloading renderer')
  } finally {
    fs.rmSync(launched.userDataDir, { recursive: true, force: true })
  }
})
