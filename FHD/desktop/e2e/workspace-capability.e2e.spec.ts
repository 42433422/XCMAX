import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test'
import fs from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'

// Real Electron frames/network + a child backend; Python HTTP tests enforce its authorization.
let app: ElectronApplication
let page: Page
let root: string
let backendPort: number
let sink: http.Server
let sinkUrl: string

async function listen(server: http.Server): Promise<number> {
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', resolve)
  })
  return (server.address() as { port: number }).port
}

async function launch(): Promise<void> {
  app = await electron.launch({
    args: ['-r', path.join(__dirname, 'patch-backend.cjs'), '.'],
    cwd: path.resolve(__dirname, '..'),
    env: {
      ...process.env, XCAGI_DESKTOP_E2E: '1', XCAGI_DESKTOP_PORT: String(backendPort),
      XCAGI_DESKTOP_USER_DATA_DIR: root, XCAGI_DESKTOP_E2E_REDIRECT_URL: sinkUrl,
      PYTHON: path.join(__dirname, 'stub-backend.mjs'),
    },
  })
  page = await app.firstWindow()
  await page.waitForURL(`http://127.0.0.1:${backendPort}/?shell=1`)
}

async function status(target: Page): Promise<number> {
  return target.evaluate(async () => (await fetch('/api/local-workspace/status', {
    headers: { 'X-XCAGI-Desktop-Local': '1' },
  })).status)
}

async function fingerprint(): Promise<string> {
  return app.evaluate(({ app }) => {
    const requireFromApp = process.getBuiltinModule('module').createRequire(
      process.getBuiltinModule('path').join(app.getAppPath(), 'package.json'),
    )
    return process.getBuiltinModule('crypto').createHash('sha256')
      .update(requireFromApp('./dist/backend-env.js').desktopWorkspaceToken).digest('hex')
  })
}

test.beforeAll(async () => {
  const portProbe = http.createServer()
  backendPort = await listen(portProbe)
  await new Promise<void>(resolve => portProbe.close(() => resolve()))
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-workspace-capability-'))
  sink = http.createServer((request, response) => {
    response.writeHead(200, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Headers': 'X-XCAGI-Desktop-Local, X-XCAGI-Workspace-Capability',
      'Content-Type': 'application/json',
    })
    response.end(JSON.stringify({ capability: Boolean(request.headers['x-xcagi-workspace-capability']) }))
  })
  sinkUrl = `http://127.0.0.1:${await listen(sink)}/receive`
  await launch()
})

test.afterAll(async () => {
  if (app) await app.close()
  if (sink) await new Promise<void>(resolve => sink.close(() => resolve()))
  if (root) fs.rmSync(root, { recursive: true, force: true })
})

test('anonymous owned main and auxiliary frames authenticate; an ordinary local client cannot', async () => {
  const ordinary = await fetch(`http://127.0.0.1:${backendPort}/api/local-workspace/status`, {
    headers: { 'X-XCAGI-Desktop-Local': '1' },
  })
  expect(ordinary.status).toBe(403)
  expect(await status(page)).toBe(200)
  expect(await page.evaluate(() => document.cookie)).not.toContain('session_id')
  const opened = app.waitForEvent('window')
  await page.evaluate(() => (
    window as unknown as { xcagiDesktop: { openWindow: (url: string) => Promise<unknown> } }
  ).xcagiDesktop.openWindow(window.location.origin))
  const auxiliary = await opened
  await auxiliary.waitForURL(`http://127.0.0.1:${backendPort}/`)
  expect(await status(auxiliary)).toBe(200)
  await auxiliary.close()
})

test('a same-origin iframe and an unregistered window never receive the capability', async () => {
  await page.evaluate(() => {
    const iframe = document.createElement('iframe')
    iframe.src = '/'
    document.body.append(iframe)
  })
  await expect.poll(() => page.frames().length).toBe(2)
  const iframe = page.frames().find(frame => frame !== page.mainFrame())!
  await iframe.waitForURL(`http://127.0.0.1:${backendPort}/`)
  expect(await iframe.evaluate(async () => (await fetch('/api/local-workspace/status', {
    headers: { 'X-XCAGI-Desktop-Local': '1' },
  })).status)).toBe(403)
  const opened = app.waitForEvent('window')
  await app.evaluate(async ({ BrowserWindow }, port) => {
    const unrelated = new BrowserWindow({ show: false, webPreferences: { sandbox: true, contextIsolation: true } })
    await unrelated.loadURL(`http://127.0.0.1:${port}/`)
  }, backendPort)
  const unrelated = await opened
  expect(await status(unrelated)).toBe(403)
  await unrelated.close()
})

test('Chromium removes the capability on a redirected next hop and on direct non-workspace requests', async () => {
  const redirected = await page.evaluate(async () => (await fetch('/api/local-workspace/redirect', {
    headers: { 'X-XCAGI-Desktop-Local': '1' },
  })).json())
  expect(redirected).toEqual({ capability: false })
  const direct = await page.evaluate(async url => (await fetch(url, {
    headers: { 'x-XCAGI-Workspace-Capability': 'renderer-forged' },
  })).json(), sinkUrl)
  expect(direct).toEqual({ capability: false })
})

test('backend restart retains the capability; restarting the main process rotates it', async () => {
  const before = await fingerprint()
  await app.evaluate(async ({ app }, port) => {
    const requireFromApp = process.getBuiltinModule('module').createRequire(
      process.getBuiltinModule('path').join(app.getAppPath(), 'package.json'),
    )
    const backend = requireFromApp('./dist/backend-process.js')
    await backend.stopBackend()
    await backend.startBackend()
    await backend.waitForBackendPing(port, 10_000)
  }, backendPort)
  expect(await status(page)).toBe(200)
  expect(await fingerprint()).toBe(before)
  await app.close()
  await launch()
  expect(await status(page)).toBe(200)
  expect(await fingerprint()).not.toBe(before)
})
